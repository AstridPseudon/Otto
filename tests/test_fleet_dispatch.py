from __future__ import annotations

import pytest
import threading
import time
import os
import tempfile
from types import SimpleNamespace

from herzchen.fleet.capacity import CapacityPool, CapacityPolicy
from herzchen.fleet.dispatch import DispatchError, FleetDispatcher
from herzchen.fleet.hosts.contract import McpGrant, McpServer, TurnSpec
from herzchen.fleet.tools.tokens import TokenBook
from herzchen.domains.work.admission import authoring_stamp
from herzchen.domains.work.readiness import ready as work_ready
from herzchen.contracts import ResourceRef
from otto.hostctl.product_service import bind_automatic_dispatch
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import OwnerCompletion
from unittest.mock import patch


def _task(task_id):
    payload = {"kind": "task", "title": "Task", "name": "Task", "fields": {"check": ["true"]},
               "dependencies": []}
    payload["metadata_namespaces"] = {
        "work.admission": authoring_stamp("rev-7", payload, "reviewer")
    }
    return SimpleNamespace(id=task_id, assignment=task_id,
        ref=ResourceRef("test", "work.task", task_id, "rev-9"), payload=payload, lifecycle="pending")


def _spec(task, role, token, _context, *, tools=("task", "check", "done")):
    grant = McpGrant(servers=(McpServer("otto", "/usr/bin/python3", tools=tools),),
                     token_env="OTTO_TOKEN_A1", token=token, token_env_prefix="OTTO_TOKEN_")
    return TurnSpec("/usr/bin/agent", "/tmp", "work", "model", "high", mcp=grant)


def _dispatcher(ready, launch, *, counts=(0, 0), make_spec=_spec):
    pool = CapacityPool(CapacityPolicy())
    book = TokenBook()
    dispatcher = FleetDispatcher(pool, book, ready=ready, role_for=lambda _task: "worker",
        policy_for=lambda _role: pool.policy, active_counts=lambda: counts,
        make_spec=make_spec, launch=launch, mcp_server_name="otto", mcp_tools=("task", "check", "done"),
        read_current=lambda task, **_context: task)
    return dispatcher, pool, book


def test_rechecks_readiness_immediately_before_retry_launch_and_records_admitted_pin():
    checks = []
    task = _task("a1")

    def ready(_task, **context):
        checks.append(context)
        return {"ready": len(checks) < 2, "blockers": ["changed"]}

    launched = []
    dispatcher, pool, book = _dispatcher(ready, lambda spec, context: launched.append(spec) or "run",
                                         counts=(0, 0))
    with pytest.raises(DispatchError, match="not ready"):
        dispatcher.dispatch(task, retry=True)
    assert checks[-1]["retry"] is True
    assert launched == []
    assert pool.snapshot()["turns"]["reserved"] == 0
    assert not book.live()


def test_launch_issues_assignment_token_for_exact_otto_tool_grant():
    task = _task("a2")
    captured = []
    dispatcher, pool, book = _dispatcher(lambda *_a, **_kw: True,
        lambda spec, _context: captured.append(spec) or "run-2")
    record = dispatcher.dispatch(task, resume=True)
    assert record.admitted_revision == "rev-7"
    assert record.state == "launched"
    assert book.resolve(record.token).assignment == "a2"
    assert book.resolve(record.token).role == "worker"
    assert captured[0].mcp.servers[0].name == "otto"
    assert pool.snapshot()["turns"]["reserved"] == 1


def test_refuses_extra_mcp_server_or_tool_surface_before_launch():
    task = _task("a3")
    launched = []
    def bad_spec(task, role, token, context):
        spec = _spec(task, role, token, context)
        return TurnSpec(spec.executable, spec.workspace, spec.prompt, spec.model, spec.reasoning,
            mcp=McpGrant(servers=(spec.mcp.servers[0], McpServer("extra", "/usr/bin/true")),
                         token_env=spec.mcp.token_env, token=spec.mcp.token,
                         token_env_prefix=spec.mcp.token_env_prefix))
    dispatcher, _pool, book = _dispatcher(lambda *_a, **_kw: True,
        lambda *_a: launched.append(True), make_spec=bad_spec)
    with pytest.raises(DispatchError, match="exactly the Otto"):
        dispatcher.dispatch(task)
    assert launched == []
    assert not book.live()


def test_refuses_initializer_that_would_suppress_the_sole_mcp_server():
    def initializer(task, role, token, context):
        spec = _spec(task, role, token, context)
        return TurnSpec(spec.executable, spec.workspace, spec.prompt, spec.model,
                        spec.reasoning, initializer=True, mcp=spec.mcp)

    dispatcher, pool, book = _dispatcher(lambda *_a, **_kw: True,
        lambda *_a: pytest.fail("initializer launched"), make_spec=initializer)
    with pytest.raises(DispatchError, match="initializer"):
        dispatcher.dispatch(_task("initializer"))
    assert pool.snapshot()["turns"]["reserved"] == 0
    assert not book.live()


def test_refuses_when_initial_readiness_fails_without_role_or_launch():
    roles = []
    dispatcher, pool, book = _dispatcher(lambda *_a, **_kw: {"ready": False, "blockers": ["gate"]},
        lambda *_a: pytest.fail("launch called"))
    dispatcher.role_for = lambda _task: roles.append(True) or "worker"
    with pytest.raises(DispatchError, match="gate"):
        dispatcher.dispatch(_task("a4"))
    assert roles == []
    assert pool.snapshot()["turns"]["reserved"] == 0
    assert not book.live()


def _dependency(kind, identity, lifecycle):
    return SimpleNamespace(ref=ResourceRef("test", kind, identity, "dep-rev"),
        payload={"lifecycle": lifecycle}, lifecycle=lifecycle)


def _ready_with(records, *, gate_satisfied=None):
    return lambda task, **_context: work_ready(
        task, read_record=lambda ref: records.get(ref.id), gate_satisfied=gate_satisfied)


@pytest.mark.parametrize("path", [{}, {"retry": True}, {"resume": True}], ids=["fresh", "retry", "resume"])
def test_unadmitted_never_dispatches_any_path(path):
    task = _task("unadmitted")
    task.payload["fields"]["check"] = ["changed after approval"]
    launched = []
    dispatcher, _pool, book = _dispatcher(_ready_with({}), lambda *_a: launched.append(True))
    with pytest.raises(DispatchError, match="not ready"):
        dispatcher.dispatch(task, **path)
    assert launched == []
    assert not book.live()


@pytest.mark.parametrize("path", [{}, {"retry": True}, {"resume": True}], ids=["fresh", "retry", "resume"])
def test_blocked_dep_waits(path):
    dep_ref = ResourceRef("test", "work.task", "prerequisite", "old-rev")
    task = _task("blocked-dep")
    task.payload["dependencies"] = [dep_ref]
    dep = _dependency("work.task", "prerequisite", "active")
    launched = []
    dispatcher, _pool, _book = _dispatcher(_ready_with({"prerequisite": dep}),
        lambda *_a: launched.append(True))
    with pytest.raises(DispatchError, match="not ready"):
        dispatcher.dispatch(task, **path)
    assert launched == []


@pytest.mark.parametrize("path", [{}, {"retry": True}, {"resume": True}], ids=["fresh", "retry", "resume"])
def test_gate_dep_waits(path):
    gate_ref = ResourceRef("test", "work.gate", "approval", "old-rev")
    task = _task("blocked-gate")
    task.payload["dependencies"] = [gate_ref]
    gate = _dependency("work.gate", "approval", "active")
    launched = []
    dispatcher, _pool, _book = _dispatcher(_ready_with({"approval": gate}, gate_satisfied=lambda _g: False),
        lambda *_a: launched.append(True))
    with pytest.raises(DispatchError, match="not ready"):
        dispatcher.dispatch(task, **path)
    assert launched == []


def test_manager_not_woken_for_routine():
    wakes = []
    routine_role_calls = []
    pool = CapacityPool(CapacityPolicy())
    dispatcher = FleetDispatcher(pool, TokenBook(), ready=_ready_with({}),
        role_for=lambda _task: routine_role_calls.append("worker") or "worker",
        policy_for=lambda _role: pool.policy, active_counts=lambda: (0, 0),
        make_spec=_spec, launch=lambda _spec, _context: "run",
        mcp_server_name="otto", mcp_tools=("task", "check", "done"), read_current=lambda task, **_ctx: task)
    # Manager waking is an owner scheduling action and is not an input to routine dispatch.
    record = dispatcher.dispatch(_task("routine"))
    assert record.role == "worker"
    assert routine_role_calls == ["worker"]
    assert wakes == []

    manager_dispatcher = FleetDispatcher(pool, TokenBook(), ready=_ready_with({}),
        role_for=lambda _task: "manager", policy_for=lambda _role: pool.policy,
        active_counts=lambda: (0, 0), make_spec=_spec,
        launch=lambda *_a: pytest.fail("routine manager launch called"),
        mcp_server_name="otto", mcp_tools=("task", "check", "done"), read_current=lambda task, **_ctx: task)
    with pytest.raises(DispatchError, match="cannot launch or wake a manager"):
        manager_dispatcher.dispatch(_task("manager-routine"))
    assert wakes == []


@pytest.mark.parametrize("path", [{}, {"retry": True}, {"resume": True}], ids=["fresh", "retry", "resume"])
def test_launch_carries_assignment_token(path):
    launched = []
    dispatcher, _pool, book = _dispatcher(_ready_with({}),
        lambda spec, context: launched.append((spec, context)) or "run")
    record = dispatcher.dispatch(_task("token-assignment"), **path)
    spec, context = launched[0]
    assert context["assignment"] == "token-assignment"
    assert spec.mcp.token == record.token
    grant = book.resolve(spec.mcp.token)
    assert (grant.assignment, grant.role) == ("token-assignment", "worker")
    assert spec.mcp.token_env == "OTTO_TOKEN_A1"


def test_launch_exception_is_unknown_and_holds_token_and_capacity_until_settled():
    dispatcher, pool, book = _dispatcher(_ready_with({}),
        lambda *_a: (_ for _ in ()).throw(RuntimeError("spawn status uncertain")))
    with pytest.raises(DispatchError, match="spawn status uncertain"):
        dispatcher.dispatch(_task("uncertain"))
    record = dispatcher.records["uncertain"]
    assert record.state == "unknown"
    assert book.resolve(record.token).assignment == "uncertain"
    assert pool.snapshot()["turns"]["reserved"] == 1
    with pytest.raises(DispatchError, match="active dispatch"):
        dispatcher.dispatch(_task("uncertain"), retry=True)
    dispatcher.finish("uncertain", settled=False)
    assert record.state == "released"
    assert not book.live()
    assert pool.snapshot()["turns"]["reserved"] == 0


def test_current_record_lookup_is_required_and_used_at_final_readiness_check():
    blocked = _task("current-changed")
    blocked.payload["fields"]["check"] = ["changed after admission"]
    reads = []
    def read_current(task, **_context):
        reads.append(task)
        return task if len(reads) == 1 else blocked
    pool = CapacityPool(CapacityPolicy())
    book = TokenBook()
    dispatcher = FleetDispatcher(pool, book, ready=_ready_with({}), role_for=lambda _task: "worker",
        policy_for=lambda _role: pool.policy, active_counts=lambda: (0, 0), make_spec=_spec,
        launch=lambda *_a: pytest.fail("launch called"), mcp_server_name="otto", mcp_tools=("task", "check", "done"),
        read_current=read_current)
    with pytest.raises(DispatchError, match="admission changed"):
        dispatcher.dispatch(_task("current-changed"))
    assert len(reads) == 2
    assert pool.snapshot()["turns"]["reserved"] == 0
    assert not book.live()


def test_ready_scan_skips_blocked_and_unadmitted_tasks():
    blocked = _task("blocked")
    blocked.payload["dependencies"] = [ResourceRef("test", "work.task", "prerequisite", "old")]
    unadmitted = _task("unadmitted-scan")
    unadmitted.payload["fields"]["check"] = ["changed after admission"]
    selected = _task("selected")
    launched = []
    dispatcher, _pool, book = _dispatcher(
        _ready_with({"prerequisite": _dependency("work.task", "prerequisite", "active")}),
        lambda spec, _context: launched.append(spec))
    record = dispatcher.dispatch_ready([blocked, unadmitted, selected])
    assert record.task is selected
    assert len(launched) == 1
    assert book.live() == frozenset({record.assignment})
    assert "blocked" not in dispatcher.records
    assert "unadmitted-scan" not in dispatcher.records


def test_concurrent_owner_selectors_launch_one_task_generation():
    task = _task("raced")
    pool = CapacityPool(CapacityPolicy())
    book = TokenBook()
    calls = []
    gate = threading.Barrier(3)

    def launch(current, _context):
        calls.append(current.ref.id)
        time.sleep(0.02)
        return {"outcome": "admitted"}

    dispatcher = FleetDispatcher(pool, book, ready=_ready_with({}),
        role_for=lambda _task: "worker", policy_for=lambda _role: pool.policy,
        active_counts=lambda: (0, 0), make_spec=None, launch=launch,
        mcp_server_name="otto", mcp_tools=(), read_current=lambda current, **_kw: current)
    results = []

    def pump():
        gate.wait()
        results.append(dispatcher.dispatch_ready([task]))

    threads = [threading.Thread(target=pump) for _ in range(2)]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert calls == ["raced"]
    assert sum(result is not None for result in results) == 1
    dispatcher.finish("raced")
    assert dispatcher.dispatch_ready([task]) is None


def test_unknown_launch_must_be_settled_before_any_retry_attempt():
    task = _task("uncertain-once")
    launch_attempts = []

    def launch(_task, _context):
        launch_attempts.append("attempt")
        raise RuntimeError("spawn outcome unknown")

    dispatcher, _pool, book = _dispatcher(_ready_with({}), launch, make_spec=None)
    with pytest.raises(DispatchError, match="spawn outcome unknown"):
        dispatcher.dispatch(task)

    assert launch_attempts == ["attempt"]
    assert dispatcher.records["uncertain-once"].state == "unknown"
    with pytest.raises(DispatchError, match="active dispatch"):
        dispatcher.dispatch(task, retry=True)
    assert launch_attempts == ["attempt"]

    dispatcher.finish("uncertain-once", settled=False)
    assert not book.live()


def _staging_dispatch_fixture(task_specs, submit_worker, tmp_path):
    """Small in-memory owner surface for the product automatic dispatch pump."""
    tasks = {}
    refs = {}
    for alias, admitted in task_specs:
        payload = {"kind": "task", "title": alias, "name": alias,
            "fields": {"instructions": "Implement " + alias, "check": ["true"]},
            "dependencies": [], "project_ref": {"authority": "fixture", "kind": "work.project", "id": "project", "revision": "project-rev"},
            "metadata_namespaces": {"otto.plan": {"route": "normal"}}}
        if admitted:
            payload["metadata_namespaces"]["work.admission"] = authoring_stamp("revision-" + alias, payload, "owner")
        ref = ResourceRef("fixture", "work.task", alias, "revision-" + alias)
        task = SimpleNamespace(id=alias, title=alias, ref=ref, payload=payload, lifecycle="pending")
        tasks[alias] = task
        refs[alias] = ref

    project = SimpleNamespace(ref=ResourceRef("fixture", "work.project", "project", "project-rev"),
        payload={"lifecycle": "pending"})
    def get_record(ref):
        return project if ref.id == "project" else tasks.get(ref.id)
    reader = SimpleNamespace(get_identity=lambda ref: tasks[ref.id], get_record=get_record)
    graph = SimpleNamespace(current=lambda ref: tasks[ref.id], reader=reader)
    owner = SimpleNamespace(graph=graph, owner_actor=object(), store=SimpleNamespace(consumer=lambda: object()))
    state = {"project_ref": {"authority": "fixture", "kind": "work.project", "id": "project", "revision": "project-rev"},
        "task_refs": {alias: ref.to_dict() for alias, ref in refs.items()}, "workers": {}}
    due_rows = {}
    view = SimpleNamespace(server=SimpleNamespace(state=state,
        due_port=SimpleNamespace(read_due=lambda schedule: due_rows.get(schedule)), _save_state=lambda: None),
        _submit_worker=None)
    host = ExecutionHost(directory=tmp_path, handler=lambda _request: {}, bounded_transports=True,
        capacity_policy=CapacityPolicy(turn_units=1, manager_reserve=0, heavy_headroom=1, worker_floor=0))
    host.admission_calls = []
    original_admit = host.admit_execution
    def admit_execution(app, due, operation):
        host.admission_calls.append(due.schedule_id)
        return host._owned(lambda: original_admit(app, due, operation))
    host.admit_execution = admit_execution
    host.restore_execution = lambda _app, _due: None
    app = SimpleNamespace(runtime=SimpleNamespace(adapter=SimpleNamespace(
        owner_transport_only=True, worktree=str(tmp_path))),
        portfolio=SimpleNamespace(operations=SimpleNamespace(reader=reader, _owner_reader=reader)),
        _read=lambda schedule: due_rows[schedule]["_due"])
    registry = SimpleNamespace(owner=owner, tokens=TokenBook())
    registry.bind_dispatcher = lambda dispatcher: (setattr(registry, "dispatcher", dispatcher),
                                                     setattr(registry, "tokens", dispatcher.tokens))
    view._submit_worker = lambda request, **kwargs: submit_worker(
        host, app, view, due_rows, request, **kwargs)
    with patch("otto.portfolio.dependencies.PortfolioDependencies",
               return_value=SimpleNamespace(readiness=lambda _ref, **_kw: {"ready": True})):
        dispatcher = bind_automatic_dispatch(host, registry, {"project": view})
    return host, view, due_rows, dispatcher


def test_automatic_dispatch_admits_serially_skips_unadmitted_and_lands_each_generation(tmp_path):
    launches = []

    def submit(host, app, view, due_rows, request, *, automatic=False, automatic_revision=None):
        assert automatic is True
        alias = request["task"]
        task = view.server.state["task_refs"][alias]
        assignment = next(key for key, record in host.dispatcher.records.items()
                          if record.task.ref.id == alias)
        schedule = "worker-" + alias
        due = SimpleNamespace(schedule_id=schedule, project_ref="project", role="worker",
            assignment_ref={"authority": "fixture", "kind": "wrk.assignment", "id": assignment},
            generation=1, target={"task_ref": task, "project_ref": {"authority": "fixture", "kind": "work.project", "id": "project", "revision": "project-rev"}},
            host_evidence={}, profile="workspace-write", host_state="ready")
        due_rows[schedule] = {"completion_state": "active", "target": due.target,
            "assignment_ref": due.assignment_ref, "generation": due.generation,
            "host_evidence": {}, "_due": due}
        view.server.state["workers"][alias] = {"schedule_id": schedule, "assignment_ref": due.assignment_ref,
            "automatic": True, "automatic_revision": automatic_revision, "generation": 1}
        pending = OwnerCompletion()
        host.admit_execution(app, due, lambda: (launches.append(alias), pending)[1])
        view.server.state["workers"][alias]["completion"] = pending
        return {"outcome": "admitted", "assignment_ref": due.assignment_ref}

    host, view, due_rows, dispatcher = _staging_dispatch_fixture(
        [("A", True), ("B", True), ("C", False)], submit, tmp_path)
    host.dispatcher = dispatcher
    host.dispatch_pump()
    with patch("otto.portfolio.execution_operations.recheck_execution_admission", return_value="admitted"):
        host._owned(host._start_ready_executions)
    assert launches == ["A"]
    assert host.admission_calls == ["worker-A"]
    assert view.server.state["workers"]["A"]["automatic"] is True

    host.dispatch_pump()
    assert launches == ["A"]

    due_rows["worker-A"]["completion_state"] = "succeeded"
    view.server.state["workers"]["A"]["completion"].resolve({"outcome": "succeeded"})
    dispatcher.finish(next(iter(dispatcher.records)))
    host.dispatch_pump()
    with patch("otto.portfolio.execution_operations.recheck_execution_admission", return_value="admitted"):
        host._owned(host._start_ready_executions)
    assert launches == ["A", "B"]
    assert host.admission_calls == ["worker-A", "worker-B"]
    assert "C" not in view.server.state["workers"]
    assert len([row for row in dispatcher.records.values() if row.state == "launched"]) == 1


def test_automatic_known_launch_failure_settles_with_reason_without_sticking_alias(tmp_path):
    calls = []
    launches = []

    def submit(host, app, view, due_rows, request, *, automatic=False, automatic_revision=None):
        alias = request["task"]
        calls.append(alias)
        if alias == "A":
            return {"outcome": "rejected", "reason": "known pre-effect refusal",
                "provider_called": False, "effects_started": False}
        assignment = next(key for key, record in host.dispatcher.records.items()
                          if record.task.ref.id == alias)
        schedule = "worker-" + alias
        raw_task_ref = view.server.state["task_refs"][alias]
        project_ref = view.server.state["project_ref"]
        due = SimpleNamespace(schedule_id=schedule, project_ref="project", role="worker",
            assignment_ref={"authority": "fixture", "kind": "wrk.assignment", "id": assignment},
            generation=1, target={"task_ref": raw_task_ref, "project_ref": project_ref},
            host_evidence={}, profile="workspace-write", host_state="ready")
        due_rows[schedule] = {"completion_state": "active", "target": due.target,
            "assignment_ref": due.assignment_ref, "generation": due.generation,
            "host_evidence": {}, "_due": due}
        view.server.state["workers"][alias] = {"schedule_id": schedule,
            "assignment_ref": due.assignment_ref, "automatic": True,
            "automatic_revision": automatic_revision, "generation": 1}
        host.admit_execution(app, due, lambda: launches.append(alias) or {"outcome": "landed"})
        return {"outcome": "admitted", "assignment_ref": due.assignment_ref}

    host, view, due_rows, dispatcher = _staging_dispatch_fixture(
        [("A", True), ("B", True), ("C", False)], submit, tmp_path)
    host.dispatcher = dispatcher
    host.dispatch_pump()

    assert calls == ["A"]
    assert view.server.state["automatic_dispatch_failures"]["A"]["reason"] == "known pre-effect refusal"
    assert "A" not in view.server.state["workers"]
    assert next(iter(dispatcher.records.values())).state in {"released", "settled"}
    host.dispatch_pump()
    with patch("otto.portfolio.execution_operations.recheck_execution_admission", return_value="admitted"):
        host._owned(host._start_ready_executions)
    assert calls == ["A", "B"]
    assert launches == ["B"]
    assert host.admission_calls == ["worker-B"]
    assert view.server.state["workers"]["B"]["automatic"] is True
    assert "C" not in view.server.state["workers"]

    # A remains fenced for this admitted generation while another pump runs.
    assert due_rows["worker-B"]["completion_state"] == "active"
    host.dispatch_pump()
    assert calls == ["A", "B"]


def test_retained_automatic_failure_callback_settles_only_explicit_no_effect_evidence(tmp_path):
    def submit(host, app, view, due_rows, request, *, automatic=False, automatic_revision=None):
        alias = request["task"]
        assignment = next(key for key, record in host.dispatcher.records.items()
                          if record.task.ref.id == alias)
        schedule = "worker-" + alias
        raw_task_ref = view.server.state["task_refs"][alias]
        project_ref = view.server.state["project_ref"]
        due = SimpleNamespace(schedule_id=schedule, project_ref="project", role="worker",
            assignment_ref={"authority": "fixture", "kind": "wrk.assignment", "id": assignment},
            generation=1, target={"task_ref": raw_task_ref, "project_ref": project_ref},
            host_evidence={}, profile="workspace-write", host_state="ready")
        due_rows[schedule] = {"completion_state": "active", "target": due.target,
            "assignment_ref": due.assignment_ref, "generation": due.generation, "host_evidence": {}}
        view.server.state["workers"][alias] = {"schedule_id": schedule,
            "assignment_ref": due.assignment_ref, "automatic": True,
            "automatic_revision": automatic_revision, "generation": 1}
        host.admit_execution(app, due, lambda: {"outcome": "partial"})
        return {"outcome": "admitted", "assignment_ref": due.assignment_ref}

    host, view, due_rows, dispatcher = _staging_dispatch_fixture([("A", True)], submit, tmp_path)
    host.dispatcher = dispatcher
    host.dispatch_pump()
    with patch("otto.portfolio.execution_operations.recheck_execution_admission", return_value="admitted"):
        host._owned(host._start_ready_executions)
    failure = {"outcome": "partial", "reason": "runtime preparation failed",
        "provider_called": False, "effects_started": False}
    unknown = {"outcome": "partial", "reason": "insufficient evidence"}
    with pytest.raises(PermissionError, match="explicit pre-effect evidence"):
        host.settle_automatic_failure("project", "A", "worker-A", unknown)
    assert next(iter(dispatcher.records.values())).state == "launched"
    assert dispatcher.tokens.live()

    settled = host.settle_automatic_failure("project", "A", "worker-A", failure)
    assert settled["outcome"] == "settled"
    assert view.server.state["automatic_dispatch_failures"]["A"]["reason"] == "runtime preparation failed"
    assert next(iter(dispatcher.records.values())).state == "settled"
    assert not dispatcher.tokens.live()


def _process_fd_count():
    """Count this process's descriptors on macOS/Linux; caller handles unsupported hosts."""
    paths = ("/dev/fd", "/proc/self/fd")
    for path in paths:
        if os.path.isdir(path):
            return len(os.listdir(path))
    pytest.skip("no process descriptor census is available")


def test_owner_direction_surface_reuse_keeps_descriptor_count_flat():
    from herzchen.authoring import domain_contribution as authoring_contribution
    from herzchen.content import domain_contribution as content_contribution
    from herzchen.domains.work import contributions
    from herzchen.contracts import ResourceRef
    from herzchen.kernel import Store
    from otto.portfolio.herzchen_binding import HerzchenBindingConfig
    from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap

    with tempfile.TemporaryDirectory() as directory:
        store = Store.create(os.path.join(directory, "owner.sqlite"), authority="fd-test-owner")
        try:
            store.register_domain_handler((*contributions(), content_contribution(), authoring_contribution()))
            owner = PortfolioOwnerBootstrap(store,
                binding=HerzchenBindingConfig(store.authority, "fd-test-credential"), owner_actor="owner")
            # Prime the cache and let transient directory enumeration handles close.
            try:
                owner.direction_surface()
                native_bodies = object()
                project_ref = ResourceRef(store.authority, "work.project", "fd-project")
                assignment_ref = ResourceRef(store.authority, "wrk.assignment", "fd-assignment")
                owner.late_usage_operation(project_ref=project_ref,
                    authorizing_assignment_ref=assignment_ref, authorizing_generation=1,
                    native_bodies=native_bodies)
                with pytest.raises(ValueError, match="different native bodies provider"):
                    owner.late_usage_operation(project_ref=project_ref,
                        authorizing_assignment_ref=assignment_ref, authorizing_generation=1,
                        native_bodies=object())
            except (PermissionError, OSError) as error:
                pytest.skip(f"AF_UNIX bind denied in this sandbox: {error}")
            before = _process_fd_count()
            for _ in range(500):
                assert owner.direction_surface() is not None
                assert owner.late_usage_operation(project_ref=project_ref,
                    authorizing_assignment_ref=assignment_ref, authorizing_generation=1,
                    native_bodies=native_bodies) is not None
            after = _process_fd_count()
            assert after <= before + 3
        finally:
            store.close()


def test_dispatch_ready_retries_prelaunch_failure_only_after_admitted_revision_changes():
    task = _task("prelaunch-refusal")
    attempts = []

    def make_spec(current, _role, _token, _context):
        attempts.append(current.payload["metadata_namespaces"]["work.admission"]["revision"])
        raise RuntimeError("assignment is not ready: spec preparation failed")

    dispatcher, _pool, _book = _dispatcher(_ready_with({}), lambda *_a: "unreachable",
        make_spec=make_spec)
    with pytest.raises(DispatchError, match="assignment is not ready: spec preparation failed"):
        dispatcher.dispatch_ready([task])
    assert attempts == ["rev-7"]

    before = _process_fd_count()
    for _ in range(500):
        assert dispatcher.dispatch_ready([task]) is None
    after = _process_fd_count()
    assert after <= before + 3
    assert attempts == ["rev-7"]

    task.payload["metadata_namespaces"]["work.admission"] = authoring_stamp(
        "rev-8", task.payload, "reviewer")
    with pytest.raises(DispatchError, match="assignment is not ready: spec preparation failed"):
        dispatcher.dispatch_ready([task])
    assert attempts == ["rev-7", "rev-8"]


def test_dispatch_ready_retries_transient_final_readiness_refusal_on_next_pump():
    task = _task("transient-final-readiness")
    readiness_checks = []
    launches = []

    def ready(_current, **_context):
        readiness_checks.append(True)
        # dispatch_ready's scan and dispatch's initial check pass. The final
        # prelaunch check refuses once, then the next pump observes recovery.
        return len(readiness_checks) != 3

    dispatcher, _pool, _book = _dispatcher(_ready_with({}),
        lambda _spec, _context: launches.append("launched") or "run")
    dispatcher.ready = ready

    assert dispatcher.dispatch_ready([task]) is None
    assert launches == []
    assert dispatcher.records["transient-final-readiness"].state == "refused"

    record = dispatcher.dispatch_ready([task])
    assert record is not None
    assert record.state == "launched"
    assert launches == ["launched"]
    assert len(readiness_checks) == 6


def test_automatic_failed_launch_is_fenced_per_admitted_revision_across_pumps(tmp_path):
    calls = []

    def submit(_host, _app, _view, _due_rows, request, *, automatic=False, automatic_revision=None):
        assert automatic is True
        calls.append((request["task"], automatic_revision))
        return {"outcome": "rejected", "reason": "known pre-effect refusal",
            "provider_called": False, "effects_started": False}

    host, view, _due_rows, dispatcher = _staging_dispatch_fixture([("A", True)], submit, tmp_path)
    host.dispatcher = dispatcher
    host.dispatch_pump()
    assert len(calls) == 1
    for _ in range(500):
        host.dispatch_pump()
    assert len(calls) == 1

    current = next(iter(dispatcher.records.values())).task
    current.payload["metadata_namespaces"]["work.admission"] = authoring_stamp(
        "revision-A-next", current.payload, "owner")
    # The staged reader returns the same object, so this is a new admitted generation
    # for the next pump; the existing failure fence must stop applying.
    host.dispatch_pump()
    assert len(calls) == 2
    assert calls[0][1] != calls[1][1]

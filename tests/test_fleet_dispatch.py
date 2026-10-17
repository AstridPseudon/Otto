from __future__ import annotations

import pytest
import threading
import time
from types import SimpleNamespace

from herzchen.fleet.capacity import CapacityPool, CapacityPolicy
from herzchen.fleet.dispatch import DispatchError, FleetDispatcher
from herzchen.fleet.hosts.contract import McpGrant, McpServer, TurnSpec
from herzchen.fleet.tools.tokens import TokenBook
from herzchen.domains.work.admission import authoring_stamp
from herzchen.domains.work.readiness import ready as work_ready
from herzchen.contracts import ResourceRef


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

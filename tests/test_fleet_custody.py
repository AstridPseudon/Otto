"""Process-tree custody: the birth-fenced group kill, the fail-closed census and the cleanup latch.

Every test launches real processes and kills every group or pid it launched in a ``finally``.
"""
import json
import hashlib
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from unittest import mock
from types import SimpleNamespace

import pytest

from herzchen.adapters import host as host_module
from herzchen.contracts import HostIdentity, HostOperation, HostOutcome, HostRequest, ResourceRef
from herzchen.fleet import custody
from herzchen.fleet.hosts.codex import CodexStream

DEVNULL = subprocess.DEVNULL


def _has_homebrew_framework_python():
    executable = Path("/opt/homebrew/bin/python3.11")
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec") or not executable.is_file():
        return False
    try:
        resolved = executable.resolve(strict=True)
        target = resolved.parent.parent / "Resources/Python.app/Contents/MacOS/Python"
        return target.is_file() and os.access(target, os.X_OK)
    except (OSError, RuntimeError):
        return False


def test_framework_python_expansion_requires_existing_python_launcher(tmp_path):
    from herzchen.fleet.hosts.claude import sandbox_policy

    version = tmp_path / "Python.framework/Versions/3.11"
    bin_dir = version / "bin"
    target = version / "Resources/Python.app/Contents/MacOS/Python"
    bin_dir.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    python = bin_dir / "python3.11"
    python.write_text("stub")
    python.chmod(0o755)
    target.write_text("app")
    target.chmod(0o755)
    other = bin_dir / "other"
    other.write_text("binary")
    other.chmod(0o755)

    other_policy = sandbox_policy("/w", "/s", exec_allow=(str(other),))
    python_policy = sandbox_policy("/w", "/s", exec_allow=(str(python),))
    target_rule = '(allow process-exec (literal ' + json.dumps(str(target)) + '))'
    python.unlink()
    missing_policy = sandbox_policy("/w", "/s", exec_allow=(str(python),))
    assert target_rule not in missing_policy
    assert target_rule not in other_policy
    assert target_rule in python_policy


@pytest.mark.skipif(not _has_homebrew_framework_python(),
                    reason="needs macOS sandbox-exec and Homebrew Python 3.11")
def test_framework_python_mcp_exec_pin_runs_worker_but_denies_unpinned_executable(tmp_path):
    from herzchen.fleet.hosts.claude import sandbox_policy, sandbox_wrap
    from herzchen.fleet.tools.pins import exec_allow_for, sole_server_grant

    workspace, state = tmp_path / "workspace", tmp_path / "state"
    workspace.mkdir()
    state.mkdir()
    grant = sole_server_grant(server="otto", tools=("task",), command="/opt/homebrew/bin/python3.11",
                              token="token", token_env="OTTO_TOKEN", token_env_prefix="OTTO_")
    allowed = exec_allow_for(grant)
    executable = Path("/opt/homebrew/bin/python3.11").resolve(strict=True)
    version_dir = executable.parent.parent
    expected_app_python = version_dir / "Resources/Python.app/Contents/MacOS/Python"
    assert len(allowed) == 2
    assert allowed[0] == os.path.realpath("/opt/homebrew/bin/python3.11")
    assert allowed[1] == str(expected_app_python.resolve(strict=True))
    policy = sandbox_policy(str(workspace), str(state), exec_allow=(allowed[0],))
    assert '(allow process-exec (literal ' + json.dumps(allowed[0]) + '))' in policy
    assert '(allow process-exec (literal ' + json.dumps(allowed[1]) + '))' in policy
    assert policy.count('(allow process-exec ') == 2
    assert '(allow process-exec (subpath ' not in policy
    worker = "print('worker-ok')"
    result = subprocess.run(sandbox_wrap(policy, str(workspace),
                                         ["/opt/homebrew/bin/python3.11", "-c", worker]),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "worker-ok" in result.stdout

    denied = "\n".join((
        "import subprocess",
        "try:",
        "    subprocess.run(['/usr/bin/true'])",
        "    print('CHILD_ALLOWED')",
        "except PermissionError:",
        "    print('CHILD_DENIED')",
    ))
    denied_result = subprocess.run(
        sandbox_wrap(policy, str(workspace), ["/opt/homebrew/bin/python3.11", "-c", denied]),
        capture_output=True, text=True, timeout=30)
    assert denied_result.returncode == 0, denied_result.stderr
    assert "CHILD_DENIED" in denied_result.stdout


def _reap_tree(leader):
    """Kill the group led by a process this test launched, then reap the leader. Safe to call twice."""
    if leader is None:
        return
    try:
        os.killpg(leader.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        leader.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _kill_pid(pid):
    """Kill one pid this test launched (an escapee outside the group)."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _observe_until(owner, ready, seconds=5.0):
    """Poll the owner's census until ``ready(live)`` holds, bounded. Returns the last live map."""
    deadline = time.monotonic() + seconds
    while True:
        live = owner.observe() or {}
        if ready(live) or time.monotonic() >= deadline:
            return live
        time.sleep(0.05)


def _dead_pids(pids, seconds=2.0):
    """The pids that still answer signal 0 after a bounded wait. ``[]`` means all are gone.

    Callers reap their own leaders first: a zombie still answers signal 0.
    """
    pending = set(pids)
    deadline = time.monotonic() + seconds
    while True:
        for pid in list(pending):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pending.discard(pid)
            except PermissionError:
                pass  # the pid exists under another owner: still alive
        if not pending or time.monotonic() >= deadline:
            return sorted(pending)
        time.sleep(0.05)


def _write_latch(path, pgid, leader_birth, members):
    """Hand-write a latch record in the format the owner persists."""
    record = {"pgid": pgid, "leader_birth": leader_birth, "state": "running",
              "identity_format": custody.IDENTITY_FORMAT,
              "members": {str(pid): birth for pid, birth in members.items()}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    return str(path)


def _fleet_registry_fixture(tmp_path, request, *, plan=None, landing_factory=None,
                            repository_path=None, advance_project=False, checkpoint=None):
    """Real owner records, current task/project pins, and a retained dispatcher grant."""
    import tempfile
    from test_hostctl_cli import HostctlFixture
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.admission import NAMESPACE, authoring_stamp
    from herzchen.fleet.capacity import CapacityPolicy
    from herzchen.fleet.dispatch import FleetDispatcher
    from otto.hostctl import product_service

    old_tempdir = tempfile.tempdir
    tempfile.tempdir = "/private/tmp"
    fixture = HostctlFixture()
    fixture.setUp()
    registries = []

    def cleanup():
        try:
            for registry in registries:
                registry.close()
            fixture.doCleanups()
        finally:
            tempfile.tempdir = old_tempdir

    request.addfinalizer(cleanup)
    fixture._ready()

    def prepare_owner_records():
        view = fixture.owner_service._attach("demo-run", host_kind="claude-code")
        owner = view.owner
        project = owner.graph.current(ResourceRef.from_dict(view.state["project_ref"]))
        task = owner.graph.current(ResourceRef.from_dict(view.state["task_refs"]["T1"]))
        actor = owner.owner_actor
        task = owner.graph.revise(task.ref, fields={"check": {"argv": ["/usr/bin/true"]}},
            base_revision=task.ref.revision, logical_request_key="fleet-test-task-check",
            actor=actor)
        if plan is not None:
            task = owner.graph.revise(task.ref, metadata_namespaces={"otto.plan": dict(plan)},
                base_revision=task.ref.revision, logical_request_key="fleet-test-task-plan",
                actor=actor)
        current_payload = task.payload
        stamp = authoring_stamp(task.ref.revision, current_payload, actor)
        task = owner.graph.revise(task.ref, metadata_namespaces={NAMESPACE: stamp},
            base_revision=task.ref.revision, logical_request_key="fleet-test-task-admission",
            actor=actor)
        if advance_project:
            project = owner.graph.revise(project.ref, title=project.title + " updated",
                base_revision=project.ref.revision, logical_request_key="fleet-test-project-advance",
                actor=actor)
        assignment = owner.assignments.assign(task.ref, role="executor", principal="worker-a",
            manager=view.state["manager"], session="worker-native",
            logical_request_key="fleet-test-worker-assignment", actor=actor)
        return owner, project, task, assignment

    owner, project, task, owner_assignment = fixture.owner_service.call(prepare_owner_records)
    repository = Path(repository_path) if repository_path is not None else tmp_path / "checkout"
    repository.mkdir(exist_ok=True)
    if not (repository / ".git").exists():
        subprocess.run(["git", "-C", str(repository), "init", "-b", "project-line"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "COMPOSEFLEET test"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "composefleet@test.invalid"], check=True)
        (repository / "README.md").write_text("owner registry test\n")
        subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-m", "base"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    policy = CapacityPolicy()
    if landing_factory is None:
        landing_factory = lambda **_kwargs: object()
    socket_home = Path("/private/tmp") / ("fleet-home-" + __import__("hashlib").sha256(
        str(tmp_path).encode()).hexdigest()[:12])
    (socket_home / "run").mkdir(parents=True, exist_ok=True)
    registry = product_service.OwnerFleetRegistry(
        owner, {"store": {"authority": owner.store.authority},
                "repositories": {"repo-a": str(repository)}}, socket_home, object(),
        checkpoint=checkpoint or (lambda *_a, **_kw: None), landing_factory=landing_factory)
    registries.append(registry)
    dispatcher = FleetDispatcher(policy, registry.tokens, ready=lambda *_a, **_kw: True,
        role_for=lambda _task: "worker", policy_for=lambda _role: policy,
        active_counts=lambda: (0, 0), make_spec=None, launch=lambda _task, _context: {"outcome": "prepared"},
        mcp_server_name="otto", mcp_tools=("worker-check", "worker-done"),
        assignment_id=lambda _task: owner_assignment.ref.id,
        read_current=lambda candidate, **_kw: owner.graph.current(candidate.ref))
    record = dispatcher.dispatch(task, assignment=owner_assignment.ref.id)
    registry.bind_dispatcher(dispatcher)
    registry.bind_owner_executor(lambda operation: fixture.owner_service.call(operation))
    if (isinstance(plan, dict) and plan.get("repo") == "repo-a"
            and isinstance(plan.get("branch"), str)
            and subprocess.run(["git", "-C", str(repository), "show-ref", "--verify", "--quiet",
                                "refs/heads/" + plan["branch"]]).returncode == 0):
        registry.prepare_worker_lab(project.ref, task.ref)
    return registry, project, task, owner_assignment, record, record.token, repository


def test_owner_registry_binds_lab_and_line_to_dispatch_record_and_reuses_repo_branch_pair(tmp_path, request):
    registry, project, task, assignment, record, token, repository = _fleet_registry_fixture(
        tmp_path, request, plan={"route": "normal", "size": 1, "lines": 99,
                                     "repo": "repo-a", "branch": "project-line"},
        landing_factory=lambda **_kwargs: object())

    first = registry.assignment_context(record.assignment, token=token)
    # Worker request fields cannot select another task, checkout, or branch.
    second = registry.assignment_context(record.assignment, token=token)

    assert first["task"].ref.to_dict() == task.ref.to_dict()
    assert first["task_id"] == task.ref.id
    assert first["assignment_ref"] == assignment.ref.to_dict()
    assert first["admitted_revision"] == record.admitted_revision
    assert first["repo_path"] == str(repository)
    assert first["branch"] == "project-line"
    assert first["line_ref"] == "refs/heads/project-line"
    assert first["lab_name"] == task.ref.id
    assert first["fleet"] is second["fleet"]
    assert first["landing"] is second["landing"]


def test_owner_registry_refuses_unchecked_out_configured_line_before_lab_creation(request, tmp_path):
    from herzchen.contracts import ResourceRef
    from herzchen.fleet.landing import LandingError

    registry, project, task, _assignment, _record, _token, repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "configured-line"})
    subprocess.run(["git", "-C", str(repository), "branch", "configured-line"], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with pytest.raises(LandingError, match="not on the configured line branch"):
        registry.prepare_worker_lab(project.ref, task.ref)

    assert registry._pairs == {}, "line preflight must run before fleet or lab construction"


def test_owner_registry_refuses_dirty_line_when_reusing_existing_lab(request, tmp_path):
    from herzchen.contracts import ResourceRef
    from herzchen.fleet.landing import LandingError

    registry, project, task, _assignment, _record, _token, repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "project-line"})
    first = registry.prepare_worker_lab(project.ref, task.ref)
    (repository / "README.md").write_text("dirty line\n")

    with pytest.raises(LandingError, match="clean and at its branch tip"):
        registry.prepare_worker_lab(project.ref, task.ref)

    assert first["fleet"].get(task.id) == first["lab"], "refusal must retain the existing lab"


def test_owner_registry_prepares_lab_on_clean_configured_line(request, tmp_path):
    registry, project, task, _assignment, _record, _token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "project-line"})

    first = registry.prepare_worker_lab(project.ref, task.ref)
    second = registry.prepare_worker_lab(project.ref, task.ref)

    assert second["lab"] == first["lab"]
    assert second["fleet"] is first["fleet"]


def test_owner_registry_allows_project_revision_advance_only_while_task_is_still_linked(tmp_path, request):
    registry, project, task, _assignment, record, _token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "project-line"},
        advance_project=True)

    # The task retains its project identity while the real owner advances the
    # project revision; the current project still owns the task's lab.
    assert task.payload["project_ref"]["revision"] != project.ref.revision
    assert registry.prepare_worker_lab(project.ref, task.ref)["lab_name"] == task.ref.id
    assert registry.assignment_lookup(record.assignment)["project_ref"] == project.ref.to_dict()

    project = registry.owner.graph.create_project(
        title="Unlinked fleet project", logical_request_key="fleet-test-unlinked-project",
        actor=registry.owner.owner_actor)
    unlinked_task = registry.owner.graph.create_task(
        project.ref, title="Unlinked fleet task", logical_request_key="fleet-test-unlinked-task",
        actor=registry.owner.owner_actor)
    with pytest.raises(PermissionError, match="not linked"):
        registry.prepare_worker_lab(project.ref, unlinked_task.ref)


def test_owner_registry_refuses_token_from_another_assignment(tmp_path, request):
    registry, _project, _task, _assignment, record, _token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "project-line"})
    foreign = registry.dispatcher.tokens.issue("another-assignment", "worker")

    with pytest.raises(PermissionError, match="does not belong"):
        registry.assignment_context(record.assignment, token=foreign)


def test_worker_facade_check_is_feedback_and_done_lands_only_its_bound_lab_and_line(request, tmp_path):
    from herzchen.fleet.tools.server import request as facade_request
    from test_landing import _Runner, _run, _service
    from herzchen.fleet.runner.commit import git_commit_identity
    from herzchen.fleet.runner.store import ResultStore

    line = tmp_path / "project"
    line.mkdir()
    _run(line, "init", "-b", "main")
    _run(line, "config", "user.name", "LAND test")
    _run(line, "config", "user.email", "land@test.invalid")
    (line / "shared.txt").write_text("base\n")
    _run(line, "add", "shared.txt")
    _run(line, "commit", "-m", "base")
    base = _run(line, "rev-parse", "HEAD")

    def checkpoint(worktree, paths, *, message):
        _run(Path(worktree), "add", "--", *paths)
        _run(Path(worktree), "-c", "user.name=LAND test", "-c", "user.email=land@test.invalid",
             "commit", "-m", message)

    class DirtyAwareRunner(_Runner):
        def call(self, request):
            reply = super().call(request)
            if request["op"] == "submit" and reply.get("ok"):
                record = self.records[reply["run_id"]]
                commit = git_commit_identity(request["cwd"])
                record["commit"] = commit
                record["binding"] = ResultStore.binding(record["argv"], record["cwd"], commit)
            return reply

    class BoundLanding:
        landing = None

        def check(self, lab_name, task_id):
            return self.landing.check(lab_name, task_id)

        def done(self, lab_name, task_id, **pins):
            from test_landing import _criterion
            return self.landing.done(lab_name, task_id, candidate="candidate@1", criterion=_criterion(),
                                parent_obligation="obligation@1", actor="owner", **pins)

    bound_landing = BoundLanding()
    registry, project, task, assignment, record, token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "main"},
        landing_factory=lambda **_kwargs: bound_landing, repository_path=line, checkpoint=checkpoint)
    fleet = registry._pairs[("repo-a", "main")][0]
    lab = fleet.get(task.ref.id)
    (lab.path / "one.txt").write_text("worker change\n")
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.admission import NAMESPACE, authoring_stamp
    second_task = next(registry.owner.graph.current(ResourceRef.from_dict(raw))
        for raw in project.payload["tasks"]
        if registry.owner.graph.current(ResourceRef.from_dict(raw)).payload.get("alias") == "T2")
    second_task = registry.owner.graph.revise(second_task.ref,
        fields={"check": {"argv": ["/usr/bin/true"]}}, base_revision=second_task.ref.revision,
        logical_request_key="fleet-test-second-task-check", actor=registry.owner.owner_actor)
    second_task = registry.owner.graph.revise(second_task.ref,
        metadata_namespaces={"otto.plan": {"repo": "repo-a", "branch": "main"}},
        base_revision=second_task.ref.revision, logical_request_key="fleet-test-second-task-plan",
        actor=registry.owner.owner_actor)
    second_task = registry.owner.graph.revise(second_task.ref,
        metadata_namespaces={NAMESPACE: authoring_stamp(
            second_task.ref.revision, second_task.payload, registry.owner.owner_actor)},
        base_revision=second_task.ref.revision, logical_request_key="fleet-test-second-task-admission",
        actor=registry.owner.owner_actor)
    second_context = registry.prepare_worker_lab(project.ref, second_task.ref)
    second_lab = second_context["lab"]
    (second_lab.path / "two.txt").write_text("other task output\n")
    runner = DirtyAwareRunner()
    task_projection = {"id": task.ref.id, "revision": task.ref.revision,
                       "current_revision": task.ref.revision, "payload": task.payload}
    bound_landing.landing, _landing_calls = _service(fleet, runner, task=task_projection)
    socket_path = str(registry.facade_socket)
    context = facade_request(socket_path, {"op": "call", "token": token, "tool": "task", "args": {}})
    assert context.get("ok") is True and context.get("result", {}).get("task_id") == task.ref.id, context
    checked = facade_request(socket_path, {"op": "call", "token": token, "tool": "check", "args": {}})
    assert checked.get("feedback") is True and checked.get("accepted") is False, checked
    assert _run(line, "rev-parse", "refs/heads/main") == base, "check advanced the project's line"
    landed = facade_request(socket_path, {"op": "call", "token": token, "tool": "done",
                                           "args": {"summary": "verified task output"}})

    assert landed.get("submitted") is True and landed.get("accepted") is False, landed
    assert landed["result"]["landed"] is True
    assert landed["result"]["task"] == task.ref.id
    assert _run(line, "rev-parse", "refs/heads/main") != base
    # The native stream has not emitted its final ``done`` event yet.  Keep the
    # owner lab available until the adapter captures the delivered Write bytes.
    assert lab.path.is_dir(), "worker-done removed the lab before stream artifact capture"
    assert (line / "one.txt").exists(), "the bound task lab did not land on its project line"
    assert not (line / "two.txt").exists(), "another task lab landed on the bound task's line"


def test_landed_done_revokes_before_facade_waiter_resumes(request, tmp_path):
    import threading
    from otto.portfolio.execution_host import ExecutionHost

    calls = []
    landing_started = threading.Event()
    release_landing = threading.Event()

    class Landing:
        def done(self, lab_name, task_id, **_pins):
            calls.append(("done", lab_name, task_id))
            landing_started.set()
            release_landing.wait()
            return {"landed": True}

        def check(self, lab_name, task_id):
            calls.append(("check", lab_name, task_id))
            return {"feedback_only": True}

    landing = Landing()
    registry, _project, task, _assignment, record, token, _repo = _fleet_registry_fixture(
        tmp_path, request,
        plan={"repo": "repo-a", "branch": "project-line"},
        landing_factory=lambda **_kwargs: landing,
    )
    host = ExecutionHost(
        directory=tmp_path / "owner-pump",
        handler=lambda _request: {},
        owner_file_compatibility=True,
        bounded_transports=True,
    )
    owner_returned = threading.Event()
    release_facade = threading.Event()
    replies = []
    queued_replies = []
    done_thread = None

    def execute(operation):
        def run_owned():
            with host._command_lock:
                return host._owned(operation)

        result = host._owner_request(run_owned)
        if threading.current_thread() is done_thread:
            owner_returned.set()
            release_facade.wait()
        return result

    registry.bind_owner_executor(execute)
    host.start()
    done_thread = threading.Thread(
        target=lambda: replies.append(registry.facade.call(token, "done"))
    )
    check_thread = threading.Thread(
        target=lambda: queued_replies.append(registry.facade.call(token, "check"))
    )
    try:
        done_thread.start()
        assert landing_started.wait(5)
        check_thread.start()
        deadline = time.monotonic() + 5
        while host._owner_calls.qsize() == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert host._owner_calls.qsize() == 1  # Check captured its grant and entered the owner queue.
        release_landing.set()
        assert owner_returned.wait(5)  # Owner finished done; its facade thread is held.
        check_thread.join(5)
        assert not check_thread.is_alive()
        assert queued_replies == [{
            "ok": False, "error": "owner_unavailable",
            "detail": "LookupError: assignment has no active dispatch record",
        }]
        refused = registry.facade.call(token, "check")
        assert refused == {
            "ok": False, "error": "unauthorized", "detail": "unknown token"
        }
        assert calls == [("done", task.ref.id, task.ref.id)]
        assert record.state == "settled"
        assert registry.tokens.live() == frozenset()
    finally:
        release_landing.set()
        release_facade.set()
        done_thread.join()
        if check_thread.ident is not None:
            check_thread.join()
        host.close()
        registry.close()

    assert replies[0]["submitted"] is True


def test_worker_facade_refuses_foreign_assignment_token(request, tmp_path):
    from herzchen.fleet.tools.server import request as facade_request
    from test_landing import _Runner, _admitted_task, _project, _run, _service

    project_root = tmp_path / "project"
    project_root.mkdir()
    line, base, fleet = _project(project_root)
    lab = fleet.labs.pop("one")
    fleet.labs["T1"] = lab
    landing, _landing_calls = _service(fleet, _Runner(), task=_admitted_task())

    registry, _project, task, assignment, record, _token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan={"repo": "repo-a", "branch": "main"},
        landing_factory=lambda **_kwargs: landing, repository_path=line)
    fleet.labs[task.ref.id] = lab
    foreign = registry.dispatcher.tokens.issue("another-assignment", "worker")
    refused = facade_request(str(registry.facade_socket),
        {"op": "call", "token": foreign, "tool": "check", "args": {}})

    assert refused["ok"] is False
    assert refused["error"] == "owner_unavailable"
    assert refused["detail"] == "LookupError: assignment has no active dispatch record"
    assert record.assignment == assignment.ref.id
    assert _run(line, "rev-parse", "refs/heads/main") == base, "foreign token advanced the project's line"


def test_owner_start_retries_only_captured_landed_lab_after_remove_failure(monkeypatch, tmp_path):
    from herzchen.fleet.labs import LabFleet
    from otto.hostctl.product_service import OwnerFleetRegistry
    from test_landing import _project, _run

    project_root = tmp_path / "landed-start"
    project_root.mkdir()
    line, _base, _fake_fleet = _project(project_root)

    def checkpoint(worktree, paths, *, message):
        _run(Path(worktree), "add", "--", *paths)
        _run(Path(worktree), "-c", "user.name=LAND test", "-c", "user.email=land@test.invalid",
             "commit", "-m", message)

    branch_hash = hashlib.sha256(b"main").hexdigest()[:20]
    labs_root = line.parent / (line.name + ".otto-labs") / branch_hash
    fleet = LabFleet(line, labs_root, checkpoint=checkpoint, shared_dirs=())
    task_lab = fleet.create("task-lab", base="refs/heads/main")
    output = task_lab.path / "task-lab.txt"
    output.write_text("task-lab output\n")
    fleet.checkpoint(str(task_lab.path), [output.name], message="worker output")
    task_commit = task_lab.head()
    _run(line, "fetch", str(task_lab.path), "HEAD")
    _run(line, "merge", "--ff-only", "FETCH_HEAD")
    fleet.mark_landed("task-lab", task_commit, "refs/heads/main")
    fleet.create("unsettled-lab", base="refs/heads/main")

    task_ref = {"authority": "fixture", "kind": "work.task", "id": "task-lab", "revision": "task-r1"}
    assignment_ref = {"authority": "fixture", "kind": "wrk.assignment", "id": "assignment-r1", "revision": "assign-r1"}
    result_digest = "captured-result-digest"
    bound = {"task_ref": task_ref, "assignment_ref": assignment_ref, "generation": 1,
             "result_digest": result_digest,
             "operation_result": {"result_ref": "result-r1", "output": {"artifacts": [{"name": "task.txt"}]}}}
    request_key = "worker-request-r1"
    result = {"outcome": "succeeded", "logical_request_key": request_key,
              "task_bound_evidence": bound}
    acceptance_digest = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    accepted_due = {
        "role": "worker", "schedule_id": "schedule-r1", "lifecycle_owner": "owner-r1",
        "assignment_ref": assignment_ref, "generation": 1, "target": {"task_ref": task_ref},
        "host_evidence": {
            "gateway_attempt": {"state": "result", "logical_request_key": request_key, "result": result,
                "manager_acceptance": {"accepted": False, "owner": "owner-r1",
                    "logical_request_key": request_key, "result_digest": acceptance_digest}},
            "captured_artifacts": [{"ref": "artifact-r1"}],
            "captured_result_summary": {"result_ref": "result-r1", "result_digest": result_digest,
                "logical_request_key": request_key, "assignment_ref": assignment_ref, "generation": 1,
                "verification": {"context_digest_verified": True}},
        },
    }

    class DuePort:
        def list_due(self):
            return [accepted_due]

    task = SimpleNamespace(payload={"metadata_namespaces": {"otto.plan": {"repo": "repo-a", "branch": "main"}}})
    owner = SimpleNamespace(graph=SimpleNamespace(reader=SimpleNamespace(
        get_identity=lambda _ref: task)))
    monkeypatch.setattr(OwnerFleetRegistry, "_start_facade", lambda _self: None)
    original_remove = LabFleet.remove
    fail_once = {"pending": True}

    def transient_remove(self, name, *args, **kwargs):
        if name == "task-lab" and fail_once["pending"]:
            fail_once["pending"] = False
            raise OSError("transient unlink failure")
        return original_remove(self, name, *args, **kwargs)

    monkeypatch.setattr(LabFleet, "remove", transient_remove)
    registry = OwnerFleetRegistry(owner, {"repositories": {"repo-a": str(line)}}, tmp_path / "owner-home",
        object(), checkpoint=checkpoint, due_port=DuePort(), landing_factory=lambda **_kwargs: object())

    assert registry.startup_landed_sweep is None, "registry construction swept before owner custody"
    mismatched = json.loads(json.dumps(accepted_due))
    mismatched["host_evidence"]["captured_result_summary"]["logical_request_key"] = "different-request"
    assert registry._captured_worker_due(accepted_due) is True
    assert registry._captured_worker_due(mismatched) is False, "mismatched capture key authorized lab cleanup"
    registry.startup_landed_sweep = registry.sweep_landed_at_start()
    assert any(getattr(item, "action", None) == "kept-error" for item in registry.startup_landed_sweep), registry.startup_landed_sweep
    assert (labs_root / "task-lab").is_dir(), "failed cleanup discarded the captured landed lab"
    assert (labs_root / "unsettled-lab").is_dir(), "startup sweep removed a lab without a captured Due"

    restarted_registry = OwnerFleetRegistry(owner, {"repositories": {"repo-a": str(line)}},
        tmp_path / "owner-home-restarted", object(), checkpoint=checkpoint, due_port=DuePort(),
        landing_factory=lambda **_kwargs: object())
    assert restarted_registry.startup_landed_sweep is None
    retried = restarted_registry.sweep_landed_at_start()

    assert any(getattr(item, "action", None) == "removed" for item in retried)
    assert not (labs_root / "task-lab").exists(), "owner-start retry left a removable landed lab"
    assert (labs_root / "unsettled-lab").is_dir()


def test_landed_lab_start_sweep_runs_after_owner_file_custody(tmp_path, monkeypatch):
    from otto.hostctl.product_service import OwnerFleetRegistry, _start_owner_host

    monkeypatch.setattr(OwnerFleetRegistry, "_start_facade", lambda _self: None)
    owner_file = tmp_path / "owner.json"
    owner = SimpleNamespace(graph=SimpleNamespace(reader=SimpleNamespace()), host=None,
                            fleet_registry=None)
    registry = OwnerFleetRegistry(owner, {}, tmp_path / "home", object(), checkpoint=lambda *_a, **_k: None)
    assert registry.startup_landed_sweep is None
    observed = []

    class Host:
        _owns_owner_file = False

        def start(self):
            assert not observed
            owner_file.write_text("owned")
            self._owns_owner_file = True

    owner.host = Host()
    owner.fleet_registry = registry
    registry.sweep_landed_at_start = lambda: observed.append(
        (owner.host._owns_owner_file, owner_file.exists())) or []

    _start_owner_host(owner)

    assert observed == [(True, True)]
    assert registry.startup_landed_sweep == []


def test_landing_owner_port_forwards_only_owner_assignment_identity():
    from herzchen.fleet.tools.facade import LandingOwnerPort, ToolFacade
    from herzchen.fleet.tools.rules import DONE, FeedbackLedger, ToolSpec
    from herzchen.fleet.tools.tokens import TokenBook

    seen = []
    class Landing:
        def done(self, lab_name, task_id, **pins):
            seen.append((lab_name, task_id, pins))
            return {"ok": True, "landed": False}

    book = TokenBook()
    token = book.issue("assignment-1", "worker")
    port = LandingOwnerPort(lambda _assignment: {
        "service": Landing(), "lab_name": "task-lab", "task_id": "task-1",
        "assignment_id": "assignment-1"})
    facade = ToolFacade((ToolSpec("done", DONE, "worker-done", ("task_id",)),),
                        {"worker": ("done",)}, port, book, FeedbackLedger())

    facade.call(token, "done", {"task_id": "other"})

    assert seen == [("task-lab", "task-1", {"assignment_id": "assignment-1"})]


def test_fleet_assessment_inputs_bind_verified_commit_and_owner_dispatch_policy(tmp_path):
    from herzchen.contracts import AuthenticatedActor, ResourceRef
    from herzchen.fleet.runner.store import ResultStore
    from otto.hostctl.fleet_landing import make_landing_service
    from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
    import hashlib

    project = ResourceRef("owner", "work.project", "project-1", "project-r1")
    task = ResourceRef("owner", "work.task", "task-1", "task-r1")
    assignment = ResourceRef("owner", "wrk.assignment", "dispatch-1", "assignment-r1")
    manager = ResourceRef("owner", "wrk.assignment", "manager-1", "manager-r1")
    criterion = ResourceRef("owner", "assessment.criterion", "criterion-1", "criterion-r1")
    scope_ref = ResourceRef("owner", "assessment.scope", "scope-1", "scope-r1")
    packet_ref = ResourceRef("owner", "assessment.input", "packet-1", "packet-r1")
    candidate_ref = ResourceRef("owner", "wrk.result", "candidate-1", "candidate-r1")
    actor = AuthenticatedActor("owner", "manager", "manager")
    policy_config = {"kind": "owner_local_bookkeeping", "purpose": "fleet check assessment",
        "local_only": True, "pool_id": "fleet-pool", "capacity_units": 1,
        "cumulative_allowance_units": 1, "task_criterion_pairs": ["T/C"],
        "scope_mode": "check-accepted"}
    state = {"authority": "owner", "project_ref": project.to_dict(),
        "task_refs": {"T": task.to_dict()}, "criterion_refs": {"C": criterion.to_dict()},
        "assessment_policy": policy_config, "assignment_ref": manager.to_dict(),
        "manager": "manager", "manager_generation": 1}
    policy = LocalAssessmentPolicy.from_run_config(policy_config, state=state)

    class Reader:
        authority = "owner"
        def __init__(self):
            self.current = {}
            self.revisions = {}

        def get_identity(self, ref):
            return self.current.get((ref.kind, ref.id))

        def get_revision(self, ref):
            return self.revisions.get(ref)

        def put(self, ref, payload):
            record = SimpleNamespace(ref=ref, payload=payload)
            self.current[(ref.kind, ref.id)] = record
            self.revisions[ref] = record

    reader = Reader()
    reader.put(project, {"kind": "project", "id": project.id, "title": "Project"})
    reader.put(criterion, {"kind": "criterion", "id": criterion.id})

    scope = SimpleNamespace(ref=scope_ref, criterion_refs=(criterion,), protocol="check-accepted",
        review_required=False, allow_no_review=True,
        policy={"required_for_completion": True, "acceptance_mode": "check-accepted"})
    packet_requests = []
    class Commands:
        # Activation has already retained this run-policy scope before the
        # worker is dispatched. Landing may add an input packet, never a scope.
        declared = True
        def required_scope(self, *, require):
            assert require in {True, False}
            return scope if self.declared else None
        def execute(self, request):
            packet_requests.append(request)
            if request["operation"] == "declare-scope":
                self.declared = True
                return {"ref": scope_ref.to_dict()}
            return {"ref": packet_ref.to_dict()}
    commands = Commands()
    candidate_rows = []
    class Assignments:
        def append_result(self, target, value, **kwargs):
            candidate_rows.append((target, value, kwargs))
            return SimpleNamespace(ref=candidate_ref, value=value)

    evidence_ref = ResourceRef("owner", "dat.content.document", "runner-evidence", "evidence-r1")
    evidence_capture = {}
    class EvidenceResolver:
        def submit(self, source, **_kwargs):
            evidence_capture["bytes"] = source
            return {"revision_ref": evidence_ref.to_dict()}
        def resolve(self, _ref, **_kwargs):
            digest = hashlib.sha256(evidence_capture["bytes"]).hexdigest()
            return {"representation": "managed", "availability": "verified",
                "verification": "full-verified", "actual_digest": digest,
                "manifest": {"byte_digest": digest, "byte_length": len(evidence_capture["bytes"])}}

    owner = SimpleNamespace(
        graph=SimpleNamespace(reader=reader), owner_actor=AuthenticatedActor("owner", "host", "host"),
        assignments=Assignments(), binding=SimpleNamespace(authenticated_actor=lambda _name: actor),
        evidence_payload_resolver=EvidenceResolver(),
        manager_assessment=lambda **kwargs: commands,
        create_manager_assessment_pool=lambda **_kwargs: None)
    dispatch = SimpleNamespace(assignment="dispatch-1", role="worker", admitted_revision="task-r1")
    policy_changed = [False]
    def assert_policy_current():
        if policy_changed[0]:
            raise ValueError("run document assessment policy changed")
    binding = {"record": dispatch, "task": SimpleNamespace(ref=task), "task_ref": task.to_dict(),
        "project_ref": project.to_dict(), "assignment_ref": assignment.to_dict(),
        "generation": 3, "project_state": state,
        "view": SimpleNamespace(server=SimpleNamespace(
            owner=owner, assert_assessment_policy_current=assert_policy_current))}
    result_store = ResultStore(tmp_path / "results")
    service = make_landing_service(fleet=SimpleNamespace(_lab=lambda _name: None), result_store=result_store,
        repo_name="repo", repo_path=tmp_path, branch="main", owner=owner, runner=SimpleNamespace(call=lambda _r: {}),
        views_provider=lambda: {}, assignment_lookup=lambda assignment_id: binding if assignment_id == "dispatch-1" else {})
    runner_record = {"run_id": "run-1", "commit": "a" * 40,
        "argv": ["pytest", "-q"], "cwd": "/repo/lab", "exit_code": 0,
        "state": "settled", "outcome": "exited", "seq": 1}
    runner_record["binding"] = ResultStore.binding(runner_record["argv"], runner_record["cwd"], runner_record["commit"])
    result_store.put(runner_record)
    runner_record = result_store.get("run-1")
    runner_identity = {key: runner_record[key] for key in
        ("run_id", "commit", "binding", "argv", "cwd", "exit_code")}
    from herzchen.domains.work.admission import authoring_stamp
    payload = {"kind": "task", "id": task.id, "title": "Task", "project_ref": project.to_dict(),
        "fields": {"check": {"argv": ["pytest", "-q"]}}, "dependencies": [],
        "metadata_namespaces": {}}
    payload["metadata_namespaces"]["work.admission"] = authoring_stamp("task-r1", payload, "reviewer")
    reader.put(task, payload)
    admitted_task = {"id": task.id, "payload": payload}

    policy_changed[0] = True
    from herzchen.fleet.landing import LandingError
    with pytest.raises(LandingError, match="assessment policy is no longer current"):
        service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")
    assert candidate_rows == [], "stale assessment policy must fail before recording a candidate"
    policy_changed[0] = False

    context = service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1",
        candidate="worker-forged-candidate", criterion="worker-forged-criterion",
        parent_obligation="worker-forged-parent", actor="worker-forged-actor")

    assert [request["operation"] for request in packet_requests] == ["freeze-input"]

    assert candidate_rows[0][0] == assignment
    assert candidate_rows[0][1] == {
        "task_ref": task.to_dict(), "admitted_revision": "task-r1",
        "assignment_ref": assignment.to_dict(), "assignment_id": "dispatch-1",
        "lab_commit": "a" * 40, "repo_name": "repo", "line_ref": "refs/heads/main",
        "lab_name": task.id, "runner": runner_identity}
    packet_args = packet_requests[0]["arguments"]
    assert packet_args["candidate_ref"] == candidate_ref.to_dict()
    assert packet_args["criterion_refs"] == [criterion.to_dict()]
    assert packet_args["packet"]["admitted_revision"] == "task-r1"
    assert packet_args["packet"]["lab_commit"] == "a" * 40
    assert packet_args["evidence_refs"] == [evidence_ref.to_dict()]
    assert json.loads(evidence_capture["bytes"])["run_id"] == runner_record["run_id"]
    assert context["candidate"] == candidate_ref and context["criterion"] == criterion
    assert context["parent_obligation"] == task and context["actor"] == actor

    # Activation retained r1. Admission and owner metadata writes advanced
    # the project and task before the dispatched worker called done.
    current_project = ResourceRef("owner", "work.project", project.id, "project-r2")
    current_task = ResourceRef("owner", "work.task", task.id, "task-r2")
    reader.put(current_project, {**reader.get_revision(project).payload,
                                 "lifecycle": "active"})
    reader.put(current_task, {**payload, "lifecycle": "admitted"})
    binding["project_ref"] = current_project.to_dict()
    binding["task_ref"] = current_task.to_dict()
    binding["task"] = SimpleNamespace(ref=current_task)
    admitted_task = {"id": task.id, "payload": reader.get_identity(current_task).payload}
    context = service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")
    assert context["parent_obligation"] == current_task
    assert context["criterion"] == criterion
    assert candidate_rows[-1][1]["task_ref"] == current_task.to_dict()

    before = len(candidate_rows)
    edited_project = ResourceRef("owner", "work.project", project.id, "project-r3")
    reader.put(edited_project, {"kind": "project", "id": project.id,
                                "title": "Changed project"})
    binding["project_ref"] = edited_project.to_dict()
    with pytest.raises(LandingError, match="project content is stale"):
        service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")
    assert len(candidate_rows) == before
    reader.current[(project.kind, project.id)] = reader.get_revision(current_project)
    binding["project_ref"] = current_project.to_dict()

    # A later authored edit changes the retained task content, so the same
    # dispatch can no longer create an assessment candidate.
    before = len(candidate_rows)
    edited_task = ResourceRef("owner", "work.task", task.id, "task-r3")
    reader.put(edited_task, {**payload, "title": "Edited task"})
    binding["task_ref"] = edited_task.to_dict()
    binding["task"] = SimpleNamespace(ref=edited_task)
    with pytest.raises(LandingError, match="task content is stale"):
        service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")
    assert len(candidate_rows) == before

    # An existing review-required scope stays separate from fleet check
    # acceptance, even when the controller policy permits check-accepted.
    reader.current[(task.kind, task.id)] = reader.get_revision(current_task)
    binding["task_ref"] = current_task.to_dict()
    binding["task"] = SimpleNamespace(ref=current_task)

    revised_criterion = ResourceRef("owner", "assessment.criterion", criterion.id, "criterion-r2")
    reader.put(revised_criterion, {"kind": "criterion", "id": criterion.id})
    with pytest.raises(LandingError, match="criterion is stale"):
        service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")
    assert len(candidate_rows) == before
    reader.current[(criterion.kind, criterion.id)] = reader.get_revision(criterion)
    scope.review_required = True
    with pytest.raises(LandingError, match="separate review"):
        service.assessment_context(runner_record, admitted_task, assignment_id="dispatch-1")


def test_fleet_accept_rejects_result_with_non_fleet_role():
    from herzchen.contracts import ResourceRef
    from herzchen.fleet.landing import LandingError
    from otto.hostctl.fleet_landing import _FleetAssessmentCommands

    candidate = ResourceRef("owner", "wrk.result", "candidate", "candidate-r1")
    criterion = ResourceRef("owner", "assessment.criterion", "criterion", "criterion-r1")
    evidence = ResourceRef("owner", "dat.content.document", "evidence", "evidence-r1")
    commands = SimpleNamespace()
    adapter = _FleetAssessmentCommands(commands, candidate, (criterion,),
        ResourceRef("owner", "assessment.input", "packet", "packet-r1"),
        ResourceRef("owner", "limit", "pool"), "manager", "request", evidence_refs=(evidence,))
    result = SimpleNamespace(payload={"role": "review"})
    commands._assessment = SimpleNamespace(get_result=lambda _ref: result)

    with pytest.raises(LandingError, match="retained fleet-check result"):
        adapter.accept(result, candidate=candidate, criterion=criterion,
            rationale="fleet check passed", actor=SimpleNamespace(actor="manager"))


def test_fleet_accept_through_owner_assessment_without_review_evidence(tmp_path):
    """Exercise the fleet adapter with a retained managed runner evidence revision."""
    import hashlib
    import json
    from pathlib import Path
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule
    from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
    from herzchen.evidence.model import load_evidence_pack
    from otto.hostctl.fleet_landing import _FleetAssessmentCommands
    from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy, compose_manager_assessment_state
    from otto.portfolio.manager_assessment_command import manager_assessment_pool_from_command

    fixture = None
    try:
        # Reuse the owner/store composition that creates a disposable project,
        # exact manager assignment, tasks and criteria without mocking assessment.
        from tests.test_local_assessment_composition import LocalAssessmentCompositionTests
        fixture = LocalAssessmentCompositionTests()
        fixture.setUp()
        f = fixture.f
        register_evidence(f.store)
        from tests import test_evidence_lifecycle as lifecycle
        root, discover, loader = lifecycle._public_pack_hooks()
        found = discover(project_root=root)[0]
        found.entry.definition.version = "1.1.0"
        found.entry.definition.to_dict = lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2}
        found.entry.resource_handles += tuple(SimpleNamespace(path=path, kind="evidence_preset",
            resolved=root / path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in ("presets/list.json", "presets/read.json"))
        pack = load_evidence_pack(project_root=root, discoverer=lambda **kwargs: (found,), loader=loader)
        evidence_handler = EvidenceCommandHandler(f.store, Path(tmp_path) / "managed-evidence", pack=pack,
            adopted_pins=[item.to_dict() for item in pack.resources])
        f.owner.evidence_payload_resolver = evidence_handler
        criterion = ResourceRef.from_dict(fixture.state["criterion_refs"]["C09"])
        task = ResourceRef.from_dict(fixture.state["task_refs"]["PA06"])

        check_config = {**fixture.config, "scope_mode": "check-accepted"}
        fixture.config_path.write_text(json.dumps({"assessment_accounting": check_config}))
        fixture.state = compose_manager_assessment_state(fixture.state, config_path=fixture.config_path)
        policy = LocalAssessmentPolicy.from_run_config(check_config, state=fixture.state)
        manager_assessment_pool_from_command(f.owner, state=fixture.state,
            request=fixture.request("PA06", key="fleet-adapter-pool"))

        candidate_row = f.owner.assignments.command_port.append_result(
            fixture.manager.ref, {"task_ref": task.to_dict(), "candidate": "verified-lab"},
            expected_generation=fixture.manager.generation, logical_request_key="fleet-adapter-candidate",
            actor=f.actor)
        candidate = candidate_row.ref
        scope_ref = fixture.call("PA06", "declare-scope", {"scope_ref": ResourceRef(
            f.actor.authority, "assessment.scope", "fleet-adapter-check").to_dict(),
            "criterion_refs": [criterion.to_dict()], "protocol": "check-accepted"}, "fleet-adapter-scope")["ref"]
        scope = AssessmentModule(f.store, actor=f.actor).get_scope(ResourceRef.from_dict(scope_ref))
        from herzchen.domains.work import WorkGraph
        advanced = WorkGraph(f.store, actor=f.actor).revise(
            task, lifecycle="active", logical_request_key="fleet-adapter-task-metadata", actor=f.actor)
        assert advanced.ref != scope.parent_obligation_ref
        fixture.state["task_refs"]["PA06"] = advanced.ref.to_dict()
        policy = LocalAssessmentPolicy.from_run_config(check_config, state=fixture.state)
        task = advanced.ref
        runner_record = {"run_id": "fleet-run-1", "commit": "a" * 40,
            "binding": "b" * 64, "argv": ["pytest", "-q"], "cwd": "/repo/lab",
            "exit_code": 0, "state": "settled", "outcome": "exited"}
        runner_bytes = json.dumps(runner_record, sort_keys=True, separators=(",", ":")).encode()
        submitted = evidence_handler.submit(runner_bytes, actor=f.actor,
            logical_request_key="fleet-runner-evidence", project_ref=f.project.ref,
            task_ref=task, original_creator="manager", format="application/json",
            provenance={"runner": runner_record})
        evidence_ref = submitted["revision_ref"]
        evidence_ref = evidence_ref.to_dict() if hasattr(evidence_ref, "to_dict") else evidence_ref
        packet_ref = fixture.call("PA06", "freeze-input", {"scope_ref": scope_ref,
            "candidate_ref": candidate.to_dict(), "criterion_refs": [criterion.to_dict()],
            "source_refs": [candidate.to_dict()], "evidence_refs": [evidence_ref],
            "packet": {"candidate": "verified-lab"}}, "fleet-adapter-input")["ref"]

        commands = f.owner.manager_assessment(project_ref=fixture.state["project_ref"],
            task_ref=fixture.state["task_refs"]["PA06"],
            manager_assignment_ref=fixture.state["assignment_ref"], manager_actor="manager",
            manager_generation=1, assessment_policy=policy)
        actor = f.owner.binding.authenticated_actor("manager")
        adapter = _FleetAssessmentCommands(commands, candidate, (criterion,),
            ResourceRef.from_dict(packet_ref), policy.pool_ref, "manager", "fleet-adapter",
            evidence_refs=(ResourceRef.from_dict(evidence_ref),))
        result = adapter.assess(scope.ref, candidate=candidate, criterion=criterion,
            input_packet=ResourceRef.from_dict(packet_ref), verdict="PASS",
            protocol_result={"passed": True}, limit_pool=policy.pool_ref, actor=actor)
        accepted = adapter.accept(result, candidate=candidate, criterion=criterion,
            rationale="retained fleet check passed", actor=actor)
        assert accepted.payload["candidate_ref"] == candidate.to_dict()
        assert accepted.payload["criterion_ref"] == criterion.to_dict()
        assert accepted.payload["result_ref"] == result.ref.to_dict()
        assert tuple(ResourceRef.from_dict(value) if isinstance(value, dict) else value
                     for value in accepted.payload["evidence_refs"]) == (ResourceRef.from_dict(evidence_ref),)
        assert not accepted.payload["review_evidence"]
        frozen = AssessmentModule(f.store, actor=f.actor).get_input(ResourceRef.from_dict(packet_ref))
        assert ResourceRef.from_dict(evidence_ref) in frozen.consumed_refs
        resolved = evidence_handler.resolve(ResourceRef.from_dict(evidence_ref), actor=f.actor,
            verify_full=True)
        assert resolved["availability"] == "verified"
        assert hashlib.sha256(runner_bytes).hexdigest() == resolved["manifest"]["byte_digest"]
        assert resolved["bytes"] == runner_bytes
        assert result.payload["role"] == "fleet-check"
        assert result.payload["protocol_result"] == {"passed": True}
        assert tuple(ResourceRef.from_dict(value) if isinstance(value, dict) else value
                     for value in result.payload["evidence_refs"]) == (ResourceRef.from_dict(evidence_ref),)

        # A retained fleet check cannot satisfy an ordinary review-required scope.
        review_scope = AssessmentModule(f.store, actor=f.actor).declare_scope(
            "fleet-adapter-review-required", parent_obligation=task, protocol="review-required",
            criteria=[criterion], designated_approver="manager", authority=f.actor.authority,
            logical_request_key="fleet-adapter-review-scope")
        review_packet_ref = fixture.call("PA06", "freeze-input", {"scope_ref": review_scope.ref.to_dict(),
            "candidate_ref": candidate.to_dict(), "criterion_refs": [criterion.to_dict()],
            "source_refs": [candidate.to_dict()], "evidence_refs": [evidence_ref],
            "packet": {"candidate": "verified-lab"}}, "fleet-adapter-review-input")["ref"]
        review_packet = ResourceRef.from_dict(review_packet_ref)
        review_result = commands._assessment._assessment.assess(review_scope.ref,
            candidate=candidate, criterion=criterion, input_packet=review_packet,
            verdict="PASS", limit_pool=policy.pool_ref, role="fleet-check",
            evidence_refs=(ResourceRef.from_dict(evidence_ref),),
            protocol_result={"passed": True}, logical_request_key="fleet-adapter-review-result",
            actor=actor)
        review_adapter = _FleetAssessmentCommands(commands, candidate,
            (criterion,), review_packet, policy.pool_ref,
            "manager", "fleet-adapter-review", evidence_refs=(ResourceRef.from_dict(evidence_ref),))
        from herzchen.domains.assessment.model import AssessmentAuthorityError
        with pytest.raises(AssessmentAuthorityError, match="required review evidence"):
            review_adapter.accept(review_result, candidate=candidate,
                criterion=criterion, rationale="fleet check only", actor=actor)
    finally:
        if fixture is not None:
            fixture.doCleanups()


def _run_real_landing_with_runner_evidence(tmp_path, *, exit_code=0, wrong_commit=False,
                                          evidence_resolver=True, corrupt_evidence=False):
    """Build one real owner and drive its landing adapter through done."""
    import hashlib
    import json
    from pathlib import Path
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule
    from herzchen.domains.work import WorkGraph
    from herzchen.domains.work.admission import admitted_revision, authoring_stamp
    from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
    from herzchen.evidence.model import load_evidence_pack
    from herzchen.fleet.runner.store import ResultStore
    from otto.hostctl.fleet_landing import make_landing_service
    from otto.portfolio.local_assessment_policy import compose_manager_assessment_state
    from otto.portfolio.manager_assessment_command import manager_assessment_pool_from_command
    from tests import test_evidence_lifecycle as lifecycle
    from tests.test_landing import _project

    fixture = None
    try:
        from tests.test_local_assessment_composition import LocalAssessmentCompositionTests
        fixture = LocalAssessmentCompositionTests()
        fixture.setUp()
        f = fixture.f
        register_evidence(f.store)
        root, discover, loader = lifecycle._public_pack_hooks()
        found = discover(project_root=root)[0]
        found.entry.definition.version = "1.1.0"
        found.entry.definition.to_dict = lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2}
        found.entry.resource_handles += tuple(SimpleNamespace(path=path, kind="evidence_preset",
            resolved=root / path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in ("presets/list.json", "presets/read.json"))
        pack = load_evidence_pack(project_root=root, discoverer=lambda **kwargs: (found,), loader=loader)
        handler = EvidenceCommandHandler(f.store, Path(tmp_path) / "managed", pack=pack,
            adopted_pins=[item.to_dict() for item in pack.resources])
        resolver = handler
        if corrupt_evidence:
            real_resolve = handler.resolve
            def mismatch_resolution(reference, **kwargs):
                resolved = real_resolve(reference, **kwargs)
                return dict(resolved, actual_digest="0" * 64)
            resolver = SimpleNamespace(
                submit=handler.submit, resolve=mismatch_resolution)
        if evidence_resolver:
            from otto.portfolio.herzchen_binding import ProjectReadGrant
            from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
            issuer = f.binding.authenticated_actor("manager")
            f.owner = PortfolioOwnerBootstrap(f.store, binding=f.binding, owner_actor="manager",
                project_read_grant=ProjectReadGrant(issuer, (f.project.id,), "test-host", "v1"),
                evidence_payload_resolver=resolver)

        graph = WorkGraph(f.store, actor=f.actor)
        original_task = ResourceRef.from_dict(fixture.state["task_refs"]["PA06"])
        original = f.owner.graph.reader.get_identity(original_task)
        authored = dict(original.payload)
        authored["fields"] = {**dict(authored.get("fields", {})),
                               "check": {"argv": ["/usr/bin/true"]}}
        stamp = authoring_stamp(original_task.revision, authored, "manager")
        admitted = graph.revise(original_task, fields=authored["fields"],
            metadata_namespaces={"work.admission": stamp}, logical_request_key="land-evidence-activate",
            actor=f.actor)
        active = graph.revise(admitted.ref, lifecycle="active",
            logical_request_key="land-evidence-activate-task", actor=f.actor)
        task_ref = active.ref
        task_id = task_ref.id
        admitted_stamp = admitted_revision(admitted.payload)
        assert admitted_stamp == admitted.ref.revision

        criterion = ResourceRef.from_dict(fixture.state["criterion_refs"]["C09"])
        check_config = {**fixture.config, "scope_mode": "check-accepted"}
        fixture.config_path.write_text(json.dumps({"assessment_accounting": check_config}))
        fixture.state = compose_manager_assessment_state(fixture.state, config_path=fixture.config_path)
        fixture.state["task_refs"]["PA06"] = task_ref.to_dict()
        manager_assessment_pool_from_command(f.owner, state=fixture.state,
            request=fixture.request("PA06", key="done-evidence-pool"))
        fixture.call("PA06", "declare-scope", {"scope_ref": ResourceRef(
            f.actor.authority, "assessment.scope", "done-evidence-scope").to_dict(),
            "criterion_refs": [criterion.to_dict()], "protocol": "check-accepted"}, "done-evidence-scope")

        worker = f.owner.assignments.command_port.assign(task_ref, role="worker", principal="worker",
            manager="manager", session="done-evidence-dispatch", pins=[],
            logical_request_key="done-evidence-dispatch", actor=f.actor)
        project_ref = ResourceRef.from_dict(fixture.state["project_ref"])
        result_store = ResultStore(Path(tmp_path) / "runner-results")
        class Runner:
            def __init__(self):
                self.n = 0
            def call(self, request):
                if request["op"] == "submit":
                    self.n += 1
                    commit = subprocess.run(["git", "-C", request["cwd"], "rev-parse", "HEAD"],
                        check=True, capture_output=True, text=True).stdout.strip()
                    checked_commit = "f" * 40 if wrong_commit else commit
                    argv, cwd = list(request["argv"]), str(Path(request["cwd"]).resolve())
                    record = {"run_id": "land-run-" + str(self.n), "argv": argv, "cwd": cwd,
                        "commit": checked_commit, "binding": ResultStore.binding(argv, cwd, checked_commit),
                        "state": "settled", "outcome": "exited", "exit_code": exit_code, "seq": self.n}
                    result_store.put(record)
                    return {"ok": True, "run_id": record["run_id"]}
                record = result_store.get(request["run_id"])
                return {"ok": True, "done": True, "record": record}

        git_root = Path(tmp_path) / "git"
        git_root.mkdir()
        line, base, fleet = _project(git_root)
        dispatch = SimpleNamespace(assignment=worker.ref.id, role="worker", admitted_revision=admitted_stamp)
        project_state = dict(fixture.state)
        binding = {"record": dispatch, "task": SimpleNamespace(ref=task_ref),
            "task_ref": task_ref.to_dict(), "project_ref": project_ref.to_dict(),
            "assignment_ref": worker.ref.to_dict(), "generation": worker.generation,
            "project_state": project_state,
            "view": SimpleNamespace(server=SimpleNamespace(owner=f.owner,
                assert_assessment_policy_current=lambda: None))}
        def task_lookup(_task_id):
            current = f.owner.graph.reader.get_identity(task_ref)
            return {"id": task_id, "revision": current.ref.revision,
                "current_revision": current.ref.revision, "payload": current.payload}
        service = make_landing_service(fleet=fleet, result_store=result_store,
            repo_name="repo", repo_path=line, branch="main", owner=f.owner,
            runner=Runner(), views_provider=lambda: {},
            assignment_lookup=lambda assignment_id: binding if assignment_id == worker.ref.id else {},
            task_lookup=task_lookup)
        try:
            result = service.done("one", task_id, assignment_id=worker.ref.id)
        except Exception:
            from tests.test_landing import _run
            assert _run(line, "rev-parse", "refs/heads/main") == base
            if exit_code != 0 or wrong_commit or not evidence_resolver or corrupt_evidence:
                assert not AssessmentModule(f.store, actor=f.actor).list_decisions(parent_obligation=task_ref)
            raise
        return result, result_store, handler, f, base, fixture
    except BaseException:
        if fixture is not None:
            fixture.doCleanups()
        raise


def test_done_freezes_exact_sealed_check_evidence_and_accepts_through_owner_adapter(tmp_path):
    from herzchen.contracts import ResourceRef
    from herzchen.domains.assessment import AssessmentModule

    result, result_store, handler, f, base, fixture = _run_real_landing_with_runner_evidence(tmp_path)
    try:
        assert result["ok"] and result["landed"]
        assert result["commit"] != base
        runner_record = result_store.get(result["runner_run_id"])
        assessment = AssessmentModule(f.store, actor=f.actor)
        assessed = assessment.get_result(ResourceRef.from_dict(result["assessment_results"][0]))
        accepted = assessment.get_decision(ResourceRef.from_dict(result["acceptances"][0]))
        evidence_value, = assessed.payload["evidence_refs"]
        evidence = evidence_value if isinstance(evidence_value, ResourceRef) else ResourceRef.from_dict(evidence_value)
        frozen = assessment.get_input(assessed.input_packet_ref)
        exact_runner = {key: runner_record[key] for key in
            ("run_id", "commit", "binding", "argv", "cwd", "exit_code")}
        assert evidence.kind == "dat.content.document" and evidence.revision
        assert evidence in frozen.consumed_refs
        assert frozen.packet["inspection"]["runner"] == exact_runner
        assert assessed.protocol_result["runner"] == exact_runner
        assert accepted.evidence_refs == (evidence,)
        completion = f.owner.assignments.completion_blockers(assessed.parent_obligation_ref,
            candidate=assessed.candidate_ref, gate_refs=(accepted.ref,),
            actor=f.binding.authenticated_actor("manager"))
        assert completion["blockers"] == []
        assert completion["evidence_verification"] == "verified"
        resolved = handler.resolve(evidence, actor=f.binding.authenticated_actor("manager"), verify_full=True)
        assert resolved["verification"] == "full-verified"
        assert resolved["bytes"] == json.dumps(runner_record, sort_keys=True, separators=(",", ":")).encode()
        current_task = f.owner.graph.reader.get_identity(assessed.parent_obligation_ref)
        project_pin = ResourceRef.from_dict(fixture.state["project_ref"])
        current_project = f.owner.graph.reader.get_identity(project_pin)
        completion_result = f.owner.assignments.complete(
            current_task.ref, project=current_project.ref, assignment=fixture.manager.ref,
            expected_generation=fixture.manager.generation,
            expected_project_revision=current_project.ref.revision,
            expected_task_revision=current_task.ref.revision, disposition="accept",
            evidence_refs=(evidence,), evidence_hashes=(resolved["manifest"]["byte_digest"],),
            gate_refs=(accepted.ref,), candidate_ref=assessed.candidate_ref,
            result_ref=assessed.ref, logical_request_key="done-evidence-task-complete",
            actor=f.binding.authenticated_actor("manager"))
        assert completion_result["outcome"] == "completed"
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize("case", ["failed", "wrong-commit", "missing-evidence", "unresolvable-evidence"])
def test_done_refuses_failed_mismatched_or_unresolvable_check_evidence(tmp_path, case):
    from herzchen.fleet.landing import LandingError
    options = {"exit_code": 1} if case == "failed" else (
        {"wrong_commit": True} if case == "wrong-commit" else (
        {"evidence_resolver": False} if case == "missing-evidence" else {"corrupt_evidence": True}))
    with pytest.raises(LandingError):
        result = _run_real_landing_with_runner_evidence(tmp_path, **options)


@pytest.mark.parametrize("plan, message", [
    ({"repo": "repo-a"}, "otto.plan.branch"),
    ({}, "otto.plan.repo"),
    ({"repo": "missing", "branch": "project-line"}, "unknown repo: missing"),
], ids=["missing-branch", "missing-repo", "unknown-repo"])
def test_owner_registry_names_missing_or_unknown_project_plan_key(request, tmp_path, plan, message):
    registry, _project, _task, _assignment, record, token, _repository = _fleet_registry_fixture(
        tmp_path, request, plan=plan)

    with pytest.raises(LookupError, match=message):
        registry.assignment_context(record.assignment, token=token)


def test_empty_census_is_uncertain():
    snap = custody.census()
    assert isinstance(snap, dict) and os.getpid() in snap, "the real census lists this very process"

    blank = mock.MagicMock()
    blank.__enter__.return_value = blank
    blank.communicate.return_value = ("", None)
    blank.returncode = 0
    with mock.patch.object(custody, "_REAL_POPEN", return_value=blank):
        assert custody.census() is None, "an empty table is a broken census, not an empty machine"

    owner = None
    try:
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & wait"], census_fn=lambda: {},
                                       stdout=DEVNULL, stderr=DEVNULL)
        assert owner.doubt is not None, "no leader identity was captured, so doubt is latched"
        disposition = owner.terminate(0.2)
        assert disposition.state == "uncertain", disposition
        assert not disposition.gone
    finally:
        _reap_tree(owner.process if owner is not None else None)


def test_census_uses_kernel_birth_and_marks_unreadable_pid_unknown():
    self_pid, other_pid = os.getpid(), 987659
    output = "%d 1 %d S\n%d 1 %d S\n" % (self_pid, self_pid, other_pid, other_pid)
    ps = mock.MagicMock()
    ps.__enter__.return_value = ps
    ps.communicate.return_value = (output, None)
    ps.returncode = 0
    exact = custody.Proc(self_pid, 1, self_pid, "darwin:1792350000:123456")

    with mock.patch.object(custody, "_REAL_POPEN", return_value=ps) as popen, \
            mock.patch.object(custody, "_kernel_proc", side_effect=lambda pid: exact if pid == self_pid else None):
        snap = custody.census()

    assert snap[self_pid].birth == exact.birth
    assert snap[other_pid].birth is None
    assert "lstart" not in popen.call_args.args[0][-1]


def test_cleanup_latch_resumes_after_crash(tmp_path):
    latch = str(tmp_path / "latch.json")
    leaders = []
    owner = None
    try:
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & sleep 31 & wait"], latch_path=latch,
                                       stdout=DEVNULL, stderr=DEVNULL)
        leaders.append(owner.process)
        live = _observe_until(owner, lambda seen: len(seen) >= 3)
        assert len(live) >= 3, "the leader and both sleeps were tracked within 5s"
        live = owner.observe() or {}
        tracked = sorted(live)

        with open(latch, encoding="utf-8") as handle:
            record = json.load(handle)
        assert record["pgid"] == owner.pgid, "the latch names the group before any signal"
        assert set(record["members"]) == {str(pid) for pid in tracked}, "the latch names every tracked member"

        owner = None  # the owner crashes: no terminate, no Popen handle kept by custody
        assert os.path.exists(latch)
        disposition = custody.resume_cleanup(latch, 0.3)
        assert disposition.state == "gone", disposition
        leaders[0].wait(timeout=2)  # our zombie leader; a zombie still answers signal 0
        assert _dead_pids(tracked) == []
        assert not os.path.exists(latch), "a gone cleanup retires its latch"

        # A latch whose census is empty must stay uncertain and keep its file.
        second = str(tmp_path / "latch-empty.json")
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & sleep 31 & wait"], latch_path=second,
                                       stdout=DEVNULL, stderr=DEVNULL)
        leaders.append(owner.process)
        assert len(_observe_until(owner, lambda seen: len(seen) >= 3)) >= 3
        owner.observe()
        owner = None
        disposition = custody.resume_cleanup(second, 0.3, census_fn=lambda: {})
        assert disposition.state == "uncertain", disposition
        assert os.path.exists(second), "an uncertain cleanup keeps its latch"
    finally:
        if owner is not None:
            leaders.append(owner.process)
        for leader in leaders:
            _reap_tree(leader)


def test_reused_pgid_never_signalled(tmp_path):
    bystander = subprocess.Popen(["sleep", "30"], start_new_session=True, stdout=DEVNULL, stderr=DEVNULL)
    try:
        with mock.patch.object(custody.os, "kill", wraps=os.kill) as kill, \
                mock.patch.object(custody.os, "killpg", wraps=os.killpg) as killpg:
            def touched():
                return [c for c in kill.call_args_list + killpg.call_args_list
                        if c.args and c.args[0] == bystander.pid]

            # The leader pid is alive with a different birth: the old group is provably gone.
            stale = _write_latch(tmp_path / "stale.json", bystander.pid, "stale-birth",
                                 {bystander.pid: "stale-birth"})
            disposition = custody.resume_cleanup(stale, 0.3)
            assert disposition.state == "gone", disposition
            assert bystander.poll() is None, "a reused group id is never signalled"
            assert touched() == [], "no signal reached the bystander"
            assert not os.path.exists(stale)

            # The leader birth is unknown and the members cannot be proven ours: uncertain, latch kept.
            mismatch = _write_latch(tmp_path / "mismatch.json", bystander.pid, None,
                                    {bystander.pid: "stale-birth"})
            disposition = custody.resume_cleanup(mismatch, 0.3)
            assert disposition.state == "uncertain", disposition
            assert bystander.poll() is None
            assert touched() == [], "no signal reached the bystander"
            assert os.path.exists(mismatch), "an uncertain cleanup keeps its latch"

            # The unit check: the stale identity never passes the group signal fence.
            unit = custody.Custody(None, bystander.pid, "stale-birth", {bystander.pid: "stale-birth"})
            assert unit.signal_group(signal.SIGTERM) is False
            assert bystander.poll() is None
            assert touched() == [], "no signal reached the bystander"
    finally:
        _reap_tree(bystander)


def test_same_second_pid_reuse_never_matches_or_receives_a_signal(tmp_path):
    pid = 987654
    original = "darwin:1792350000:100"
    reused = "darwin:1792350000:900"
    snap = {pid: custody.Proc(pid, 1, pid, reused)}
    latch = _write_latch(tmp_path / "same-second.json", pid, original, {pid: original})

    with mock.patch.object(custody.os, "kill") as kill, mock.patch.object(custody.os, "killpg") as killpg:
        unit = custody.Custody.from_latch(latch, census_fn=lambda: snap)
        assert unit.observe() == {}, "the reused pid cannot pass the live member check"
        assert unit.signal_group(signal.SIGTERM) is False
        disposition = unit.terminate(0)

    assert disposition.state == "gone", disposition
    assert kill.call_args_list == []
    assert killpg.call_args_list == []
    assert not os.path.exists(latch)


def test_missing_kernel_birth_keeps_custody_uncertain_and_unsignalled(tmp_path):
    pid = 987655
    original = "darwin:1792350000:100"
    snap = {pid: custody.Proc(pid, 1, pid, None)}
    latch = _write_latch(tmp_path / "missing-birth.json", pid, original, {pid: original})

    with mock.patch.object(custody.os, "kill") as kill, mock.patch.object(custody.os, "killpg") as killpg:
        unit = custody.Custody.from_latch(latch, census_fn=lambda: snap)
        assert unit.observe() == {}
        assert unit.signal_group(signal.SIGTERM) is False
        disposition = unit.terminate(0)

    assert disposition.state == "uncertain", disposition
    assert kill.call_args_list == []
    assert killpg.call_args_list == []
    assert os.path.exists(latch)
    assert custody.Custody.from_latch(latch, census_fn=lambda: {}).doubt == "tracked process identity unavailable"


def test_unreadable_zombie_leader_does_not_keep_an_empty_group_uncertain(tmp_path):
    pid = 987662
    birth = "darwin:1792350000:100"
    latch = _write_latch(tmp_path / "zombie.json", pid, birth, {pid: birth})
    snap = {pid: custody.Proc(pid, 1, pid, None, zombie=True)}

    with mock.patch.object(custody.os, "kill") as kill, mock.patch.object(custody.os, "killpg") as killpg:
        disposition = custody.resume_cleanup(latch, 0, census_fn=lambda: snap)

    assert disposition.state == "gone", disposition
    assert kill.call_args_list == []
    assert killpg.call_args_list == []
    assert not os.path.exists(latch)


def test_latch_cleanup_settles_after_signalled_members_become_zombies(tmp_path):
    leader, child = 987663, 987664
    leader_birth = "darwin:1792350000:100"
    child_birth = "darwin:1792350000:200"
    latch = _write_latch(tmp_path / "zombie-after-term.json", leader, leader_birth,
                         {leader: leader_birth, child: child_birth})
    snap = {leader: custody.Proc(leader, 1, leader, leader_birth),
            child: custody.Proc(child, leader, leader, child_birth)}

    def finish_group(pgid, sig):
        assert (pgid, sig) == (leader, signal.SIGTERM)
        snap[leader] = custody.Proc(leader, 1, leader, None, zombie=True)
        snap[child] = custody.Proc(child, leader, leader, None, zombie=True)

    with mock.patch.object(custody.os, "kill") as kill, \
            mock.patch.object(custody.os, "killpg", side_effect=finish_group) as killpg:
        disposition = custody.resume_cleanup(latch, 0, census_fn=lambda: snap)

    assert disposition.state == "gone", disposition
    assert kill.call_args_list == []
    assert killpg.call_args_list == [mock.call(leader, signal.SIGTERM)]
    assert not os.path.exists(latch)


def test_display_time_latch_cannot_claim_a_kernel_identity(tmp_path):
    pid = 987658
    latch = tmp_path / "old-latch.json"
    display_birth = "Sun Oct 18 12:00:00 2026"
    latch.write_text(json.dumps({"pgid": pid, "leader_birth": display_birth, "state": "running",
                                 "members": {str(pid): display_birth}}), encoding="utf-8")
    snap = {pid: custody.Proc(pid, 1, pid, "darwin:1792350000:100")}

    with mock.patch.object(custody.os, "kill") as kill, mock.patch.object(custody.os, "killpg") as killpg:
        disposition = custody.resume_cleanup(str(latch), 0, census_fn=lambda: snap)

    assert disposition.state == "uncertain", disposition
    assert kill.call_args_list == []
    assert killpg.call_args_list == []
    assert latch.exists()
    unrelated = {42: custody.Proc(42, 1, 42, "darwin:1792350001:1")}
    assert custody.resume_cleanup(str(latch), 0, census_fn=lambda: unrelated).state == "uncertain"


def test_unverified_escapee_latches_doubt_after_parent_disappears():
    leader, escapee = 987656, 987657
    birth = "darwin:1792350000:100"
    snap = {leader: custody.Proc(leader, 1, leader, birth),
            escapee: custody.Proc(escapee, leader, escapee, None)}
    unit = custody.Custody(None, leader, birth, {leader: birth}, census_fn=lambda: snap)

    assert unit.observe() == {leader: birth}
    assert unit.doubt == "child identity unavailable"
    snap = {42: custody.Proc(42, 1, 42, "darwin:1792350001:1")}
    assert unit.status().state == "uncertain"


def test_exact_escapee_birth_controls_individual_signalling():
    leader, escapee = 987660, 987661
    leader_birth = "darwin:1792350000:100"
    escapee_birth = "darwin:1792350000:200"
    snap = {leader: custody.Proc(leader, 1, leader, leader_birth),
            escapee: custody.Proc(escapee, leader, escapee, escapee_birth)}
    unit = custody.Custody(None, leader, leader_birth, {leader: leader_birth}, census_fn=lambda: snap)

    with mock.patch.object(custody.os, "kill") as kill, mock.patch.object(custody.os, "killpg") as killpg:
        assert unit.observe() == {leader: leader_birth, escapee: escapee_birth}
        unit._send(signal.SIGTERM)
        assert kill.call_args_list == [mock.call(escapee, signal.SIGTERM)]
        assert killpg.call_args_list == [mock.call(leader, signal.SIGTERM)]

        # The escaped pid is recycled within the same second. It must lose custody.
        snap = {leader: snap[leader],
                escapee: custody.Proc(escapee, 1, escapee, "darwin:1792350000:900")}
        kill.reset_mock()
        killpg.reset_mock()
        unit._send(signal.SIGTERM)
        assert kill.call_args_list == []
        assert killpg.call_args_list == [mock.call(leader, signal.SIGTERM)]


def test_group_kill_takes_grandchildren_and_setsid_escapees(tmp_path):
    pidfile = tmp_path / "escapee.pid"
    script = "\n".join([
        "import os, sys, time",
        "pidfile = sys.argv[1]",
        "if os.fork() == 0:",
        "    os.setsid()",
        "    with open(pidfile + '.tmp', 'w') as handle:",
        "        handle.write(str(os.getpid()))",
        "    os.replace(pidfile + '.tmp', pidfile)",
        "    time.sleep(42)",
        "    os._exit(0)",
        "time.sleep(42)",
    ])
    command = "sleep 40 & sh -c 'sleep 41 & wait' & %s -c %s %s & wait" % (
        shlex.quote(sys.executable), shlex.quote(script), shlex.quote(str(pidfile)))
    owner = custody.Custody.launch(["/bin/sh", "-c", command], stdout=DEVNULL, stderr=DEVNULL)
    leader = owner.process
    escapee = None
    try:
        deadline = time.monotonic() + 5.0
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), "the python child started its setsid grandchild within 5s"
        escapee = int(pidfile.read_text(encoding="utf-8"))
        assert os.getpgid(escapee) != owner.pgid, "the grandchild really left the group"

        live = _observe_until(owner, lambda seen: escapee in seen and len(seen) >= 6)
        assert escapee in live, "the setsid escapee was adopted through its tracked parent"
        tracked = sorted(live)

        disposition = owner.terminate(0.3)
        assert disposition.state == "gone", disposition
        leader.wait(timeout=2)
        assert _dead_pids(tracked) == [], "every grouped and escaped pid is dead"
    finally:
        if escapee is not None:
            _kill_pid(escapee)
        _reap_tree(leader)


def test_normal_exit_release_sweeps_stragglers():
    owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 40 & sleep 1; exit 0"],
                                   stdout=DEVNULL, stderr=DEVNULL)
    leader = owner.process
    try:
        time.sleep(0.3)
        live = owner.observe() or {}
        assert len(live) >= 2, "the straggler sleep is tracked while the shell still runs"
        tracked = sorted(live)

        assert leader.wait(timeout=5) == 0, "the shell finished on its own"
        disposition = owner.release()
        assert disposition.state == "gone", disposition
        assert _dead_pids(tracked) == [], "the straggler was swept"
    finally:
        _reap_tree(leader)


# -- the Codex CLI binding over custody: timeout, interrupt and a recycled pid ----------------------

CODEX_USAGE = {"input_tokens": 3, "output_tokens": 1}


def _ps_stat(pid):
    """The ps state column for pid ('' when ps lists nothing). Uses the real Popen even under a patch."""
    proc = custody._REAL_POPEN(["ps", "-o", "stat=", "-p", str(pid)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    out, _ = proc.communicate(timeout=5)
    return out.strip()


def _is_dead(pid):
    """Gone: no such pid, or a zombie (or nothing listed by ps). A pid this test did not launch is never touched."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    stat = _ps_stat(pid)
    return stat == "" or stat.startswith("Z")


def _await_dead(pids, seconds=3.0):
    """The pids still alive after a bounded wait. ``[]`` means every one is dead or a zombie."""
    deadline = time.monotonic() + seconds
    while True:
        alive = [pid for pid in pids if not _is_dead(pid)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.05)


def _pids_in(paths):
    """Pids this test's fake CLI wrote to its own files. Missing or unreadable files contribute nothing."""
    pids = []
    for path in paths:
        try:
            pids.append(int(path.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            pass
    return pids


def _fake_cli(directory, body):
    """A fake Codex CLI: a python script used as the launcher. It reads its prompt, then runs ``body``."""
    path = os.path.join(str(directory), "fake-codex")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!%s\n" % sys.executable)
        handle.write("import json, os, shlex, signal, subprocess, sys, time\n")
        handle.write("DEVNULL = subprocess.DEVNULL\n")
        handle.write("def emit(event):\n    print(json.dumps(event), flush=True)\n")
        handle.write("sys.stdin.read()\n")
        handle.write(body)
    os.chmod(path, 0o755)
    return path


def _binding(directory, launcher, **overrides):
    """A real CodexCliBinding with a one-second finite start deadline."""
    options = {"timeout_seconds": 1.0, "occurrence_deadline": time.monotonic() + 10}
    options.update(overrides)
    return host_module.CodexCliBinding(worktree=str(directory), launcher=launcher, prompt="fake brief", **options)


def _invoke():
    return HostRequest(HostOperation.INVOKE, HostIdentity("fixture-worker", None),
                       ResourceRef("fixture", "work.task", "task", "rev-1"), "read-only")


def _turn_lines():
    return [json.dumps({"type": "thread.started", "thread_id": "fake-session"}),
            json.dumps({"type": "turn.started", "turn_id": "turn-1"}),
            json.dumps({"type": "turn.completed", "turn_id": "turn-1", "usage": CODEX_USAGE})]


def _shape(value):
    """Keys and list structure only, leaves collapsed: two captures with the same shape have the same fields."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_shape(item) for item in value[:1]]
    return "leaf"


def test_codex_timeout_kills_group(tmp_path):
    child_file, grand_file = tmp_path / "child.pid", tmp_path / "grand.pid"
    grand_code = ("import os, time; os.setsid(); open(%r, 'w').write(str(os.getpid())); time.sleep(60)"
                  % str(grand_file))
    body = (
        "emit({'type': 'thread.started', 'thread_id': 'fake-session'})\n"
        "child = subprocess.Popen(['sleep', '60'], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "open(%r, 'w').write(str(child.pid))\n"
        "subprocess.Popen(['/bin/sh', '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "time.sleep(60)\n" % (str(child_file), "%s -c %s & wait" % (sys.executable, shlex.quote(grand_code))))
    launcher = _fake_cli(tmp_path, body)
    try:
        receipt, envelope = _binding(tmp_path, launcher).execute(_invoke())
        assert child_file.exists() and grand_file.exists(), "the fake CLI launched the child and the setsid grandchild"
        pids = _pids_in([child_file, grand_file])
        assert receipt.outcome == HostOutcome.UNKNOWN, receipt
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        assert envelope["exit_status"] is None
        assert _await_dead(pids, 3.0) == [], "the same-group child and the setsid grandchild are both dead within 3s"
    finally:
        for pid in _pids_in([child_file, grand_file]):
            _kill_pid(pid)


def test_codex_interrupt_after_usage_is_unknown(tmp_path):
    interrupted_dir, normal_dir = tmp_path / "interrupted", tmp_path / "normal"
    interrupted_dir.mkdir()
    normal_dir.mkdir()
    lines = _turn_lines()
    # The CLI reports the whole turn, then kills itself with SIGTERM: exit status -15.
    interrupted = _fake_cli(interrupted_dir, "for line in %r:\n    print(line, flush=True)\n"
                            "os.kill(os.getpid(), signal.SIGTERM)\ntime.sleep(5)\n" % (lines,))
    normal = _fake_cli(normal_dir, "for line in %r:\n    print(line, flush=True)\nsys.exit(0)\n" % (lines,))

    receipt, envelope = _binding(interrupted_dir, interrupted).execute(_invoke())
    assert envelope["exit_status"] == -15, envelope["exit_status"]
    assert receipt.outcome == HostOutcome.UNKNOWN, "an interrupted turn is unknown, never failed"
    assert receipt.unsupported_reason == "codex_execution_interrupted", receipt
    assert envelope["usage_capture"], "usage observed before the interrupt is retained"

    normal_receipt, normal_envelope = _binding(normal_dir, normal).execute(_invoke())
    assert normal_receipt.outcome == HostOutcome.SUCCEEDED, normal_receipt
    assert _shape(envelope["usage_capture"]) == _shape(normal_envelope["usage_capture"]), \
        "the interrupted capture has the same shape as a normal turn's"

    # The same three records through the stream: the exit code alone decides the outcome.
    for code, expected in ((-2, "unknown"), (1, "failed"), (0, "succeeded")):
        stream = CodexStream()
        for line in lines:
            stream.feed(line)
        result = stream.finish(code)
        assert result.outcome == expected, (code, result.outcome)
        assert result.usage_capture is not None, code


def test_timed_out_fake_cli_leaves_nothing_and_spares_reused_pid(tmp_path):
    # C1: a same-group child with a grandchild in the same group, plus a child that ignores SIGTERM.
    ignoring_file, sh_file, grand_file = tmp_path / "ignoring.pid", tmp_path / "sh.pid", tmp_path / "grand.pid"
    ignoring_code = ("import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                     "open(%r, 'w').write(str(os.getpid())); time.sleep(60)" % str(ignoring_file))
    shell_code = "sleep 60 & echo $! > %s; wait" % shlex.quote(str(grand_file))
    body = (
        "emit({'type': 'thread.started', 'thread_id': 'fake-session'})\n"
        "ignoring = subprocess.Popen([sys.executable, '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "for _ in range(500):\n"
        "    if os.path.exists(%r):\n        break\n"
        "    time.sleep(0.01)\n"
        "shell = subprocess.Popen(['/bin/sh', '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "open(%r, 'w').write(str(shell.pid))\n"
        "time.sleep(60)\n" % (ignoring_code, str(ignoring_file), shell_code, str(sh_file)))
    launcher = _fake_cli(tmp_path, body)
    files = [ignoring_file, sh_file, grand_file]
    try:
        receipt, envelope = _binding(tmp_path, launcher).execute(_invoke())
        assert all(path.exists() for path in files), "the ignoring child, the shell and its grandchild all started"
        pids = _pids_in(files)
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        assert _await_dead(pids, 3.0) == [], "no child, grandchild or SIGTERM-ignoring child is left"
    finally:
        for pid in _pids_in(files):
            _kill_pid(pid)

    # C2: the launch-time census shows the pid with another birth, so the group id was recycled after launch.
    bystander = subprocess.Popen(["sleep", "60"], start_new_session=True, stdout=DEVNULL, stderr=DEVNULL)
    real_census = custody.census
    try:
        real = real_census()
        assert real is not None and bystander.pid in real, "the real census lists the bystander"
        at_launch = dict(real)
        info = real[bystander.pid]
        at_launch[bystander.pid] = custody.Proc(info.pid, info.ppid, info.pgid, "launch-birth", info.zombie)
        calls = []

        def census_after_launch():
            calls.append(1)
            return at_launch if len(calls) == 1 else real_census()   # the first census is taken at launch

        stand_in = mock.MagicMock(name="stand_in")
        stand_in.pid = bystander.pid
        stand_in.stdout = None      # the communicate-only branch: the timeout is a TimeoutExpired from communicate
        stand_in.stderr = None
        stand_in.poll.return_value = 0   # reaped as far as custody can see: the group is never "ours" by leader
        stand_in.returncode = 0
        stand_in.wait.return_value = 0
        stand_in.communicate.side_effect = [subprocess.TimeoutExpired("codex", 1.0), ("", "")]

        with mock.patch.object(custody.os, "kill", wraps=os.kill) as kill, \
                mock.patch.object(custody.os, "killpg", wraps=os.killpg) as killpg, \
                mock.patch.object(host_module.subprocess, "Popen", return_value=stand_in), \
                mock.patch.object(custody, "census", side_effect=census_after_launch):
            receipt, envelope = _binding(tmp_path, "/fixture/codex").execute(_invoke())
        assert receipt.outcome == HostOutcome.UNKNOWN, receipt
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        touched = [c for c in kill.call_args_list + killpg.call_args_list
                   if c.args and c.args[0] == bystander.pid]
        assert touched == [], "no kill or killpg reached the bystander pid or its group"
        assert bystander.poll() is None, "a recycled pid is never signalled: the bystander is still alive"
        assert len(calls) > 1, "the timeout path consulted the census after launch"
    finally:
        _reap_tree(bystander)

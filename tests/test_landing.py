"""Acceptance tests for the owner-controlled landing lifecycle."""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from herzchen.contracts import ResourceRef


def _landing_api():
    # Keep imports inside helpers so canon/main reports each missing acceptance case
    # independently when this file is run against an extracted baseline.
    from herzchen.fleet.landing import LandingError, LandingService
    return LandingError, LandingService


def _run(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return done.stdout.strip()


class _Lab:
    def __init__(self, name: str, path: Path):
        self.name, self.path = name, path

    def head(self):
        return _run(self.path, "rev-parse", "HEAD")

    def dirty(self):
        return _run(self.path, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")[:-1]


class _Fleet:
    def __init__(self, repo: Path, labs: dict[str, _Lab]):
        self.repo, self.labs = repo, labs

    def _lab(self, name):
        return self.labs[name]

    def checkpoint(self, worktree, paths, *, message):
        path = Path(worktree)
        _run(path, "add", "--", *paths)
        _run(path, "-c", "user.name=LAND test", "-c", "user.email=land@test.invalid",
             "commit", "-m", message)

    def remove(self, name, merged_into=None):
        lab = self.labs.pop(name)
        import shutil
        shutil.rmtree(lab.path)


class _Runner:
    """Runner double with an independent sealed-result readback."""
    def __init__(self, *, submitted=None, await_record=None, store_record=None, barrier=None, exit_code=0):
        from herzchen.fleet.runner.store import ResultStore
        self.binding = ResultStore.binding
        self.submitted, self.await_record, self.store_record = submitted, await_record, store_record
        self.barrier = barrier
        self.exit_code = exit_code
        self.calls = []
        self.records = {}
        self.counter = 0
        self._lock = threading.Lock()

    def call(self, req):
        self.calls.append(dict(req))
        if req["op"] == "submit":
            with self._lock:
                self.counter += 1
                run_id = "run-%d" % self.counter
            commit = _run(Path(req["cwd"]), "rev-parse", "HEAD")
            record = {"run_id": run_id, "argv": list(req["argv"]), "cwd": os.path.realpath(req["cwd"]),
                      "commit": commit,
                      "binding": self.binding(list(req["argv"]), os.path.realpath(req["cwd"]), commit),
                      "state": "settled", "outcome": "exited", "exit_code": self.exit_code}
            self.records[run_id] = record
            return {"ok": True, "run_id": run_id} if self.submitted is None else self.submitted(run_id, record)
        run_id = req["run_id"]
        record = self.records[run_id]
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        reply_record = record if self.await_record is None else self.await_record(run_id, record)
        return {"ok": True, "done": True, "record": reply_record}

    def lookup(self, run_id):
        if self.store_record is not None:
            return self.store_record(run_id, self.records[run_id])
        return self.records[run_id]


def _project(tmp_path: Path, *, conflict=False):
    line = tmp_path / "line"
    line.mkdir()
    _run(line, "init", "-b", "main")
    _run(line, "config", "user.name", "LAND test")
    _run(line, "config", "user.email", "land@test.invalid")
    (line / "shared.txt").write_text("base\n")
    _run(line, "add", "shared.txt")
    _run(line, "commit", "-m", "base")
    base = _run(line, "rev-parse", "HEAD")
    labs = {}
    for name, content in (("one", "worker change\n"), ("two", "worker change\n" if conflict else "other change\n")):
        path = tmp_path / ("lab-" + name)
        _run(tmp_path, "clone", "-q", "--no-hardlinks", "--branch", "main", str(line), str(path))
        _run(path, "branch", "-m", "lab/" + name)
        _run(path, "config", "user.name", "LAND test")
        _run(path, "config", "user.email", "land@test.invalid")
        if conflict:
            (path / "shared.txt").write_text(content)
        else:
            (path / (name + ".txt")).write_text(content)
        labs[name] = _Lab(name, path)
    return line, base, _Fleet(line, labs)


def _service(fleet, runner, *, task=None, assessment_assess=None, blockers=None, gate=None):
    _LandingError, LandingService = _landing_api()
    admitted = task or _admitted_task()
    calls = {"accept": [], "decisions": [], "blockers": [], "gate": [], "gate_records": []}

    class Assessment:
        def assess(self, scope, *, candidate, criterion, input_packet, verdict, protocol_result,
                   limit_pool, actor, **kwargs):
            if assessment_assess:
                assessment_assess(criterion)
            calls["accept"].append((dict(protocol_result["runner"]), admitted,
                                    {"candidate": candidate, "criterion": criterion},
                                    tuple(protocol_result.get("gate_runners", ()))))
            return SimpleNamespace(ref=ResourceRef("assessment", "assessment.result", "result-1", "r1"),
                                    verdict="PASS",
                                    protocol_result=protocol_result)

        def accept(self, result_ref, *, candidate, criterion, rationale, actor):
            calls["decisions"].append((result_ref, candidate, criterion, rationale, actor))
            return SimpleNamespace(ref=ResourceRef("assessment", "assessment.decision", "decision-1", "r1"),
                                   result_ref=result_ref,
                                   disposition="accept")

    def clear_blockers(*args, **kwargs):
        calls["blockers"].append((args, kwargs))
        return {"required": False, "blockers": []}

    def clear_gate(*args, **kwargs):
        calls["gate"].append((args, kwargs))
        return {"blockers": [], "clear": True}

    service = LandingService(fleet, runner, lambda _task: admitted, "refs/heads/main",
                             assessment=Assessment(),
                             assessment_context=lambda *_a, **kwargs: (
                                 calls["gate_records"].extend(kwargs.get("gate_records", ())) or
                                 {"scope": "scope@1", "input_packet": "packet@1", "limit_pool": "pool@1"}),
                             criterion_lookup=lambda ref: ref,
                             completion_blockers=blockers or clear_blockers,
                             completion_gate=gate or clear_gate,
                             result_lookup=runner.lookup)
    return service, calls


def _admitted_task(*, argv=("/usr/bin/true",), gate_checks=None):
    from herzchen.domains.work.admission import authoring_stamp
    payload = {"kind": "task", "project_ref": "project@1", "title": "LAND task",
               "name": "task-1", "outcome": "land verified work",
               "fields": {"check": {"argv": list(argv)}}, "parent": None, "dependencies": []}
    payload["metadata_namespaces"] = {
        "work.admission": authoring_stamp("task-rev-1", payload, "reviewer")}
    result = {"revision": "task-rev-1", "payload": payload}
    if gate_checks is not None:
        result["gate_checks"] = gate_checks
    return result


def _admitted_gate(check):
    from herzchen.domains.work.admission import authoring_stamp
    payload = {"kind": "task", "project_ref": "project@1", "title": "Gate task",
               "name": "gate-1", "outcome": "verify gate", "fields": {"check": check},
               "parent": None, "dependencies": []}
    payload["metadata_namespaces"] = {
        "work.admission": authoring_stamp("gate-rev-1", payload, "reviewer")}
    return {"id": "gate-1", "revision": "gate-rev-1", "payload": payload}


def _advance(service, lab="one", task_id="task-1"):
    return service.done(lab, task_id, candidate="candidate@1", criterion=_criterion(),
                        parent_obligation="obligation@1", actor="owner")


def _criterion(revision="1"):
    return ResourceRef("assessment", "assessment.criterion", "criterion", revision)


def test_forged_lab_result_ignored(tmp_path):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path)
    runner = _Runner(await_record=lambda _rid, record: {**record, "commit": "forged-commit"})
    service, calls = _service(fleet, runner)
    with pytest.raises(LandingError):
        _advance(service)
    assert _run(line, "rev-parse", "refs/heads/main") == base
    assert calls["accept"] == []
    assert len([call for call in runner.calls if call["op"] == "submit"]) == 1


def test_lab_edited_check_ignored(tmp_path):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path)
    (fleet.labs["one"].path / "worker-check.json").write_text('{"argv":["/bin/echo","edited"]}\n')
    runner = _Runner(await_record=lambda _rid, record: {**record, "argv": ["/bin/echo", "edited"]})
    service, calls = _service(fleet, runner)
    with pytest.raises(LandingError):
        _advance(service)
    submitted = next(call for call in runner.calls if call["op"] == "submit")
    assert submitted["argv"] == ["/usr/bin/true"]
    assert "worker-check.json" in _run(fleet.labs["one"].path, "show", "--pretty=", "--name-only", "HEAD")
    assert _run(line, "rev-parse", "refs/heads/main") == base
    assert calls["accept"] == []


def test_stale_criterion_refused(tmp_path):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path)
    runner = _Runner()
    _LandingError, LandingService = _landing_api()
    service = LandingService(fleet, runner, lambda _task: _admitted_task(), "refs/heads/main",
                             assessment=object(), assessment_context=lambda *_a, **_k: {},
                             criterion_lookup=lambda _ref: _criterion("2"),
                             completion_blockers=lambda *_a, **_k: {"required": False, "blockers": []},
                             completion_gate=lambda *_a, **_k: {"blockers": [], "clear": True},
                             result_lookup=runner.lookup)
    with pytest.raises(LandingError, match="criterion|stale"):
        _advance(service)
    assert _run(line, "rev-parse", "refs/heads/main") == base
    assert runner.calls == []


def test_two_passing_labs_conflict_caught(tmp_path):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path, conflict=False)
    runner = _Runner(barrier=threading.Barrier(2))
    service, calls = _service(fleet, runner)
    outcomes = []

    def land(name):
        try:
            outcomes.append(_advance(service, name))
        except Exception as exc:
            outcomes.append(exc)

    workers = [threading.Thread(target=land, args=(name,)) for name in ("one", "two")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
    assert all(not worker.is_alive() for worker in workers)
    assert sum(isinstance(result, dict) and result.get("landed") for result in outcomes) == 1
    assert sum(isinstance(result, LandingError) for result in outcomes) == 1
    landed = _run(line, "rev-parse", "refs/heads/main")
    assert landed != base
    assert landed == calls["accept"][0][0]["commit"]
    assert _run(line, "rev-parse", "HEAD") == landed
    assert len(calls["blockers"]) == 1 and len(calls["gate"]) == 1
    assert len(calls["accept"]) == 1
    assert calls["accept"][0][0]["commit"] == landed
    assert calls["decisions"][0][0] == ResourceRef("assessment", "assessment.result", "result-1", "r1")
    assert len([call for call in runner.calls if call["op"] == "submit"]) == 2


def test_runner_checks_rebased_commit_not_lab_commit(tmp_path):
    _LandingError, _ = _landing_api()
    line, _base, fleet = _project(tmp_path)
    fleet.checkpoint(str(fleet.labs["one"].path), ["one.txt"], message="checkpoint before rebase")
    old_lab_commit = _run(fleet.labs["one"].path, "rev-parse", "HEAD")
    (line / "line-only.txt").write_text("advanced independently\n")
    _run(line, "add", "line-only.txt")
    _run(line, "commit", "-m", "advance line before landing")
    for lab in fleet.labs.values():
        _run(lab.path, "fetch", "origin", "main")
    runner = _Runner()
    service, _calls = _service(fleet, runner)
    result = _advance(service)
    submitted = next(call for call in runner.calls if call["op"] == "submit")
    checked_commit = runner.records["run-1"]["commit"]
    assert checked_commit != old_lab_commit
    assert submitted["cwd"] == os.path.realpath(fleet.repo.parent / "lab-one")
    assert result["commit"] == checked_commit
    assert _run(line, "rev-parse", "HEAD") == checked_commit


def test_check_gate_refuses_free_text(tmp_path):
    LandingError, _ = _landing_api()
    _line, _base, fleet = _project(tmp_path)
    runner = _Runner()
    service, calls = _service(fleet, runner, task=_admitted_task(
        gate_checks=[_admitted_gate({"command": "run tests"})]))
    with pytest.raises(LandingError, match="argv|free-text|admitted"):
        service.done("one", "task-1", candidate="candidate@1", criterion=_criterion(),
                     parent_obligation="obligation@1")
    assert runner.calls == [] and calls["accept"] == []


def test_admitted_gate_check_uses_rebased_commit(tmp_path):
    _LandingError, _ = _landing_api()
    line, _base, fleet = _project(tmp_path)
    task = _admitted_task(gate_checks=[_admitted_gate({"argv": ["/usr/bin/true"]})])
    runner = _Runner()
    service, calls = _service(fleet, runner, task=task)
    result = _advance(service)
    submitted = [call for call in runner.calls if call["op"] == "submit"]
    assert len(submitted) == 2
    assert [call["argv"] for call in submitted] == [["/usr/bin/true"], ["/usr/bin/true"]]
    commits = [runner.records["run-%d" % index]["commit"] for index in (1, 2)]
    assert commits[0] == commits[1] == result["commit"] == _run(line, "rev-parse", "HEAD")
    assert calls["accept"][0][3] and calls["accept"][0][3][0]["commit"] == commits[0]


def test_failed_admitted_check_returns_lab_to_worker(tmp_path):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path)
    runner = _Runner(exit_code=1)
    service, calls = _service(fleet, runner)
    with pytest.raises(LandingError, match="check failed"):
        _advance(service)
    assert _run(line, "rev-parse", "refs/heads/main") == base
    assert "one" in fleet.labs and not calls["accept"] and not calls["decisions"]


def test_rebase_conflict_returns_clean_lab_to_worker(tmp_path):
    LandingError, _ = _landing_api()
    line, _base, fleet = _project(tmp_path, conflict=True)
    lab = fleet.labs["one"]
    fleet.checkpoint(str(lab.path), ["shared.txt"], message="worker checkpoint")
    worker_commit = lab.head()
    (line / "shared.txt").write_text("conflicting line change\n")
    _run(line, "add", "shared.txt")
    _run(line, "commit", "-m", "advance line with conflict")
    line_tip = _run(line, "rev-parse", "HEAD")
    _run(lab.path, "fetch", "origin", "main")
    runner = _Runner()
    service, calls = _service(fleet, runner)
    with pytest.raises(LandingError, match="conflict|rebase"):
        _advance(service)
    assert _run(line, "rev-parse", "HEAD") == line_tip
    assert "one" in fleet.labs
    assert lab.head() == worker_commit
    assert lab.dirty() == []
    assert runner.calls == [] and calls["accept"] == []


def test_facade_done_starts_landing(tmp_path):
    from herzchen.fleet.tools import DONE, CHECK, FeedbackLedger, ToolFacade, ToolSpec, TokenBook, AllowlistedPort
    from herzchen.fleet.tools.facade import LandingOwnerPort

    line, base, fleet = _project(tmp_path)
    runner = _Runner()
    service, calls = _service(fleet, runner)

    class Fallback:
        def call(self, operation, assignment, args, *, feedback):
            fallback_calls.append((operation, assignment, dict(args)))
            return {"task": True}

    fallback_calls = []
    owner = LandingOwnerPort(lambda assignment: {"service": service,
                                                   "lab_name": {"task-1": "one", "task-2": "two"}[assignment],
                                                   "task_id": assignment, "candidate": "candidate@1",
                                                   "criterion": _criterion(), "parent_obligation": "obligation@1",
                                                   "actor": "owner"},
                             fallback=Fallback())
    book = TokenBook()
    specs = (ToolSpec("check", CHECK, "worker-check"),
             ToolSpec("done", DONE, "worker-done", args=("summary",)))
    facade = ToolFacade(specs, {"worker": ("check", "done")},
                        AllowlistedPort(owner, ("worker-check", "worker-done")), book,
                        FeedbackLedger())
    token = book.issue("task-1", "worker")
    other_token = book.issue("task-2", "worker")
    smuggled = facade.call(other_token, "done", {"summary": "ready", "lab_name": "one"})
    assert smuggled["ok"] is False and smuggled["error"] == "bad_args"
    assert "two" in fleet.labs and "one" in fleet.labs and runner.calls == []
    result = facade.call(token, "done", {"summary": "ready"})
    assert result["ok"] is True and result["kind"] == DONE and result["accepted"] is False
    assert result["result"]["landed"] is True
    assert len(calls["accept"]) == 1


def test_landed_write_artifact_remains_available_for_native_turn_capture(tmp_path):
    """The real Claude adapter captures worker bytes after worker-done returns."""
    from otto.agents.claude_adapter import capture_artifacts

    line, _base, fleet = _project(tmp_path)
    lab = fleet.labs["one"]
    artifact = lab.path / "answer.txt"
    artifact.write_text("captured owner result\n")
    runner = _Runner()
    service, _calls = _service(fleet, runner)

    landed = _advance(service)
    native = {
        "tools": {"write-1": {"name": "Write", "input": {
            "file_path": str(artifact), "content": "captured owner result\n"}}},
        "tool_results": {"write-1": {"is_error": False}},
    }

    # This is the exact post-stream capture operation: landing's ``done`` call
    # has returned, and the adapter now verifies the bytes written in the lab.
    captured = capture_artifacts(native, str(lab.path))

    assert landed["landed"] is True
    assert captured[0]["name"] == "answer.txt"
    assert base64.b64decode(captured[0]["content_base64"]) == b"captured owner result\n"


@pytest.mark.parametrize("calls,initial,final", [
    ([('Edit', {'old_string': 'base\n', 'new_string': 'after'})], 'base\n', 'after'),
    ([('Write', {'content': 'first'}), ('Edit', {'old_string': 'first', 'new_string': 'last'})],
     'irrelevant', 'last'),
])
def test_capture_uses_successful_edit_sequence_from_worker_checkpoint(tmp_path, calls, initial, final):
    from otto.agents.claude_adapter import capture_artifacts

    line, _base, fleet = _project(tmp_path)
    lab = fleet.labs['one']
    path = lab.path / ('shared.txt' if calls[0][0] == 'Edit' else 'answer.txt')
    path.write_text(initial)
    tools, results = {}, {}
    for index, (name, inputs) in enumerate(calls):
        ident = 'call-%d' % index
        tools[ident] = {'name': name, 'input': {'file_path': str(path), **inputs}}
        results[ident] = {'is_error': False}
    path.write_text(final)
    service, _ = _service(fleet, _Runner())
    _advance(service)

    captured = capture_artifacts({'tools': tools, 'tool_results': results}, str(lab.path))

    assert base64.b64decode(captured[0]['content_base64']) == final.encode()


def test_capture_rejects_uncalled_checkpoint_drift_and_unsafe_paths(tmp_path):
    from otto.agents.claude_adapter import ClaudeBindingError, capture_artifacts

    line, _base, fleet = _project(tmp_path)
    lab = fleet.labs['one']
    path = lab.path / 'answer.txt'
    path.write_text('uncalled change')
    uncalled = lab.path / 'uncalled.txt'
    uncalled.write_text('changed with no successful write')
    fleet.checkpoint(str(lab.path), ['answer.txt', 'uncalled.txt'], message='land one')
    with pytest.raises(ClaudeBindingError):
        capture_artifacts({'tools': {'write': {'name': 'Write', 'input': {
            'file_path': str(path), 'content': 'authorized'}}},
            'tool_results': {'write': {'is_error': False}}}, str(lab.path))
    with pytest.raises(ClaudeBindingError):
        capture_artifacts({'tools': {'read': {'name': 'Read', 'input': {
            'file_path': str(uncalled)}}},
            'tool_results': {'read': {'is_error': False}}}, str(lab.path))
    path.write_text('authorized')
    fleet.checkpoint(str(lab.path), ['answer.txt'], message='land one')
    assert [item['name'] for item in capture_artifacts({'tools': {'write': {
        'name': 'Write', 'input': {'file_path': str(path), 'content': 'authorized'}}},
        'tool_results': {'write': {'is_error': False}}}, str(lab.path))] == ['answer.txt']
    with pytest.raises(ClaudeBindingError):
        capture_artifacts({'tools': {'write': {'name': 'Write', 'input': {
            'file_path': str(lab.path / '.git' / 'config'), 'content': 'authorized'}}},
            'tool_results': {'write': {'is_error': False}}}, str(lab.path))
    outside = tmp_path / 'outside.txt'
    outside.write_text('authorized')
    with pytest.raises(ClaudeBindingError):
        capture_artifacts({'tools': {'write': {'name': 'Write', 'input': {
            'file_path': str(outside), 'content': 'authorized'}}},
            'tool_results': {'write': {'is_error': False}}}, str(lab.path))
    target = lab.path / 'real.txt'
    target.write_text('authorized')
    link = lab.path / 'link.txt'
    link.symlink_to(target.name)
    with pytest.raises(ClaudeBindingError):
        capture_artifacts({'tools': {'write': {'name': 'Write', 'input': {
            'file_path': str(link), 'content': 'authorized'}}},
            'tool_results': {'write': {'is_error': False}}}, str(lab.path))


@pytest.mark.parametrize('mode', ['edit', 'write_edit', 'auto_merge_write'])
def test_real_owner_claude_edit_capture_settles_and_removes_lab(tmp_path, mode):
    """A real owner captures authorized tool bytes before sweeping a landed lab."""
    from tests import test_execution_application as owner_fixture
    from herzchen.fleet.labs import LabFleet
    from otto.agents.claude_adapter import (ClaudeNativeResultVerifier, ClaudeWorkerAdapter, ROLE_PROFILES)
    from otto.agents.tests.test_claude_binding import local_transport
    from otto.portfolio.occurrence_reads import read_captured_artifact, result_view

    f = owner_fixture.ExecutionApplicationTests()
    f.setUp()
    tmp_path_factory = tempfile.TemporaryDirectory(prefix='capture-edit-owner-')
    state = tempfile.TemporaryDirectory(prefix='capture-edit-state-')
    try:
        project_root = Path(tmp_path_factory.name) / 'project'
        project_root.mkdir()
        line, base, _ = _project(project_root)

        def checkpoint(worktree, paths, *, message):
            subprocess.run(['git', '-C', str(worktree), 'add', '--', *paths], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(worktree), '-c', 'user.name=LAND test',
                            '-c', 'user.email=land@test.invalid', 'commit', '-m', message], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        fleet = LabFleet(line, project_root / 'real-labs', checkpoint=checkpoint, shared_dirs=())
        lab = fleet.create('one', base='refs/heads/main')
        if mode == 'auto_merge_write':
            # Give both branches separate editable lines in the same tracked file.
            shared = Path(line) / 'shared.txt'
            shared.write_text('line-a\nline-b\nline-c\nline-d\nline-e\n'
                              'line-f\nline-g\nline-h\nbase-i\nbase-j\n')
            subprocess.run(['git', '-C', str(line), 'add', '--', 'shared.txt'], check=True)
            subprocess.run(['git', '-C', str(line), '-c', 'user.name=LAND test',
                            '-c', 'user.email=land@test.invalid', 'commit', '-m', 'two line base'], check=True)
            subprocess.run(['git', '-C', str(lab.path), 'fetch', str(line), 'main'], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(lab.path), 'reset', '--hard', 'FETCH_HEAD'], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            base = subprocess.run(['git', '-C', str(line), 'rev-parse', 'HEAD'], check=True,
                                  stdout=subprocess.PIPE, text=True).stdout.strip()
        workspace = str(lab.path.resolve())
        landing, _calls = _service(fleet, _Runner(), task=_admitted_task())
        edit_path = 'shared.txt' if mode in {'edit', 'auto_merge_write'} else 'answer.txt'
        if mode == 'edit':
            operations = [('Edit', {'old_string': 'base\n', 'new_string': 'edited\n'})]
            expected = b'edited\n'
        elif mode == 'write_edit':
            operations = [('Write', {'content': 'first\n'}),
                          ('Edit', {'old_string': 'first\n', 'new_string': 'final\n'})]
            expected = b'final\n'
        else:
            operations = [('Write', {'content': 'worker-a\nline-b\nline-c\nline-d\nline-e\n'
                                     'line-f\nline-g\nline-h\nbase-i\nbase-j\n'})]
            expected = b'worker-a\nline-b\nline-c\nline-d\nline-e\nline-f\nline-g\nline-h\nbase-i\nbase-j\n'
        # The transport emits a successful native tool stream and applies the
        # corresponding file operations inside the worker worktree.
        encoded_ops = repr(operations)
        script = r'''import json,os,sys
frame=json.loads(sys.stdin.readline());prompt=frame['message']['content'][0]['text'];session=frame.get('session_id') or 'native-session';init=prompt.startswith('Initialize this session only.');cwd=os.getcwd();tools=[] if init else ['Edit','Glob','Grep','Read','Write']
def emit(e): print(json.dumps(e),flush=True)
emit({'type':'system','subtype':'init','session_id':session,'cwd':cwd,'model':'gpt-test','permissionMode':'bypassPermissions','tools':tools,'mcp_servers':[],'plugins':[],'skills':[],'slash_commands':[]})
emit({'type':'user','uuid':'input-init' if init else 'input-work','session_id':session,'message':{'role':'user','content':[{'type':'text','text':prompt}]}})
if not init:
 for i,(name,fields) in enumerate(OPS):
  path=os.path.join(cwd,PATH); ident='tool-'+str(i); inp={'file_path':path,**fields}
  emit({'type':'assistant','uuid':'assistant-'+str(i),'session_id':session,'message':{'role':'assistant','model':'gpt-test','content':[{'type':'tool_use','id':ident,'name':name,'input':inp}]}})
  try: current=open(path).read()
  except FileNotFoundError: current=''
  if name=='Write': current=fields['content']
  else:
   old=fields['old_string']; new=fields['new_string']; current=current.replace(old,new)
  with open(path,'w') as out: out.write(current)
  emit({'type':'user','uuid':'result-'+str(i),'session_id':session,'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':ident,'is_error':False,'content':'written'}]}})
emit({'type':'result','subtype':'success','is_error':False,'session_id':session,'uuid':'result','result':'READY' if init else 'Delivered artifact.','usage':{'input_tokens':11,'output_tokens':4}})
'''.replace('OPS', encoded_ops).replace('PATH', repr(edit_path))
        transport = local_transport(workspace, str(Path(state.name).resolve()), script=script)
        original_run = transport.run
        landed_commits = []

        def run_and_land(prompt, **options):
            native = original_run(prompt, **options)
            if not options.get('initializer'):
                if mode == 'auto_merge_write':
                    shared = Path(line) / 'shared.txt'
                    shared.write_text('line-a\nline-b\nline-c\nline-d\nline-e\n'
                                      'line-f\nline-g\nline-h\nbase-i\nline-j\n')
                    subprocess.run(['git', '-C', str(line), 'add', '--', 'shared.txt'], check=True)
                    subprocess.run(['git', '-C', str(line), '-c', 'user.name=LAND test',
                                    '-c', 'user.email=land@test.invalid', 'commit', '-m', 'line edit'], check=True)
                    subprocess.run(['git', '-C', str(lab.path), 'fetch', str(line), 'main'], check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                landed_commits.append(_advance(landing)['commit'])
            return native

        transport.run = run_and_land
        adapter = ClaudeWorkerAdapter(owner='worker', source=workspace, worktree=workspace,
            launcher_pin=transport.pin, state_root=str(Path(state.name).resolve()),
            requested_model='gpt-test', requested_reasoning='high', transport=transport)

        def settle(**kwargs):
            due = f.port.read_due(kwargs['schedule_id'])
            view = result_view(due)
            assert view['required_capture'] is True
            assert base64.b64decode(read_captured_artifact(due,
                artifact_ref=view['artifacts'][0]['ref'])['content_base64']) == expected
            swept = fleet.sweep_landed('refs/heads/main', lambda _name, commit: commit in landed_commits)
            assert any(item.name == 'one' and item.action == 'removed' for item in swept)
            return {'cleanup_pending': False}

        f.owner.landed_worker_settler = settle
        app = f.owner.execution_application(due_port=f.port, adapter=adapter,
            clock=lambda: owner_fixture.NOW, native_result_verifier=ClaudeNativeResultVerifier())
        request = f.request()
        request['instruction_contract']['authority']['effect_profile'] = 'workspace-write-worker'
        request['instruction_contract']['authority']['permitted_effects'] = sorted(ROLE_PROFILES['worker']['effects'])
        request['instruction_contract']['authority']['workspace_roots'] = [workspace]
        request['instruction_contract']['read_targets'] = [workspace]

        result = app.assign_and_start(**request)

        assert result['outcome'] == 'succeeded', result.get('result', {}).get('error')
        due = f.port.read_due(result['schedule_id'])
        assert due['completion_state'] == 'succeeded'
        assert not lab.path.exists()
        if mode == 'auto_merge_write':
            landed = subprocess.run(['git', '-C', str(line), 'show', landed_commits[0] + ':shared.txt'],
                                    check=True, stdout=subprocess.PIPE).stdout
            assert landed == b'worker-a\nline-b\nline-c\nline-d\nline-e\nline-f\nline-g\nline-h\nbase-i\nline-j\n'
            assert landed != expected
    finally:
        f.doCleanups()
        state.cleanup()
        tmp_path_factory.cleanup()


def test_facade_check_is_feedback_only(tmp_path):
    from herzchen.fleet.tools import FeedbackLedger, ToolFacade, TokenBook, AllowlistedPort
    from herzchen.fleet.tools import CHECK, DONE, ToolSpec
    from herzchen.fleet.tools.facade import LandingOwnerPort

    line, base, fleet = _project(tmp_path)
    (fleet.labs["one"].path / "check-input.txt").write_text("checkpointed\n")
    fleet.checkpoint(str(fleet.labs["one"].path), ["one.txt", "check-input.txt"],
                     message="clean feedback check")
    runner = _Runner()
    service, calls = _service(fleet, runner)

    owner = LandingOwnerPort(lambda assignment: {"service": service, "lab_name": "one", "task_id": assignment,
                                                   "candidate": "candidate@1", "criterion": _criterion(),
                                                   "parent_obligation": "obligation@1", "actor": "owner"})
    book = TokenBook()
    specs = (ToolSpec("check", CHECK, "worker-check"),
             ToolSpec("done", DONE, "worker-done", args=("summary",)))
    facade = ToolFacade(specs, {"worker": ("check", "done")},
                        AllowlistedPort(owner, ("worker-check", "worker-done")),
                        book, FeedbackLedger())
    token = book.issue("task-1", "worker")
    result = facade.call(token, "check")
    assert result["ok"] is True and result["kind"] == CHECK
    assert result["feedback"] is True and result["accepted"] is False
    assert calls["accept"] == [] and calls["blockers"] == [] and calls["gate"] == []
    assert _run(line, "rev-parse", "HEAD") == base
    assert "one" in fleet.labs


def test_facade_check_ignores_worker_supplied_identity(tmp_path):
    from herzchen.fleet.tools import FeedbackLedger, ToolFacade, TokenBook, AllowlistedPort
    from herzchen.fleet.tools import CHECK, DONE, ToolSpec
    from herzchen.fleet.tools.facade import LandingOwnerPort

    line, base, fleet = _project(tmp_path)
    fleet.checkpoint(str(fleet.labs["two"].path), ["two.txt"], message="clean second lab")
    runner = _Runner()
    service, calls = _service(fleet, runner)
    owner = LandingOwnerPort(lambda assignment: {
        "service": service, "lab_name": {"task-1": "one", "task-2": "two"}[assignment],
        "task_id": assignment, "candidate": "candidate@1", "criterion": _criterion(),
        "parent_obligation": "obligation@1", "actor": "owner",
    })
    book = TokenBook()
    specs = (ToolSpec("check", CHECK, "worker-check", args=("lab_name", "task_id")),
             ToolSpec("done", DONE, "worker-done", args=("summary",)))
    facade = ToolFacade(specs, {"worker": ("check", "done")},
                        AllowlistedPort(owner, ("worker-check", "worker-done")), book,
                        FeedbackLedger())
    token = book.issue("task-2", "worker")
    result = facade.call(token, "check", {"lab_name": "one", "task_id": "task-1"})
    submitted = next(call for call in runner.calls if call["op"] == "submit")
    assert result["ok"] is True and result["feedback"] is True
    assert submitted["cwd"] == os.path.realpath(fleet.labs["two"].path)
    assert submitted["task"] == "task-2"
    assert calls["accept"] == [] and _run(line, "rev-parse", "HEAD") == base


@pytest.mark.parametrize("include_decision", [True, False])
def test_required_completion_blocker_must_link_acceptance(tmp_path, include_decision):
    LandingError, _ = _landing_api()
    line, base, fleet = _project(tmp_path)
    runner = _Runner()
    service, calls = _service(fleet, runner, blockers=lambda _parent, *, candidate, gate_refs, actor: {
        "required": True, "blockers": [],
        "accepted_decision_refs": [gate_refs[-1]] if include_decision else [],
    })
    if include_decision:
        result = _advance(service)
        assert result["landed"] is True
        assert _run(line, "rev-parse", "HEAD") == result["commit"]
        assert calls["gate"]
    else:
        with pytest.raises(LandingError, match="completion blockers"):
            _advance(service)
        assert _run(line, "rev-parse", "HEAD") == base
        assert "one" in fleet.labs

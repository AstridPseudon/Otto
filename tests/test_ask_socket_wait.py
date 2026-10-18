"""ASK socket wait and paused admission regressions."""
import os
import json
import socket
import tempfile
import threading
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from otto.portfolio import cli
from otto.portfolio.caller_client import call, call_connection
from otto.portfolio.execution_host import ExecutionAdmissionHeld, ExecutionHost
from otto.portfolio.manager_journey_service import ManagerJourneyService


def test_otto_wait_uses_existing_authenticated_caller_socket():
    assignment = '{"authority":"a","kind":"work.assignment","id":"ask-1","revision":"r1"}'
    request = {}

    def call(path, value, *, timeout=None):
        request.update(path=path, value=value, timeout=timeout)
        return {"outcome": "read", "schema": "otto.wait.v1"}

    with patch.dict(os.environ, {"OTTO_CALLER_SOCKET": "/private/tmp/caller.sock"}), \
         patch("otto.portfolio.caller_client.call", side_effect=call):
        result_code = cli.client_main([
            "wait", "--assignment-ref", assignment, "--generation", "4",
            "--native-session-id", "native-4", "--asking-schedule-id", "sched-4",
            "--issue-id", "issue-4", "--cursor", "cursor-4", "--timeout-seconds", "8",
        ])

    assert result_code == 0
    assert request["path"] == "/private/tmp/caller.sock"
    assert request["value"] == {
        "command": "wait-for-answer", "issue_id": "issue-4",
        "asking_schedule_id": "sched-4",
        "assignment_ref": {"authority": "a", "kind": "work.assignment", "id": "ask-1", "revision": "r1"},
        "generation": 4, "native_session_id": "native-4", "cursor": "cursor-4",
        "timeout_seconds": 8.0,
    }
    assert request["timeout"] > 8


def test_otto_wait_reports_owner_down_and_restart_event_when_socket_is_gone(tmp_path):
    result = call(str(tmp_path / "closed-owner.sock"), {"command": "wait-for-answer"}, timeout=1)
    assert result["schema"] == "otto.wait.v1"
    assert result["outcome"] == "owner_down"
    assert result["owner_event"]["type"] == "owner-down"
    assert "restart" in result["next_action"]

    client, owner = socket.socketpair()
    owner.close()
    with client:
        dropped = call_connection(client, {"command": "wait-for-answer"})
    assert dropped["outcome"] == "owner_down"
    assert dropped["owner_event"]["type"] == "owner-down"

    output = StringIO()
    with patch.dict(os.environ, {"OTTO_CALLER_SOCKET": str(tmp_path / "closed-owner.sock")}), \
         redirect_stdout(output):
        code = cli.client_main([
            "wait", "--assignment-ref", '{"authority":"a","kind":"work.assignment","id":"x","revision":"r1"}',
            "--generation", "1", "--native-session-id", "native", "--asking-schedule-id", "schedule",
            "--issue-id", "issue", "--cursor", "cursor", "--timeout-seconds", "5",
        ])
    assert code != 0
    assert json.loads(output.getvalue())["owner_event"]["type"] == "owner-down"


def test_active_otto_wait_is_released_with_owner_down_event_on_drain():
    from tests import test_execution_application as owner_fixture
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.decisions import DecisionsModule

    owner = owner_fixture.ExecutionApplicationTests()
    owner.setUp()
    try:
        assignment, guide, mandate = owner.role_handles("manager", "manager", "native")
        prepared = owner.app.prepare_role(role="manager", project_ref=owner.project.ref.to_dict(),
            task_ref=owner.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="ask-wait-real-due",
            instruction="Wait for a decision", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="native")
        schedule = prepared["schedule_id"]
        issue_id = "issue-real-wait"
        request = {"command": "wait-for-answer", "issue_id": issue_id,
            "asking_schedule_id": schedule, "assignment_ref": assignment.ref.to_dict(),
            "generation": 1, "native_session_id": "native", "cursor": None,
            "timeout_seconds": 0.0}
        waiting = DecisionsModule(owner.store, actor=owner.actor).record_wait(
            owner.task.ref, missing_obligation="a decision", owner="manager",
            awaited_ref=owner.task.ref, revisit_condition="when answered",
            asking_assignment_ref=assignment.ref, asking_session_id="native", asking_generation=1,
            metadata={"asking_schedule_id": schedule, "issue_id": issue_id},
            logical_request_key="ask-wait-real-record")
        stream = "report:" + assignment.ref.id
        first_report = owner.owner.assignments.append_report(
            assignment.ref, {"schema": "testpatch.report.v1", "sequence": "before-drain"},
            expected_generation=1, logical_request_key="ask-wait-before-drain",
            actor=owner.actor)
        state = {"project_ref": owner.project.ref.to_dict(), "owner": "manager",
            "manager": "manager", "assignment_ref": assignment.ref.to_dict(),
            "manager_generation": 1, "task_refs": {"T1": owner.task.ref.to_dict()},
            "asking_waits": {issue_id: {"wait_ref": waiting.ref.to_dict()}}}
        server = SimpleNamespace(owner=owner.owner, portfolio=owner.app.portfolio, state=state,
            store=owner.store, due_port=owner.port, _execution=lambda **_kwargs: owner.app,
            _save_state=lambda: None)
        host = SimpleNamespace(draining=True)
        service = ManagerJourneyService(server=server, host=host,
            run_path=owner.temporary.name, workspace=owner.temporary.name)
        context = {"role": "manager", "principal": "manager",
            "project_ref": owner.project.ref.to_dict(), "task_ref": owner.task.ref.to_dict(),
            "assignment_ref": assignment.ref.to_dict(), "generation": 1,
            "occurrence_ref": {"schedule_id": schedule}, "native_session": {"id": "native"}}
        result = service._wait_for_answer(request, context)
        assert result["outcome"] == "owner_down"
        assert result["owner_event"]["type"] == "owner-down"
        from herzchen.kernel import EventCursorReader, EventFilter
        stream = "report:" + assignment.ref.id
        event_filter = EventFilter(event_types=("work.report.appended",))
        continuation = {"schema": "test.ask-wait-continuation.v1", "marker": "after-drain"}
        owner.app.assignments.append_report(assignment.ref, continuation,
            expected_generation=1, logical_request_key="ask-wait-after-drain-report", actor=owner.actor)
        reader = EventCursorReader(owner.store)
        page = reader.page(stream, cursor=result["cursor"], event_filter=event_filter)
        assert page.complete
        assert len(page.events) == 1
        event = page.events[0]
        assert event.event_type == "work.report.appended"
        assert event.subject != first_report.ref
        report = owner.store.get_record(event.subject)
        assert report.payload["value"] == continuation
        resumed = reader.page(stream, cursor=page.cursor, event_filter=event_filter)
        assert resumed.complete and resumed.events == (), "continued page replayed the consumed report"

        host.draining = False
        foreign_context = {**context, "principal": "foreign-principal"}
        try:
            service._wait_for_answer(request, foreign_context)
        except PermissionError:
            pass
        else:
            raise AssertionError("foreign asker principal passed owner authorization")
    finally:
        owner.doCleanups()


def test_ask_wait_invalid_json_arguments_return_structured_errors():
    cases = (
        ["wait", "--assignment-ref", "not-json", "--generation", "1",
         "--native-session-id", "native", "--asking-schedule-id", "schedule",
         "--issue-id", "issue", "--cursor", "cursor"],
        ["ask", "--issue-key", "issue", "--problem", "problem", "--evidence", "not-json",
         "--impact", "impact", "--requested-decision", "decision",
         "--return-condition", "condition", "--request-key", "request"],
    )
    with patch.dict(os.environ, {"OTTO_CALLER_SOCKET": "/private/tmp/caller.sock"}):
        for words in cases:
            output = StringIO()
            with redirect_stdout(output):
                code = cli.client_main(words)
            assert code != 0
            response = json.loads(output.getvalue())
            assert response["schema"] == "otto.cli-error.v1"
            assert response["error"]["code"] == "invalid_argument"


def test_authenticated_socket_wait_does_not_block_answer_command():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        socket_path = root / "caller.sock"
        wait_entered = threading.Event()
        answer_seen = threading.Event()
        result = {}

        def handler(request):
            if request.get("command") == "wait-for-answer":
                wait_entered.set()
                assert answer_seen.wait(3), "answer command could not enter while wait was blocked"
                return {"outcome": "read"}
            if request.get("command") == "answer-session-result":
                answer_seen.set()
                return {"outcome": "accepted"}
            return {"outcome": "error"}

        host = ExecutionHost(directory=root / "commands", handler=handler,
                             socket_path=socket_path)
        host.start()

        def call(command):
            from otto.portfolio.caller_client import call as socket_call
            return socket_call(str(socket_path), {"command": command}, timeout=4)

        try:
            waiting = threading.Thread(target=lambda: result.setdefault("wait", call("wait-for-answer")))
            waiting.start()
            assert wait_entered.wait(2)
            answer = call("answer-session-result")
            assert answer["outcome"] == "accepted"
            waiting.join(3)
            assert not waiting.is_alive()
            assert result["wait"]["outcome"] == "read"
        finally:
            host.close()


def test_paused_due_is_refused_before_execution_admission():
    due = type("Due", (), {"schedule_id": "paused-1", "host_state": "paused",
                           "target": {"native_id": "native"}, "project_ref": "project",
                           "role": "manager", "host_evidence": {}, "assignment_ref": {"authority": "a", "id": "assign"},
                           "generation": 1, "profile": "read-only"})()
    app = type("App", (), {"runtime": type("Runtime", (), {
        "adapter": type("Adapter", (), {"owner_transport_only": True, "worktree": "/tmp"})(),
    })(), "portfolio": type("Portfolio", (), {"operations": object()})()})()
    host = ExecutionHost(directory=Path("/private/tmp/ask-paused-admission"),
                         handler=lambda _: None, bounded_transports=True)
    with patch.object(ExecutionHost, "current_bounded", return_value=host):
        try:
            try:
                host.admit_execution(app, due, lambda: None)
            except ExecutionAdmissionHeld as exc:
                assert "paused task" in str(exc)
            else:
                raise AssertionError("paused Due was admitted")
            assert host._executions == {}
        finally:
            host.close()


def test_active_due_is_refused_when_authoritative_task_is_paused():
    task_ref = {"authority": "a", "kind": "work.task", "id": "task-1", "revision": "r1"}
    project_ref = {"authority": "a", "kind": "work.project", "id": "project-1", "revision": "r1"}
    due = type("Due", (), {"schedule_id": "active-due-1", "host_state": "active",
        "target": {"task_ref": task_ref, "project_ref": project_ref}, "project_ref": "project-1"})()
    app = type("App", (), {"runtime": type("Runtime", (), {
        "adapter": type("Adapter", (), {"owner_transport_only": True})(),
    })(), "portfolio": type("Portfolio", (), {"operations": object()})()})()
    host = ExecutionHost(directory=Path("/private/tmp/ask-paused-task-admission"),
                         handler=lambda _: None, bounded_transports=True)
    with patch.object(ExecutionHost, "current_bounded", return_value=host), \
         patch("otto.portfolio.owner_readers.task_reader",
               return_value=lambda _: {"lifecycle": "paused", "payload": {}}):
        try:
            try:
                host.admit_execution(app, due, lambda: None)
            except ExecutionAdmissionHeld as exc:
                assert "paused task" in str(exc)
            else:
                raise AssertionError("active Due for an authoritatively paused task was admitted")
            assert host._executions == {}
        finally:
            host.close()


def test_pending_answer_continuation_survives_owner_restart_until_due_settles():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        request = {"command": "answer-session-result", "asking_schedule_id": "ask-schedule-7",
            "report_ref": {"authority": "a", "kind": "work.report", "id": "answer", "revision": "r1"},
            "issue_id": "issue-7",
            "assignment_ref": {"authority": "a", "kind": "work.assignment", "id": "assignment-7", "revision": "r1"},
            "generation": 7, "native_session_id": "native-7"}
        calls = []
        first = ExecutionHost(directory=root, handler=lambda value: calls.append(value) or {
            "outcome": "pending", "provider_called": False, "effects_started": False})
        admitted = first._owned(lambda: first.submit(request))
        assert admitted["outcome"] == "admitted"
        retained_path = root / ("request-" + admitted["retained_handle"] + ".json")
        response_path = root / ("response-" + admitted["retained_handle"] + ".json")
        first._serve_files(False)
        assert calls == [request]
        assert retained_path.exists()
        assert not response_path.exists()
        assert (root / ("pending-" + admitted["retained_handle"] + ".json")).exists()

        # A new host has no _executions entry or completion callback. It picks
        # up the same retained request and can finish it after the exact Due
        # has become terminal.
        restarted_calls = []
        restarted = ExecutionHost(directory=root, handler=lambda value: restarted_calls.append(value) or {
            "outcome": "started", "provider_called": False, "effects_started": False})
        pending_path = root / ("pending-" + admitted["retained_handle"] + ".json")
        pending = json.loads(pending_path.read_text())
        pending["retry_after"] = 0
        pending_path.write_text(json.dumps(pending))
        restarted._serve_files(False)
        assert restarted_calls == [request]
        assert not retained_path.exists()
        assert json.loads(response_path.read_text())["outcome"] == "started"
        assert restarted._executions == {}


def test_answer_submit_requires_exact_session_envelope():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        host = ExecutionHost(directory=root, handler=lambda _: None)
        base = {"command": "answer-session-result", "asking_schedule_id": "ask-schedule-8",
            "report_ref": {"authority": "a", "kind": "work.report", "id": "answer", "revision": "r1"},
            "issue_id": "issue-8",
            "assignment_ref": {"authority": "a", "kind": "work.assignment", "id": "assignment-8", "revision": "r1"},
            "generation": 8, "native_session_id": "native-8"}
        admitted = host._owned(lambda: host.submit(base))
        assert admitted["outcome"] == "admitted"
        for request in ({**base, "resume_after_settlement": True}, {**base, "extra": "rejected"}):
            try:
                host._owned(lambda request=request: host.submit(request))
            except ValueError as exc:
                assert "exact asking occurrence" in str(exc)
            else:
                raise AssertionError("malformed answer continuation was retained")


def test_answer_continuation_does_not_launch_during_owner_drain():
    called = []
    host = ExecutionHost(directory=Path("/private/tmp/ask-answer-drain"),
                         handler=lambda request: called.append(request))
    host.begin_drain()
    result = host._dispatch({"command": "answer-session-result"})
    assert result["outcome"] == "held"
    assert called == []

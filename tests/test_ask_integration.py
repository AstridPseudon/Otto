"""Owner-backed ASK continuation preserves the asking native session."""
from dataclasses import replace
import json
import hashlib

from otto.portfolio.execution import OccurrencePreparationError


def _fixture():
    from src.otto.portfolio.tests.test_help_routing import HelpRoutingTests
    value = HelpRoutingTests()
    value.setUp()
    return value


def test_answer_continues_exact_asking_occurrence_and_rejects_stale_generation():
    fixture = _fixture()
    try:
        f = fixture.f
        assignment, guide, mandate = f.role_handles("worker", "worker", "ask-native-session")
        asking = f.app.prepare_role(role="worker", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, mandate_ref=mandate, context_refs=(guide, mandate),
            request_key="ask-native-occurrence", instruction="Wait for the owner decision.",
            model="gpt-test", reasoning="high", profile="workspace-write",
            native_session_id="ask-native-session")
        due = f.app._read(asking["schedule_id"])
        f.port.save_due(due.schedule_id, replace(due, stop_state="completed",
            completion_state="succeeded", in_flight_request=None,
            last_completed_request="settle-asking-occurrence").to_dict(), request_id="settle-asking-occurrence",
            expected_version=due.version)

        asked = fixture.loop.ask(project_ref=f.project.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=assignment.generation,
            actor="worker", issue_key="integration-question", problem="Need an owner decision",
            evidence=[{"observed": "blocked"}], impact="Cannot continue safely",
            requested_decision="Choose the next step", return_condition="Decision is recorded",
            request_id="integration-ask", asking_schedule_id=asking["schedule_id"])
        answered = fixture.loop.respond_to_issue(project_ref=f.project.ref.to_dict(),
            issue_id=asked["issue_id"], actor="root", authority_source="Owner decision",
            response="Use the bounded repair route", proposed_solution="Repair only this task",
            next_action="Continue the current session", request_id="integration-answer")
        report_ref = answered["report_ref"]

        resumed = f.app.continue_from_answer(asking_schedule_id=asking["schedule_id"],
            report_ref=report_ref, issue_id=asked["issue_id"], assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, native_session_id="ask-native-session")
        self_due = f.app._read(resumed["schedule_id"])
        assert resumed["outcome"] == "committed"
        assert resumed["schedule_id"] != asking["schedule_id"]
        assert self_due.target["native_id"] == "ask-native-session"
        assert self_due.target["assignment_ref"] == assignment.ref.to_dict()
        assert self_due.generation == assignment.generation
        assert "Use the bounded repair route" in self_due.instruction

        started = f.app.continue_from_answer(asking_schedule_id=asking["schedule_id"],
            report_ref=report_ref, issue_id=asked["issue_id"], assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, native_session_id="ask-native-session", execute=True)
        assert started["schedule_id"] == resumed["schedule_id"]
        assert started["outcome"] in {"succeeded", "replayed", "adoption-required"}
        assert len([row for row in f.port.list_due() if row["schedule_id"] == resumed["schedule_id"]]) == 1

        f.owner.assignments.command_port.reassign(assignment.ref, principal="worker",
            session="replacement-session", expected_generation=assignment.generation,
            logical_request_key="integration-reassign-asker", actor=f.actor)
        try:
            f.app.continue_from_answer(asking_schedule_id=asking["schedule_id"],
                report_ref=report_ref, issue_id=asked["issue_id"], assignment_ref=assignment.ref.to_dict(),
                generation=assignment.generation, native_session_id="ask-native-session")
        except OccurrencePreparationError:
            pass
        else:
            raise AssertionError("stale asking generation was allowed to continue")
    finally:
        fixture.doCleanups()


def test_answered_worker_continuation_dispatches_once_and_replay_is_inert():
    fixture = _fixture()
    try:
        f = fixture.f
        assignment, guide, mandate = f.role_handles("worker", "worker", "ask-dispatch-session")
        asking = f.app.prepare_role(role="worker", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, mandate_ref=mandate, context_refs=(guide, mandate),
            request_key="ask-dispatch-occurrence", instruction="Wait for the owner decision.",
            model="gpt-test", reasoning="high", profile="read-only",
            native_session_id="ask-dispatch-session")
        due = f.app._read(asking["schedule_id"])
        f.port.save_due(due.schedule_id, replace(due, stop_state="completed",
            completion_state="succeeded", in_flight_request=None,
            last_completed_request="settle-ask-dispatch-occurrence").to_dict(),
            request_id="settle-ask-dispatch-occurrence", expected_version=due.version)

        asked = fixture.loop.ask(project_ref=f.project.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=assignment.generation,
            actor="worker", issue_key="ask-dispatch-question", problem="Need an owner decision",
            evidence=[{"observed": "blocked"}], impact="Cannot continue safely",
            requested_decision="Choose the next step", return_condition="Decision is recorded",
            request_id="ask-dispatch-ask", asking_schedule_id=asking["schedule_id"])
        answered = fixture.loop.respond_to_issue(project_ref=f.project.ref.to_dict(),
            issue_id=asked["issue_id"], actor="root", authority_source="Owner decision",
            response="Use the bounded repair route", proposed_solution="Repair only this task",
            next_action="Continue the current session", request_id="ask-dispatch-answer")

        request = dict(asking_schedule_id=asking["schedule_id"],
            report_ref=answered["report_ref"], issue_id=asked["issue_id"],
            assignment_ref=assignment.ref.to_dict(), generation=assignment.generation,
            native_session_id="ask-dispatch-session")
        prepared = f.app.continue_from_answer(**request)
        assert prepared["outcome"] == "committed"
        stream = "dispatch:" + assignment.ref.id
        events_before = f.store.list_events(stream=stream)
        calls_before = len(f.provider.calls)
        started = f.app.continue_from_answer(**request, execute=True)
        events_after_start = f.store.list_events(stream=stream)
        assert started["outcome"] in {"succeeded", "replayed", "adoption-required"}
        assert len(f.provider.calls) == calls_before + 1
        new_events = events_after_start[len(events_before):]
        assert len(new_events) == 1
        assert [event.event_type for event in new_events] == ["work.assignment.dispatched"]

        replayed = f.app.continue_from_answer(**request, execute=True)
        assert replayed["schedule_id"] == started["schedule_id"]
        assert len(f.provider.calls) == calls_before + 1
        assert f.store.list_events(stream=stream) == events_after_start
    finally:
        fixture.doCleanups()


def test_service_wait_returns_for_the_matching_real_delivery_event():
    fixture = _fixture()
    try:
        f = fixture.f
        assignment, guide, mandate = f.role_handles("worker", "worker", "ask-wait-session")
        asking = f.app.prepare_role(role="worker", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, mandate_ref=mandate, context_refs=(guide, mandate),
            request_key="ask-wait-occurrence", instruction="Wait for the owner decision.",
            model="gpt-test", reasoning="high", profile="workspace-write",
            native_session_id="ask-wait-session")
        due = f.app._read(asking["schedule_id"])
        f.port.save_due(due.schedule_id, replace(due, stop_state="completed",
            completion_state="succeeded", in_flight_request=None,
            last_completed_request="settle-wait-occurrence").to_dict(), request_id="settle-wait-occurrence",
            expected_version=due.version)
        fixture.server.store = f.store
        prior_lifecycle = f.owner.graph.current(f.task.ref).lifecycle.value
        context = {"role": "worker", "principal": "worker", "project_ref": f.project.ref.to_dict(),
            "task_ref": f.task.ref.to_dict(), "assignment_ref": assignment.ref.to_dict(),
            "generation": assignment.generation,
            "occurrence_ref": {"schedule_id": asking["schedule_id"]},
            "native_session": {"id": "ask-wait-session"}}
        asked = fixture.service.dispatch_bound(context, {"command": "ask", "request_key": "wait-ask",
            "issue_key": "wait-integration-question", "problem": "Need the owner's decision",
            "evidence": [{"observed": "blocked"}], "impact": "Cannot continue safely",
            "requested_decision": "Choose the next step", "return_condition": "Decision is recorded"})
        assert asked["outcome"] == "paused"
        task = f.owner.graph.current(f.task.ref)
        assert task.lifecycle.value == "paused"
        answer = fixture.loop.respond_to_issue(project_ref=f.project.ref.to_dict(),
            issue_id=asked["issue_id"], actor="root", authority_source="Owner decision",
            response="Use the bounded repair route", proposed_solution="Repair only this task",
            next_action="Continue the current session", request_id="wait-integration-answer")
        request = {"command": "wait-for-answer", "issue_id": asked["issue_id"],
            "asking_schedule_id": asking["schedule_id"], "assignment_ref": assignment.ref.to_dict(),
            "generation": assignment.generation, "native_session_id": "ask-wait-session",
            "cursor": asked["cursor"], "timeout_seconds": 0}
        result = fixture.service.dispatch_bound(context, request)
        assert result["outcome"] == "answered"
        assert result["answer_ref"] == answer["report_ref"]
        assert "Use the bounded repair route" not in repr(result)
        assert "answer" not in result
        assert task.lifecycle.value == "paused"
        continuation = {"command": "answer-session-result", "asking_schedule_id": asking["schedule_id"],
            "report_ref": answer["report_ref"], "issue_id": asked["issue_id"],
            "assignment_ref": assignment.ref.to_dict(), "generation": assignment.generation,
            "native_session_id": "ask-wait-session"}
        try:
            fixture.service._answer_session_result({**continuation, "native_session_id": "wrong-session"})
        except PermissionError:
            pass
        else:
            raise AssertionError("callback accepted a different native session")
        assert task.lifecycle.value == "paused"
        # Simulate a new host process: the durable Due is still in flight, but
        # this host has no in-memory execution to attach a completion callback to.
        live = f.app._read(asking["schedule_id"])
        f.port.save_due(live.schedule_id, replace(live, stop_state="active",
            completion_state="none", in_flight_request="native-ask-still-running").to_dict(),
            request_id="mark-asking-native-in-flight", expected_version=live.version)
        assert fixture.host._executions == {}
        started_schedules = []
        original_start = f.app.start
        f.app.start = lambda *, schedule_id: started_schedules.append(schedule_id) or {
            "outcome": "started", "schedule_id": schedule_id}
        try:
            # ExecutionHost.submit retains the exact callback under a stable
            # content hash. Model that owner request file across a process
            # restart; this host's execution table is intentionally empty.
            encoded = json.dumps(continuation, sort_keys=True, separators=(",", ":"))
            token = hashlib.sha256(encoded.encode()).hexdigest()
            retained = fixture.directory / ("request-" + token + ".json")
            retained.parent.mkdir(parents=True, exist_ok=True)
            retained.write_text(json.dumps(continuation))
            pending = fixture.service._answer_session_result(continuation)
            assert pending["outcome"] == "pending"
            assert fixture.host._executions == {}
            assert retained.exists(), "pending callback request was not retained"
            assert json.loads(retained.read_text()) == continuation

            live = f.app._read(asking["schedule_id"])
            f.port.save_due(live.schedule_id, replace(live, stop_state="completed",
                completion_state="succeeded", in_flight_request=None,
                last_completed_request="native-ask-settled").to_dict(),
                request_id="settle-asking-native-after-restart", expected_version=live.version)
            callback = fixture.service._answer_session_result(continuation)
        finally:
            fixture.host.close()
            f.app.start = original_start
        assert callback["outcome"] == "started"
        assert len(started_schedules) == 1
        continued_due = f.app._read(started_schedules[0])
        assert continued_due.target["native_id"] == "ask-wait-session"
        assert continued_due.target["assignment_ref"] == assignment.ref.to_dict()
        assert f.owner.graph.current(f.task.ref).lifecycle.value == prior_lifecycle
        try:
            fixture.service.dispatch_bound(context, {**request, "issue_id": "another-issue"})
        except PermissionError as exc:
            assert "durable asking-session record" in str(exc)
        else:
            raise AssertionError("wait accepted an issue without a durable asking-session record")
    finally:
        fixture.doCleanups()

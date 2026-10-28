## Design on `canon/main`

1. `tests/test_ask_integration.py:75` → add the failing test below. It uses the real ask, answer, continuation, store, and provider fixture.
2. `src/otto/portfolio/execution.py:2043–2048` → delete the answer path’s dispatch comment and `_record_assignment_dispatch(...)` call. Keep the call to `start()` for the prepared occurrence.
3. `src/otto/portfolio/execution.py:1255–1263` → remove the now unused `logical_request_key` override parameter and its conditional branch. Keep the existing launch-request key or `execution-start:<schedule_id>` fallback. The worker start at `:1346` owns the dispatch; `WorkAssignments.dispatch` at `src/herzchen/domains/work/assignments.py:857–868` reuses its receipt on replay.

## Failing test to write first

Add `test_answered_worker_continuation_dispatches_once_and_replay_is_inert` to `tests/test_ask_integration.py`:

```python
def test_answered_worker_continuation_dispatches_once_and_replay_is_inert():
    fixture = _fixture()
    try:
        f = fixture.f
        assignment, guide, mandate = f.role_handles(
            "worker", "worker", "dispatch-ask-session")
        asking = f.app.prepare_role(
            role="worker", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key="dispatch-asking",
            instruction="Wait for the owner decision.",
            model="gpt-test", reasoning="high", profile="read-only",
            native_session_id="dispatch-ask-session")
        assert asking["outcome"] == "committed", asking

        due = f.app._read(asking["schedule_id"])
        f.port.save_due(
            due.schedule_id,
            replace(due, stop_state="completed",
                completion_state="succeeded", in_flight_request=None,
                last_completed_request="dispatch-asking-settled").to_dict(),
            request_id="dispatch-asking-settled",
            expected_version=due.version)

        asked = fixture.loop.ask(
            project_ref=f.project.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(),
            generation=assignment.generation, actor="worker",
            issue_key="dispatch-question", problem="Need an owner decision",
            evidence=[{"observed": "blocked"}],
            impact="Cannot continue safely",
            requested_decision="Choose the next step",
            return_condition="Decision is recorded",
            request_id="dispatch-ask",
            asking_schedule_id=asking["schedule_id"])
        answered = fixture.loop.respond_to_issue(
            project_ref=f.project.ref.to_dict(),
            issue_id=asked["issue_id"], actor="root",
            authority_source="Owner decision",
            response="Use the bounded repair route",
            proposed_solution="Repair only this task",
            next_action="Continue the current session",
            request_id="dispatch-answer")

        stream = "dispatch:" + assignment.id
        before_events = f.store.list_events(stream=stream)
        before_calls = len(f.provider.calls)
        continuation = {
            "asking_schedule_id": asking["schedule_id"],
            "report_ref": answered["report_ref"],
            "issue_id": asked["issue_id"],
            "assignment_ref": assignment.ref.to_dict(),
            "generation": assignment.generation,
            "native_session_id": "dispatch-ask-session",
        }
        started = f.app.continue_from_answer(**continuation, execute=True)
        assert started["outcome"] == "succeeded", started
        assert len(f.provider.calls) == before_calls + 1
        after_events = f.store.list_events(stream=stream)
        assert [event.event_type for event in after_events[len(before_events):]] == [
            "work.assignment.dispatched"]

        replay = f.app.continue_from_answer(**continuation, execute=True)
        assert replay["outcome"] == "replayed", replay
        assert replay["schedule_id"] == started["schedule_id"]
        assert len(f.provider.calls) == before_calls + 1
        assert f.store.list_events(stream=stream) == after_events
    finally:
        fixture.doCleanups()
```

## Deletion and review notes

- **Delete:** the explicit answer dispatch at `execution.py:2043–2047`, including its comment, and the unused key override in `_record_assignment_dispatch`. Add no second dispatch mechanism.
- **Plausible mistake:** retaining the explicit call while relying on the shared start. The answer call uses `answer-session:…:dispatch`; this continuation has no `launch_request`, so worker start uses `execution-start:<schedule_id>`. The test sees two new dispatch events even though it sees one provider call.
- **Existing assertions / D19:** none need to change. The new test adds an assertion. Strengthening the existing broad outcome assertion at `tests/test_ask_integration.py:60` would be a separate D19 decision.
- **Stale or incomplete row details:** the existing journey requests `workspace-write` against a read-only worker mandate and permits `adoption-required`; it does not establish a successful continuation. The new test uses the matching `read-only` profile. Also, `execution.py:1346` dispatches **workers only**, while ask authorization at `manager_journey_service.py:732–735` permits other roles. Deleting the answer call removes those roles’ answer-dispatch event; the row needs an explicit decision on that broader behavior before implementation. No tests were run, as requested.
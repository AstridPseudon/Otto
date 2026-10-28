Design for `canon/main` at `97f5f97`. This is a read-only implementation handoff; I did not edit files or run tests.

### 1. Changes, in order

1. `src/otto/portfolio/issue_loop.py:108` → Resolve a worker-origin question to `current_manager(project)`. Keep manager-origin `operational_help` routed to the orchestrator. Do not route every `ask` to the manager: the authenticated ask entry also admits other roles.
2. `src/otto/portfolio/issue_loop.py:717,735,761` → Select the worker-question purpose only after `_asking_assignment` proves the current assignment, generation, DueRecord, project, task, schedule, and native session. Record `awaiting="manager"` and the selected manager’s assignment and generation in the opening issue. Keep the existing asker tuple at `:776–780` and its issue identity at `:739–742`.
3. `src/otto/portfolio/manager_journey_service.py:1774–1805` → After the durable wait and pause are recorded, submit one retained `manager-help-result` wake keyed to the opening report and the **current manager occurrence**. Return its retained handle. A replay must reuse that handle; ordinary worker progress must never enter this path.
4. `src/otto/portfolio/execution.py:1860–1966` → Extend the existing manager help continuation to accept a worker-question opening report. Before preparing a callback, verify its exact project, current manager assignment/generation, and retained delivery intent. Give the callback question-specific instructions to read and answer the issue. Reuse its deterministic schedule and manager-head fencing; do not create a second wake ledger.
5. `src/otto/portfolio/manager_journey_service.py:928–957,2044–2085` → Let an authenticated **native current manager** use `respond-help` for a worker question. Preserve the separate host-granted orchestrator reply for escalations. Feed either valid response into the existing `answer-session-result` handoff; its DueRecord, wait, report, delivery, and session checks at `:1897–2009` remain mandatory.
6. `src/otto/portfolio/issue_loop.py:827–919` → On response replay, also compare `responding_generation`. Build the asker-bound response delivery once from the immutable opening tuple, so new response and replay cannot diverge.

A manager replacement leaves an old retained wake or answer stale. It must not silently rebind an in-flight manager DueRecord or an asking session. The replacement manager can inspect the open issue and make a fresh, explicitly reconciled response under its current authority.

### 2. Failing test to write first

Add this to `tests/test_ask_session_routing.py` as `test_worker_question_goes_to_its_manager_and_answer_returns_to_its_session`. It first fails on the current root recipient. Follow it with a real host test of the retained wake handle, including replay and routine progress.

```python
def test_worker_question_goes_to_its_manager_and_answer_returns_to_its_session():
    from dataclasses import replace
    from herzchen.domains.work import WorkGraph
    from otto.portfolio.owner_issue_loop import compose_owner_issue_loop
    from tests.test_execution_application import ExecutionApplicationTests

    first = fixture_module.HelpRoutingTests()
    first.setUp()
    second = ExecutionApplicationTests()
    second.setUp()
    try:
        graph = WorkGraph(second.store, actor=second.actor)
        second.project = graph.create_project(
            title="Other project", logical_request_key="other-project")
        second.task = graph.create_task(
            second.project.ref, title="Other task", logical_request_key="other-task")
        second.compose()
        other_manager, _, _ = second.role_handles(
            "manager", "other-manager", "other-manager-session")
        other_loop = compose_owner_issue_loop(
            second.owner.consumer_operations(), second.port)

        f = first.f
        _, guide, _ = f.role_handles("worker", "worker", "seed-worker-session")
        asker, schedule = _task_asker(
            first, session="asking-session", key="own-manager-question", guide=guide)
        fields = dict(
            project_ref=f.project.ref.to_dict(),
            assignment_ref=asker.ref.to_dict(),
            generation=asker.generation,
            actor="worker",
            issue_key="decision",
            problem="Choose the task route",
            evidence=[{"task_ref": f.task.ref.to_dict()}],
            impact="Worker is paused",
            requested_decision="Choose A or B",
            return_condition="A route is recorded",
            request_id="worker-question-1",
            asking_schedule_id=schedule,
        )
        asked = first.loop.ask(**fields)
        assert asked["delivery"]["receipt"]["recipient_assignment_ref"] == (
            first.manager.ref.to_dict())
        assert asked["delivery"]["receipt"]["recipient_assignment_ref"] != (
            other_manager.ref.to_dict())
        assert first.loop.ask(**fields)["issue_id"] == asked["issue_id"]

        openings = [
            r for r in first.readers.reports(f.project.ref.to_dict())
            if r.get("value", {}).get("schema") == "otto.issue.v1"
            and r["value"].get("issue_id") == asked["issue_id"]
        ]
        assert len(openings) == 1
        with pytest.raises(IssueLoopError, match="does not exist"):
            other_loop.respond_to_issue(
                project_ref=second.project.ref.to_dict(),
                issue_id=asked["issue_id"], actor="other-manager",
                authority_source="Other project", response="B",
                proposed_solution="B", next_action="Resume",
                request_id="foreign-answer")

        due = f.app._read(schedule)
        f.port.save_due(
            schedule,
            replace(due, stop_state="completed", completion_state="succeeded",
                    in_flight_request=None).to_dict(),
            request_id="settle-asking-session", expected_version=due.version)
        answer = first.loop.respond_to_issue(
            project_ref=f.project.ref.to_dict(), issue_id=asked["issue_id"],
            actor="manager", authority_source="Current manager decision",
            response="A", proposed_solution="Use A", next_action="Resume",
            request_id="own-manager-answer")
        resumed = f.app.continue_from_answer(
            asking_schedule_id=schedule, report_ref=answer["report_ref"],
            issue_id=asked["issue_id"], assignment_ref=asker.ref.to_dict(),
            generation=asker.generation, native_session_id="asking-session")
        target = f.app._read(resumed["schedule_id"]).target
        assert target["native_id"] == "asking-session"
        assert target["assignment_ref"] == asker.ref.to_dict()
    finally:
        second.doCleanups()
        first.doCleanups()
```

### 3. Delete

Delete the duplicated response-delivery construction at `issue_loop.py:851–859` and `:910–918` when introducing the shared construction. Replace the unconditional worker-ask supervisor route and its `awaiting="orchestrator"` value. Add no project/task keyed answer queue.

### 4. Plausible mistake

A router keyed only by project or task could wake the other project’s manager, or resume a replacement worker session. The test checks the manager assignment, rejects the foreign-project answer, and inspects the resumed DueRecord’s exact assignment and native session. The follow-up host test must also assert one retained manager wake, one answer continuation, and no new wake on ask replay or routine progress.

### 5. Existing expectations needing a D19 decision

Write the decision as: **worker questions are answered by their current project manager; manager `request-help` remains an explicit orchestrator escalation; answer custody stays with the original asker.** Then update the root-responder inputs in `tests/test_ask_session_routing.py:78–100,121–125` and `tests/test_ask_integration.py:39–42,108–111` to manager responses. Adapt the direct service fixture in `test_ask_integration.py:101–105` to observe the retained wake through real owner ingress. Preserve the orchestrator expectations in `tests/test_help_routing.py` and `tests/test_hostctl_serve.py:703–738`. Any changed assertion needs that written D19 decision; the product-method patch at `test_ask_integration.py:141–167` should be removed when that harness is updated.

### 6. Stale row details

`owner_issue_loop.py:82` validates the **orchestrator** assignment; current-manager selection is at `:38–56`. Canon already preserves asker assignment, generation, schedule, and session through response and continuation (`issue_loop.py:776–780,898–917`; `manager_journey_service.py:1897–2009`). The missing behavior is the worker-to-manager opening route and retained manager wake. Current worker asks explicitly open as `awaiting="orchestrator"` at `issue_loop.py:770`.
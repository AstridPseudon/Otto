"""An answer is retained for the precise assignment occurrence that asked."""
import src.otto.portfolio.tests.test_help_routing as fixture_module
import pytest
from otto.portfolio.issue_loop import IssueLoopError


def _task_asker(fixture, *, session, key, guide):
    from herzchen.contracts import ResourceRef
    from tests.test_execution_application import validate_instruction_content

    f = fixture.f
    guide_ref = ResourceRef.from_dict(guide)
    assignment = f.owner.assignments.command_port.assign(f.task.ref, role="worker",
        principal="worker", manager="manager", session=session, pins=[guide_ref],
        logical_request_key=key + ":assignment", actor=f.actor)
    content = f.owner.content.read(guide_ref)["content"]
    assignment = f.owner.assignments.command_port.adopt_resources(assignment.ref,
        resources=[{"resource_ref": guide_ref.to_dict(), "resource_name": content["name"],
                    "content_digest": validate_instruction_content(content), "required": True}],
        expected_revision=assignment.revision, expected_generation=assignment.generation,
        logical_request_key=key + ":adopt", actor=f.actor)
    contract = f.request()["instruction_contract"]
    contract["authority"]["owner_actor"] = "worker"
    contract["read_scope"] = "linked_context"
    contract["allowed_operations"] = ["read_project_context", "return_advice"]
    contract["authority"].pop("effect_profile", None)
    contract["authority"].pop("workspace_roots", None)
    contract["authority"]["permitted_effects"] = ["read_delivered_context", "read_linked_sources", "return_advice"]
    mandate = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager",
        request_id=key + ":mandate", document_id=key + "-mandate", role="mandate",
        content={"role": "worker", "scope_ref": f.project.ref.to_dict(), "status": "active",
            "dispatch_enabled": True, "task_ref": f.task.ref.to_dict(),
            "assignment_ref": assignment.ref.to_dict(), "generation": assignment.generation,
            "brief": {"role": "worker", "mandate": "Return a scoped answer"},
            "instruction_contract": contract})
    mandate_ref = mandate["record"]["payload"]["current_revision"]
    occurrence = f.app.prepare_role(role="worker", project_ref=f.project.ref.to_dict(),
        task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(),
        generation=assignment.generation, mandate_ref=mandate_ref,
        context_refs=(guide_ref.to_dict(), mandate_ref), request_key=key + ":occurrence",
        instruction="Wait for the owner answer.", model="gpt-test", reasoning="high",
        profile="workspace-write", native_session_id=session)
    return assignment, occurrence["schedule_id"]


def test_issue_snapshot_binds_origin_session_and_answer_delivery():
    fixture = fixture_module.HelpRoutingTests()
    fixture.setUp()
    try:
        _, guide, _ = fixture.f.role_handles("worker", "worker", "seed-worker-session")
        asker, asking_schedule = _task_asker(fixture, session="worker-session",
            key="task-scoped-asker", guide=guide)
        requested = fixture.loop.ask(project_ref=fixture.f.project.ref.to_dict(),
            assignment_ref=asker.ref.to_dict(), generation=asker.generation, actor="worker",
            issue_key="question", problem="Need a human decision", evidence=[{"held": True}],
            impact="Task cannot continue", requested_decision="Choose route",
            return_condition="Answer is recorded", request_id="worker-ask",
            asking_schedule_id=asking_schedule)
        opening = next(item["value"] for item in fixture.readers.reports(fixture.f.project.ref.to_dict())
                       if isinstance(item.get("value"), dict)
                       and item["value"].get("schema") == "otto.issue.v1")
        assert opening["asking_assignment_ref"] == asker.ref.to_dict()
        assert opening["asking_generation"] == asker.generation
        assert opening["asking_conversation"] == "worker-session"
        assert opening["asking_schedule_id"] == asking_schedule

        second_asker, second_schedule = _task_asker(fixture, session="second-worker-session",
            key="second-task-scoped-asker", guide=guide)
        second = fixture.loop.ask(project_ref=fixture.f.project.ref.to_dict(),
            assignment_ref=second_asker.ref.to_dict(), generation=second_asker.generation, actor="worker",
            issue_key="question", problem="Need a human decision", evidence=[{"held": True}],
            impact="Task cannot continue", requested_decision="Choose route",
            return_condition="Answer is recorded", request_id="worker-ask-2",
            asking_schedule_id=second_schedule)
        assert second["issue_id"] != requested["issue_id"]

        fixture.host._closing = True
        answered = fixture.loop.respond_to_issue(project_ref=fixture.f.project.ref.to_dict(),
            issue_id=requested["issue_id"], actor="root", authority_source="Owner decision",
            response="Use route A", proposed_solution="Route A", next_action="Resume", request_id="answer-1")
        delivery = next(item["value"] for item in fixture.readers.reports(fixture.f.project.ref.to_dict())
                        if isinstance(item.get("value"), dict)
                        and item["value"].get("schema") == "otto.issue.delivery.v1"
                        and item["value"].get("delivery_id") == answered["delivery"]["delivery_id"])
        assert delivery["recipient_assignment_ref"] == opening["asking_assignment_ref"]
        assert delivery["recipient_generation"] == opening["asking_generation"]
        assert delivery["recipient_conversation"] == opening["asking_conversation"]
        assert delivery["message"]["asking_schedule_id"] == opening["asking_schedule_id"]
        issue_view = fixture.loop.read_issues(project_ref=fixture.f.project.ref.to_dict())["issues"]
        answered_issue = next(item for item in issue_view if item["issue_id"] == requested["issue_id"])
        assert answered_issue["current_owner_ref"] == opening["asking_assignment_ref"]
        recovered = fixture.loop.recover_delivery(project_ref=fixture.f.project.ref.to_dict(),
            delivery_id=answered["delivery"]["delivery_id"])
        assert "supported_application" not in recovered
        report_count = len(fixture.readers.reports(fixture.f.project.ref.to_dict()))
        with pytest.raises(IssueLoopError, match="already has an accepted answer"):
            fixture.loop.respond_to_issue(project_ref=fixture.f.project.ref.to_dict(),
                issue_id=requested["issue_id"], actor="root", authority_source="Second decision",
                response="Use route B", proposed_solution="Route B", next_action="Resume again",
                request_id="answer-2")
        assert len(fixture.readers.reports(fixture.f.project.ref.to_dict())) == report_count
    finally:
        fixture.doCleanups()


def test_answer_rejects_reassigned_asking_generation_and_session():
    fixture = fixture_module.HelpRoutingTests()
    fixture.setUp()
    try:
        _, guide, _ = fixture.f.role_handles("worker", "worker", "seed-stale-worker-session")
        asker, asking_schedule = _task_asker(fixture, session="worker-session",
            key="stale-task-scoped-asker", guide=guide)
        asked = fixture.loop.ask(project_ref=fixture.f.project.ref.to_dict(),
            assignment_ref=asker.ref.to_dict(), generation=asker.generation, actor="worker",
            issue_key="stale-question", problem="Need a decision", evidence=[], impact="Held",
            requested_decision="Choose", return_condition="Resume", request_id="stale-ask",
            asking_schedule_id=asking_schedule)
        fixture.f.owner.assignments.command_port.reassign(asker.ref, principal="worker",
            session="replacement-session", expected_generation=asker.generation,
            logical_request_key="replace-asking-occurrence", actor=fixture.f.actor)
        with pytest.raises(IssueLoopError, match="stale"):
            fixture.loop.respond_to_issue(project_ref=fixture.f.project.ref.to_dict(),
                issue_id=asked["issue_id"], actor="root", authority_source="Owner decision",
                response="Use route A", proposed_solution="Route A", next_action="Resume",
                request_id="answer-stale")
        reports = fixture.readers.reports(fixture.f.project.ref.to_dict())
        assert not any(item.get("value", {}).get("schema") == "otto.issue.response.v1"
                       and item["value"].get("issue_id") == asked["issue_id"] for item in reports)
    finally:
        fixture.doCleanups()

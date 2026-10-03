from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

from otto.portfolio.execution_operations import (
    OccurrencePreparationError,
    build_manager_callback_due,
    prepare_current_assignment_occurrence,
)


REF = {"authority": "owner", "kind": "wrk.assignment", "id": "a", "revision": "rev-2"}
BASE = {**REF, "revision": "rev-1"}


@dataclass(frozen=True)
class Due:
    schedule_id: str = "due-1"
    assignment_ref: dict | None = None
    target: dict | None = None
    execution_mode: str = "continue_existing"
    def to_dict(self): return vars(self)


class Ref:
    def __init__(self, value): self.value = value
    def to_dict(self): return dict(self.value)


class Assignment:
    ref = Ref(REF)
    payload = {"resource_adoption_base_ref": BASE}
    manager = "manager"
    principal = "worker"


class Assignments:
    def get(self, ref): return Assignment()


class Binding:
    def authenticated_actor(self, actor): return type("Actor", (), {"actor": actor})()


class DuePort:
    def __init__(self, fail=False): self.fail = fail
    def save_due(self, schedule, value, **kwargs): return {"version": 1}
    def reconcile_assignment_resources(self, schedule, **kwargs):
        if self.fail: raise RuntimeError("stale current assignment")
        return {"version": 2}


class Tests(unittest.TestCase):
    def due(self): return Due(assignment_ref=BASE, target={"assignment_ref": BASE, "native_id": "session"})

    def test_current_assignment_is_reconciled_from_public_base(self):
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(), assignments=Assignments(), binding=Binding(), due=self.due(),
            assignment_ref=REF, assignment_owner="manager", operation="resume", lifecycle="resume",
            request_key="resume-v1",
        )
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["assignment_base_ref"], BASE)
        self.assertEqual(result["assignment_current_ref"], REF)
        self.assertEqual(result["due_version"], 2)

    def test_partial_success_names_committed_due(self):
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(fail=True), assignments=Assignments(), binding=Binding(), due=self.due(),
            assignment_ref=REF, assignment_owner="manager", operation="resume", lifecycle="resume",
            request_key="resume-v2",
        )
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["stage"], "due_created")
        self.assertEqual(result["schedule_id"], "due-1")

    def test_owner_and_mode_are_rejected_before_write(self):
        with self.assertRaises(OccurrencePreparationError):
            prepare_current_assignment_occurrence(
                due_port=DuePort(), assignments=Assignments(), binding=Binding(),
                due=replace(self.due(), execution_mode="fresh_bounded_worker"), assignment_ref=REF,
                assignment_owner="outsider", operation="resume", lifecycle="resume", request_key="resume-v3",
            )

    def test_settled_manager_builds_same_session_callback(self):
        prior = type("ManagerDue", (), {
            "stop_state": "completed", "completion_state": "succeeded",
            "in_flight_request": None, "delivery_state": "returned",
            "target": {"native_id": "session", "assignment_ref": BASE},
            "last_result": {"physical_session_id": "session"},
        })()
        # dataclasses.replace is the production mechanism; use a real flexible
        # dataclass in this focused fixture.
        @dataclass(frozen=True)
        class ManagerDue:
            schedule_id: str = "old"
            instruction: str = "old"
            anchor: str = "old"
            due_at: str = "old"
            last_covered_slot: int = 1
            invocation_identity: str = "old"
            in_flight_request: str | None = None
            delivery_state: str = "returned"
            assignment_ref: dict | None = None
            target: dict | None = None
            purpose: str = "old"
            host_state: str = "active"
            execution_mode: str = "continue_existing"
            context_refs: tuple = ()
            timeout_seconds: int = 1
            stop_state: str = "completed"
            last_completed_request: str | None = "old"
            last_result: dict | None = None
            delivered_at: str | None = "old"
            delivery_evidence: dict | None = None
            completed_at: str | None = "old"
            completion_state: str = "succeeded"
            completion_evidence: dict | None = None
            host_evidence: dict | None = None
        prior = ManagerDue(target={"native_id": "session"}, last_result={"physical_session_id": "session"})
        result = build_manager_callback_due(
            prior, schedule_id="next", request_key="callback-v1", assignment_ref=REF,
            guide_ref={"id": "guide"}, mandate_ref={"id": "mandate"},
            due_at="2026-10-03T00:00:00Z", timeout_seconds=1200,
        )
        self.assertEqual(result.schedule_id, "next")
        self.assertEqual(result.target["native_id"], "session")
        self.assertEqual(result.in_flight_request, "callback-v1")
        self.assertEqual(result.completion_state, "none")


if __name__ == "__main__": unittest.main()

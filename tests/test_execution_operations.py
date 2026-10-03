from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

from otto.portfolio.execution_operations import OccurrencePreparationError, prepare_current_assignment_occurrence


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


if __name__ == "__main__": unittest.main()

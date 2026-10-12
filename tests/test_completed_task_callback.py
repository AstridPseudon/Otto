import unittest
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from otto.portfolio.compact_reads import compact_read_response


class Receipt:
    def __init__(self, target, result_ref):
        self.status = SimpleNamespace(value="committed")
        self.operation = "work.revise"
        self.target = target
        self.result_ref = result_ref
    def to_dict(self):
        return {"status": self.status.value, "operation": self.operation,
                "target": self.target.to_dict(), "result_ref": self.result_ref.to_dict()}


class Reader:
    def __init__(self, records, receipts=None):
        self.records = records
        self.receipts = receipts or {}
        self.identity_calls = []
        self.bounded_calls = []

    def get_identity(self, ref):
        self.identity_calls.append(ref)
        item = self.records.get((ref.authority, ref.kind, ref.id))
        return item if item is not None and (ref.revision is None or item.ref == ref) else None

    def get_receipt(self, key):
        return self.receipts.get(key)

    def get_identity_bounded(self, ref, *, max_record_bytes=65536):
        self.bounded_calls.append((ref, max_record_bytes))
        item = self.records.get((ref.authority, ref.kind, ref.id))
        return {"record": item if item is not None and item.ref == ref else None,
                "state": "available" if item is not None and item.ref == ref else "missing",
                "bytes_parsed": 1}


class CompletedCallbackTests(unittest.TestCase):
    def setUp(self):
        self.authority = "owner"
        self.project = ResourceRef(self.authority, "work.project", "project", "rev-2")
        self.historical_project = ResourceRef(self.authority, "work.project", "project", "rev-1")
        self.task = ResourceRef(self.authority, "work.task", "task", "rev-2")
        self.historical_task = ResourceRef(self.authority, "work.task", "task", "rev-1")
        self.assignment = ResourceRef(self.authority, "wrk.assignment", "manager", "rev-2")
        self.historical_assignment = ResourceRef(self.authority, "wrk.assignment", "manager", "rev-1")
        self.candidate = ResourceRef(self.authority, "wrk.result", "candidate", "rev-1")
        self.evidence = ResourceRef(self.authority, "dat.content.document", "proof", "rev-1")
        self.gate = ResourceRef(self.authority, "assessment.decision", "gate", "rev-1")
        completion = {"candidate_ref": self.candidate.to_dict(), "result_ref": None,
            "attempt_ref": None, "assignment_ref": self.historical_assignment.to_dict(),
            "project_ref": self.historical_project.to_dict(), "project_revision": "rev-1",
            "task_ref": self.historical_task.to_dict(), "task_revision": "rev-1",
            "generation": 1, "manager": "manager", "logical_request_key": "journey:accepted-replay:finish", "disposition": "accepted",
            "evidence_refs": [self.evidence.to_dict()], "gate_refs": [self.gate.to_dict()],
            "evidence_hashes": {"dat.content.document:proof:rev-1": "a" * 64}}
        task_record = SimpleNamespace(ref=self.task, payload={"lifecycle": "completed", "completion": completion})
        candidate_record = SimpleNamespace(ref=self.candidate, payload={"value": {
            "task_ref": self.historical_task.to_dict(), "project_ref": self.historical_project.to_dict(),
            "assignment_ref": ResourceRef(self.authority, "wrk.assignment", "original-worker", "rev-2").to_dict(),
            "outcome": "succeeded"}})
        gate_record = SimpleNamespace(ref=self.gate, payload={"disposition": "accept", "candidate_ref": self.candidate.to_dict()})
        receipt = Receipt(self.historical_task, self.task)
        project_record = SimpleNamespace(ref=self.project, payload={"lifecycle": "active"})
        reader = Reader({(self.authority, "work.project", "project"): project_record,
                         (self.authority, "work.task", "task"): task_record,
                         (self.authority, "wrk.result", "candidate"): candidate_record,
                         (self.authority, "assessment.decision", "gate"): gate_record},
                        {"journey:accepted-replay:finish": receipt})
        self.reader = reader
        self.owner = SimpleNamespace(graph=SimpleNamespace(reader=reader))
        self.command = ManagerJourneyCommands.__new__(ManagerJourneyCommands)
        self.command.owner = self.owner
        self.command.state = {"task_refs": {"D03": self.task.to_dict()}, "project_ref": self.project.to_dict(),
                              "assignment_ref": self.assignment.to_dict(), "manager_generation": 1,
                              "manager": "manager"}
        self.command._authorize = lambda: "manager"

    def test_completed_review_input_is_bounded_and_acceptance_stays_unknown(self):
        result = self.command.review_input("D03")
        self.assertEqual(result["outcome"], "read")
        self.assertFalse(result["review_eligible"])
        self.assertEqual(result["task_lifecycle"], "completed")
        self.assertEqual(result["completion"]["candidate_ref"], self.candidate.to_dict())
        self.assertEqual(result["completion"]["state"], "recorded")
        self.assertEqual(result["completion"]["historical_acceptance_verification"], "unknown")
        self.assertEqual(result["completion"]["task_ref"], self.historical_task.to_dict())
        self.assertEqual(result["completion"]["current_task_ref"], self.task.to_dict())
        self.assertEqual(result["completion"]["completion_receipt"]["result_ref"], self.task.to_dict())
        self.assertNotIn("unjudged", result.get("acceptance", ""))
        self.assertIn((self.candidate, 8192), self.reader.bounded_calls)
        self.assertNotIn(self.candidate, self.reader.identity_calls)

    def test_new_key_completed_review_refuses_before_effects(self):
        calls = []
        self.command._journal = lambda *args, **kwargs: calls.append((args, kwargs)) or None
        with self.assertRaises(PermissionError):
            self.command.review_task({"command": "review-task", "task": "D03", "request_key": "new-review"})
        self.assertEqual([item[0] for item in calls], [("new-review", "intent"), ("new-review", "review")])
        self.assertTrue(all(item[1] == {"adopted_history": True} for item in calls))

    def test_exact_accepted_replay_uses_adopted_history_and_finishes(self):
        request = {"command": "review-task", "task": "D03", "request_key": "accepted-replay", "finish": True}
        prior = {"request": dict(request), "task_ref": self.historical_task.to_dict(),
                 "assessment_policy_selection": {"source": "trusted-global-policy"},
                 "generation": 1, "assignment_ref": self.historical_assignment.to_dict(),
                 "project_ref": self.historical_project.to_dict()}
        reviewed = {"outcome": "accepted", "candidate_ref": self.candidate.to_dict(),
                    "result_refs": [], "gate_refs": [self.gate.to_dict()],
                    "evidence_refs": [self.evidence.to_dict()],
                    "evidence_hashes": {"dat.content.document:proof:rev-1": "a" * 64}}
        finish_request = {"task": "D03", "request_key": "accepted-replay:finish", "review_key": "accepted-replay"}
        calls = []
        def journal(key, stage, value=None, *, adopted_history=False):
            calls.append((key, stage, adopted_history))
            if key == "accepted-replay" and stage == "intent":
                return prior
            if key == "accepted-replay" and stage == "review":
                return reviewed
            if key == "accepted-replay:finish" and stage == "finish-intent":
                return finish_request
            return None
        self.command._journal = journal
        self.command._review_policy = lambda alias, **kwargs: object()
        self.command._review_policy_pin = lambda alias, policy: prior["assessment_policy_selection"]
        result = self.command.review_task(request)
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["completion"]["outcome"], "replayed")
        self.assertTrue(result["completion"]["replayed"])
        self.assertEqual(result["completion"]["receipt"]["result_ref"], self.task.to_dict())
        self.assertEqual(calls[:2], [("accepted-replay", "intent", True), ("accepted-replay", "review", True)])
        self.assertIn(("accepted-replay:finish", "finish-intent", True), calls)

    def test_nonterminal_task_does_not_enter_completed_projection(self):
        task_record = self.reader.records[(self.authority, "work.task", "task")]
        task_record.payload["lifecycle"] = "active"
        self.command._review_policy = lambda alias: object()
        self.command._review_policy_pin = lambda alias, policy: {}
        self.command._review_criteria = lambda task_ref, policy: {}
        result = self.command.review_input("D03")
        self.assertEqual(result["outcome"], "held")
        self.assertNotEqual(result.get("task_lifecycle"), "completed")
        self.assertNotIn("completion", result)
        task_record.ref = ResourceRef(self.authority, "work.task", "task", "rev-3")
        result = self.command.review_input("D03")
        self.assertEqual(result["outcome"], "held")
        self.assertIsNone(result["task_lifecycle"])
        self.assertEqual(result["completion"]["state"], "unknown")

    def test_compact_projection_preserves_completion_fields(self):
        value = {"outcome": "read", "task": "D03", "task_lifecycle": "completed",
            "review_eligible": False, "candidate_ref": self.candidate.to_dict(),
            "completion": {"state": "recorded", "candidate_ref": self.candidate.to_dict(), "result_ref": None,
                "attempt_ref": None, "gate_refs": [self.gate.to_dict()]}}
        projection = compact_read_response(value, operation="review-input")
        self.assertEqual(projection["projection"]["task_lifecycle"], "completed")
        self.assertFalse(projection["projection"]["review_eligible"])
        self.assertEqual(projection["projection"]["completion"]["candidate_ref"], self.candidate.to_dict())

    def test_foreign_or_corrupt_completion_stays_unknown(self):
        task_record = self.owner.graph.reader.records[(self.authority, "work.task", "task")]
        task_record.payload["completion"]["candidate_ref"] = {
            "authority": "foreign", "kind": "wrk.result", "id": "candidate", "revision": "rev-1"}
        result = self.command.review_input("D03")
        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["completion"]["state"], "unknown")
        task_record.payload["completion"] = {"candidate_ref": "truncated"}
        result = self.command.review_input("D03")
        self.assertEqual(result["completion"]["availability"], "unknown")


if __name__ == "__main__":
    unittest.main()

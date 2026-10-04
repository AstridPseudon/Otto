"""Same prepared callback must retain exact task/assignment mandate scope."""
import unittest
from herzchen.domains.work import WorkGraph
from tests import test_manager_service_continuation as service


class ManagerMandateReconciliationTests(unittest.TestCase):
    reports = service.ManagerServiceContinuationTests.reports

    def setUp(self):
        service.ManagerServiceContinuationTests.setUp(self)
        f = self.fixture
        self.next_task = WorkGraph(f.store, actor=f.actor).create_task(f.project.ref,
            title="Next explicitly selected task", logical_request_key="next-task")
        self.key = "next-owner-intent"
        f.app.assignments.append_report(f.app._read(self.anchor).assignment_ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "NEXT", "task_ref": self.next_task.ref.to_dict(), "continue_requested": True,
             "next_action": "Inspect the next owner task", "logical_request_key": self.key,
             "recorded_at": service.NOW.isoformat()}, expected_generation=1,
            logical_request_key=self.key, actor=f.actor)
        result = self.call()
        self.callback = result["continuation"]["schedule_id"]

    def call(self, operation="prepare", **kwargs):
        f = self.fixture
        return service.manager_continuation_from_command(request={"report_key": self.key,
            "operation": operation, **kwargs}, execution=f.app, anchor_schedule_id=self.anchor,
            current_schedule_id=self.anchor, task_refs={"NEXT": self.next_task.ref.to_dict()},
            native_session_id="manager-session", read_reports=self.reports)

    def test_diagnostic_reads_real_task_mismatch_without_effect_or_due_mutation(self):
        f = self.fixture
        before = f.port.read_due(self.callback)
        result = self.call("mandate-status")
        self.assertEqual(result["outcome"], "read", result)
        self.assertEqual(result["scope_mismatches"]["task_ref"], {
            "actual": f.task.ref.to_dict(), "expected": self.next_task.ref.to_dict()})
        self.assertEqual(result["instruction_contract_scope"]["effect_profile"], "workspace-write-manager")
        self.assertEqual(f.port.read_due(self.callback), before)
        failed = self.call("dispatch")
        self.assertEqual(failed["continuation"]["error"]["message"],
            "execution mandate lacks exact active role task/assignment/generation/dispatch scope", failed)
        self.assertIsNone((f.port.read_due(self.callback).get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__": unittest.main()

"""Explicit continuation checks use the maintained owner and a fake provider."""
from datetime import timedelta
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from otto.portfolio.manager_continuation_command import manager_continuation_from_command
from otto.portfolio.execution_operations import derive_manager_continuation_request, read_project_progress_reports
from tests.test_execution_application import ExecutionApplicationTests, NOW


class ManagerServiceContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExecutionApplicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        assignment, guide, mandate = f.role_handles("manager", "manager", "manager-session")
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="settled-manager",
            instruction="Inspect current project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        first = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(first["outcome"], "succeeded")
        self.anchor = first["schedule_id"]
        self.key = "explicit-pa02-inspection"
        f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "PA02", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "next_action": "Inspect retained PA02 source and its acceptance boundary; do not rerun its worker.",
             "logical_request_key": self.key, "recorded_at": (NOW + timedelta(minutes=1)).isoformat()},
            expected_generation=1, logical_request_key=self.key, actor=f.actor)
        self.provider_calls = len(f.provider.calls)

    def reports(self):
        f = self.fixture
        return read_project_progress_reports(f.store.consumer(), f.project.ref.to_dict())

    def call(self, operation="prepare", current=None):
        f = self.fixture
        return manager_continuation_from_command(
            request={"report_key": self.key, "operation": operation}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=current or self.anchor,
            native_session_id="manager-session", task_refs={"PA02": f.task.ref.to_dict()},
            read_reports=self.reports)

    def test_external_explicit_report_is_consumed_prepare_restart_and_duplicate_without_provider(self):
        f = self.fixture
        self.assertIsNone(derive_manager_continuation_request(f.app._read(self.anchor), self.reports()))
        first = self.call()
        self.assertEqual(first["outcome"], "committed", first)
        identity = first["continuation"]["schedule_id"]
        due = f.port.read_due(identity)
        self.assertEqual(due["target"]["native_id"], "manager-session")
        self.assertEqual(due["target"]["task_ref"], f.task.ref.to_dict())
        self.assertIn("retained PA02", due["instruction"])
        self.assertEqual(due["in_flight_request"], self.key)
        f.compose()
        repeated = self.call()
        self.assertEqual(repeated["continuation"]["schedule_id"], identity)
        self.assertEqual(repeated["outcome"], "prepared")
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        self.assertEqual(self.call("status")["request"]["logical_request_key"], self.key)

    def test_existing_unknown_is_not_replayed_and_blocks_dispatch(self):
        f = self.fixture
        prior = f.app._read(self.anchor)
        unknown = replace(prior, schedule_id="existing-unknown", completion_state="unknown",
            delivery_state="unknown", last_result={"outcome": "unknown", "retry_allowed": False})
        f.port.save_due(unknown.schedule_id, unknown.to_dict(), request_id="fixture-original-unknown", expected_version=0)
        before = f.port.read_due(unknown.schedule_id)
        prepared = self.call(current=unknown.schedule_id)
        self.assertEqual(prepared["outcome"], "committed")
        self.assertTrue(prepared["current_unknown_effect"])
        with patch.object(f.app, "continue_manager", wraps=f.app.continue_manager) as continued:
            held = self.call("dispatch", current=unknown.schedule_id)
        self.assertEqual(held["outcome"], "held")
        continued.assert_not_called()
        self.assertEqual(f.port.read_due(unknown.schedule_id), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_report_key_scope_and_current_task_pin_fence_preparation(self):
        f = self.fixture
        real = self.reports()
        changed = [{**item, "value": {**item["value"], "project_ref": {**f.project.ref.to_dict(), "id": "foreign"}}} for item in real]
        with patch.object(f.app, "continue_manager") as continued:
            result = manager_continuation_from_command(
                request={"report_key": self.key}, execution=f.app, anchor_schedule_id=self.anchor,
                current_schedule_id=self.anchor, native_session_id="manager-session",
                task_refs={"PA02": f.task.ref.to_dict()}, read_reports=lambda: changed)
        self.assertEqual(result["outcome"], "idle")
        continued.assert_not_called()

    def test_roster_only_session_uses_retained_anchor_binding_not_uncreated_callback(self):
        f = self.fixture
        with patch.object(f.app, "_verify_native_binding", wraps=f.app._verify_native_binding) as verify:
            result = self.call()
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(verify.call_args.args[2], self.anchor)


if __name__ == "__main__":
    unittest.main()

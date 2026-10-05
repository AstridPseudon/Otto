"""Explicit continuation checks use the maintained owner and a fake provider."""
from datetime import timedelta
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch
from herzchen.domains.work import Lifecycle

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

    def test_explicit_command_consumes_retained_action_in_same_session_with_fake_provider(self):
        f = self.fixture
        result = self.call("dispatch")
        self.assertEqual(result["outcome"], "succeeded", result)
        identity = result["continuation"]["schedule_id"]
        due = f.port.read_due(identity)
        self.assertEqual(due["last_result"]["physical_session_id"], "manager-session")
        self.assertEqual(due["target"]["task_ref"], f.task.ref.to_dict())
        self.assertEqual(due["assignment_ref"]["id"], f.app._read(self.anchor).assignment_ref["id"])
        self.assertIn("Inspect retained PA02 source", f.provider.calls[-1])
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        f.compose()
        repeated = self.call("dispatch")
        self.assertEqual(repeated["outcome"], "replayed")
        self.assertEqual(repeated["continuation"]["schedule_id"], identity)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

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

    def test_same_prepared_callback_refreshes_project_revision_without_rebinding_task(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        before = f.port.read_due(schedule)
        self.assertIsNone((before.get("host_evidence") or {}).get("gateway_attempt"))
        project = f.owner.graph.set_lifecycle(f.project.ref, Lifecycle.ACTIVE,
            logical_request_key="owner-project-advanced", actor=f.actor)
        self.assertNotEqual(project.ref.to_dict(), before["target"]["project_ref"])
        with patch.object(f.app, "_manager_project_reference", side_effect=lambda due, assignment: due):
            failed = f.app.start(schedule_id=schedule)
        self.assertEqual(failed["outcome"], "partial", failed)
        self.assertEqual(failed["error"]["message"], "project does not match the pinned canonical reference")
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        # This public same-occurrence recovery is the real retry of the previous
        # pre-runtime failure, through canonical briefing and gateway/provider.
        result = f.app.recover(schedule_id=schedule, execute=True)
        self.assertEqual(result["outcome"], "succeeded", result)
        after = f.port.read_due(schedule)
        self.assertEqual(after["target"]["project_ref"], project.ref.to_dict())
        for field in ("task_ref", "reported_task_ref", "mandate_ref", "native_id"):
            self.assertEqual(after["target"][field], before["target"][field])
        self.assertEqual(after["assignment_ref"], before["assignment_ref"])
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["invocation_identity"], before["invocation_identity"])
        reconciliation = after["host_evidence"]["manager_project_reconciliation"]
        self.assertEqual(reconciliation["before_project_ref"], before["target"]["project_ref"])
        self.assertEqual(reconciliation["current_project_ref"], project.ref.to_dict())
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        original = after
        self.assertEqual(f.app.recover(schedule_id=schedule, execute=True)["outcome"], "replayed")
        self.assertEqual(f.port.read_due(schedule), original)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

    def test_project_reconciliation_rejects_foreign_scope_and_never_edits_attempted_due(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        due = f.app._read(schedule)
        assignment = f.app._current(due.assignment_ref, due.generation)
        foreign = replace(due, target={**due.target, "project_ref": {**due.target["project_ref"], "id": "foreign-project"}})
        with self.assertRaisesRegex(ValueError, "current manager scope"):
            f.app._manager_project_reference(foreign, assignment)
        attempted = replace(due, host_evidence={**(due.host_evidence or {}),
            "gateway_attempt": {"state": "attempt", "process_created": False}})
        with patch("otto.portfolio.execution.project_reader") as read:
            self.assertEqual(f.app._manager_project_reference(attempted, assignment), attempted)
            read.assert_not_called()
        self.assertEqual(f.app._read(schedule), due)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_new_bound_callback_is_prepared_with_current_project_revision_without_provider(self):
        f = self.fixture
        project = f.owner.graph.set_lifecycle(f.project.ref, Lifecycle.ACTIVE,
            logical_request_key="project-before-callback", actor=f.actor)
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        due = f.port.read_due(prepared["continuation"]["schedule_id"])
        self.assertEqual(due["target"]["project_ref"], project.ref.to_dict())
        self.assertIn('"report_consumed_by_this_invocation":true', due["message"])
        self.assertIn("do not redispatch that report", due["message"])
        self.assertEqual(due["target"]["task_ref"], f.app._read(self.anchor).target["task_ref"])
        self.assertIsNone((due.get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_completed_task_refresh_never_changes_attempted_callbacks_or_nonmanager_roles(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        due = f.app._read(prepared["continuation"]["schedule_id"])
        assignment = f.app._current(due.assignment_ref, due.generation)
        for retained in (replace(due, role="worker"), replace(due, role="project_advisor"),
                         replace(due, host_evidence={**(due.host_evidence or {}),
                                 "gateway_attempt": {"state": "attempt", "process_created": False}})):
            with patch("otto.portfolio.execution.task_reader") as reader:
                self.assertEqual(f.app._manager_task_reference(retained, assignment), retained)
                reader.assert_not_called()
        self.assertEqual(f.app._read(due.schedule_id), due)

    def test_changed_uncompleted_task_requires_owner_action_without_new_mandate_or_provider(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        before = f.port.read_due(schedule)
        f.owner.graph.set_lifecycle(f.task.ref, Lifecycle.ACTIVE,
            logical_request_key="changed-uncompleted-task", actor=f.actor)
        with patch.object(f.app.portfolio, "create_document", wraps=f.app.portfolio.create_document) as create:
            held = f.app.start(schedule_id=schedule)
        self.assertEqual(held["outcome"], "partial", held)
        self.assertIn("committed completion", held["error"]["message"])
        create.assert_not_called()
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__":
    unittest.main()

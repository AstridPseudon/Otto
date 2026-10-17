"""Same prepared callback must retain exact task/assignment mandate scope."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from herzchen.domains.work import WorkGraph, admission
from herzchen.kernel.store import Store
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
        prior = f.app._read(self.anchor)
        unknown = replace(prior, schedule_id="old-unknown", completion_state="unknown",
            delivery_state="unknown", host_evidence={**dict(prior.host_evidence or {}), "gateway_attempt": {
                "state": "result", "physical_session_id": "manager-session", "process_created": False,
                "result": {"outcome": "unknown", "physical_session_id": "manager-session", "observed_turn_id": None}}},
            last_result={"outcome": "unknown", "physical_session_id": "manager-session",
                         "native_session_created": False, "retry_allowed": False, "delivery_state": "preprovider_unknown"})
        f.port.save_due(unknown.schedule_id, unknown.to_dict(), request_id="old-unknown", expected_version=0)
        self.current = unknown.schedule_id
        self.old = f.port.read_due(self.current)

    def dispose(self):
        pins = self.call("status")["expected_disposition_pins"]
        return self.call("dispose-no-overlap", request_key="owner-no-overlap", **pins)

    def reconcile(self, **changes):
        pins = self.call("status")["expected_task_reconciliation_pins"]
        pins.update(changes)
        return self.call("reconcile-manager-task", request_key="owner-task-reconciliation", **pins)

    def call(self, operation="prepare", **kwargs):
        f = self.fixture
        return service.manager_continuation_from_command(request={"report_key": self.key,
            "operation": operation, **kwargs}, execution=f.app, anchor_schedule_id=self.anchor,
            current_schedule_id=getattr(self, "current", self.anchor), task_refs={"NEXT": self.next_task.ref.to_dict()},
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
        self.assertEqual(self.dispose()["outcome"], "committed")
        failed = self.call("dispatch")
        self.assertEqual(failed["continuation"]["error"]["message"],
            "execution mandate lacks exact active role task/assignment/generation/dispatch scope", failed)
        self.assertIsNone((f.port.read_due(self.callback).get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_manager_task_pin_survives_admission_metadata_but_not_content_edit(self):
        f = self.fixture
        pinned = f.task.ref
        graph = WorkGraph(f.store, actor=f.actor)
        current = graph.current(pinned)
        metadata_revision = graph.revise(current.ref,
            metadata_namespaces={admission.NAMESPACE: {
                "revision": current.revision,
                "digest": admission.content_digest(current.payload),
                "reviewed_digest": admission.reviewed_content_digest(current.payload),
                "basis": admission.BASIS_AUTHORING,
            }}, logical_request_key="manager-pin-admission-metadata", actor=f.actor)
        self.assertTrue(admission.task_content_matches(f.store, pinned, metadata_revision.payload))
        changed = graph.revise(metadata_revision.ref, title="Changed after manager pin",
            logical_request_key="manager-pin-content-edit", actor=f.actor)
        self.assertFalse(admission.task_content_matches(f.store, pinned, changed.payload))

    def test_same_callback_repair_retains_disposition_and_dispatches_once(self):
        f = self.fixture
        original = f.port.read_due(self.callback)
        disposition = self.dispose()
        self.assertEqual(self.call("dispatch")["outcome"], "partial")
        self.assertEqual(f.port.read_due(self.callback), original)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        repaired = self.reconcile()
        self.assertEqual(repaired["outcome"], "committed", repaired)
        after = f.port.read_due(self.callback)
        self.assertEqual(after["target"]["task_ref"], f.task.ref.to_dict())
        self.assertEqual(after["version"], original["version"] + 1)
        receipt = after["host_evidence"]["manager_task_reconciliation"]
        self.assertEqual(receipt["before"], original)
        self.assertEqual(receipt["disposition_ref"], disposition["disposition_ref"])
        self.assertEqual(self.call("mandate-status")["scope_mismatches"], {})
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        f.store.close()
        f.store = Store.open(f.path, authority="execution-owner",
            expected_domains=tuple(sorted(f.domains, key=lambda value: value.domain_id)))
        f.compose()
        self.assertEqual(self.reconcile()["outcome"], "replayed")
        status = self.call("status")
        self.assertFalse(status["dispatch_held_by_current_unknown"], status)
        self.assertEqual(status["no_overlap_disposition_ref"], disposition["disposition_ref"])
        dispatched = self.call("dispatch")
        self.assertEqual(dispatched["outcome"], "succeeded", dispatched)
        self.assertEqual(dispatched["continuation"]["schedule_id"], self.callback)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        self.assertIn("Inspect the next owner task", f.provider.calls[-1])
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(self.call("dispatch")["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

    def test_foreign_or_stale_repair_pins_and_missing_disposition_cannot_mutate(self):
        f = self.fixture
        before = f.port.read_due(self.callback)
        self.assertEqual(self.reconcile()["outcome"], "held")
        self.dispose()
        for field, wrong in {"expected_continuation_version": 99, "expected_manager": "foreign",
                "expected_generation": True, "expected_report_task_ref": f.task.ref.to_dict(),
                "expected_execution_task_ref": self.next_task.ref.to_dict(),
                "expected_mandate_ref": {"id": "foreign"}}.items():
            with self.subTest(field=field):
                result = self.reconcile(**{field: wrong})
                self.assertEqual(result["outcome"], "rejected", result)
        self.assertEqual(f.port.read_due(self.callback), before)
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_later_callback_change_invalidates_retained_disposition(self):
        f = self.fixture
        self.dispose()
        self.assertEqual(self.reconcile()["outcome"], "committed")
        value = f.port.read_due(self.callback)
        value["instruction"] = "changed intent"
        f.port.save_due(self.callback, value, request_id="changed-intent", expected_version=value["version"])
        self.assertTrue(self.call("status")["dispatch_held_by_current_unknown"])
        self.assertEqual(self.call("dispatch")["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_attempted_callback_cannot_be_reconciled(self):
        f = self.fixture
        self.dispose()
        pins = self.call("status")["expected_task_reconciliation_pins"]
        before = f.port.read_due(self.callback)
        before["host_evidence"]["gateway_attempt"] = {"state": "claimed"}
        f.port.save_due(self.callback, before, request_id="claimed-callback", expected_version=before["version"])
        attempted = f.port.read_due(self.callback)
        result = self.call("reconcile-manager-task", request_key="owner-task-reconciliation", **pins)
        self.assertEqual(result["outcome"], "rejected", result)
        self.assertEqual(f.port.read_due(self.callback), attempted)
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_repair_does_not_relax_mandate_authority_or_effect_profile(self):
        f = self.fixture
        self.dispose()
        before = f.port.read_due(self.callback)
        diagnostic = self.call("mandate-status")
        for field, value in (("effect_profile", "workspace-write"), ("owner_actor", "foreign")):
            altered = {**diagnostic, "instruction_contract_scope": {
                **diagnostic["instruction_contract_scope"], field: value}}
            with patch.object(f.app, "inspect_mandate", return_value=altered):
                self.assertEqual(self.reconcile()["outcome"], "rejected")
        self.assertEqual(f.port.read_due(self.callback), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__": unittest.main()

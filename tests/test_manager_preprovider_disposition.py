"""Retained host failure is dispositioned through real Store owner reports."""
import copy
import unittest
from unittest.mock import patch

from herzchen.kernel.store import Store
from tests import test_manager_service_continuation as service
from tests.test_manager_no_overlap_disposition import ManagerNoOverlapDispositionTests as NoOverlap


class ManagerPreproviderDispositionTests(unittest.TestCase):
    reports = service.ManagerServiceContinuationTests.reports
    dispose = NoOverlap.dispose

    def call(self, operation="prepare", current=None, **kwargs):
        f = self.fixture
        return service.manager_continuation_from_command(request={"report_key": self.key,
            "operation": operation, **kwargs}, execution=f.app, anchor_schedule_id=self.anchor,
            current_schedule_id=current or getattr(self, "current", self.anchor),
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session", read_reports=self.reports)

    def setUp(self):
        NoOverlap.setUp(self)
        self.no_overlap = self.dispose()
        self.assertEqual(self.no_overlap["outcome"], "committed")
        f = self.fixture
        adapter = f.app.runtime.adapter
        # The maintained receiving binding fails at the actual recipient trace
        # read; Popen is an executable-boundary tripwire, never a substitute API.
        class FailedRecipientReader:
            def read_with_deadline(self, session_id, deadline):
                raise RuntimeError("app_server_cleanup_failed")
        with patch.object(adapter, "binding_factory", None), patch.object(adapter,
                "trusted_thread_reader", FailedRecipientReader()), \
                patch("herzchen.adapters.host.subprocess.Popen", side_effect=AssertionError("provider reached")) as launch:
            failed = self.call("dispatch")
        launch.assert_not_called()
        self.assertEqual(failed["outcome"], "unknown", failed)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        self.failed = f.port.read_due(self.callback)
        self.assertEqual(f.port.read_due(self.current), self.old)

    def disposition(self, **changes):
        status = self.call("preprovider-status")
        self.assertEqual(status["outcome"], "read", status)
        request = {**status["expected_preprovider_disposition_pins"], "request_key": "owner-preprovider",
                   "disposition": "root-host-recovery", **changes}
        return self.call("dispose-preprovider", **request)

    def test_authentic_append_preserves_both_unknowns_and_global_dispatch_guard(self):
        f = self.fixture
        before_reports = self.reports()
        result = self.disposition()
        self.assertEqual(result["outcome"], "committed", result)
        self.assertFalse(result["dispatch_authorized"])
        self.assertFalse(result["same_callback_replay_allowed"])
        self.assertTrue(result["new_owner_report_key_required"])
        rows = self.reports()
        self.assertEqual(len(rows), len(before_reports) + 1)
        report = next(row for row in rows if row["ref"] == result["disposition_ref"])
        self.assertEqual(report["value"]["schema"], "otto.manager-preprovider-disposition.v1")
        self.assertEqual(f.port.read_due(self.callback), self.failed)
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertTrue(any(row["ref"] == self.no_overlap["disposition_ref"] for row in rows))
        self.assertEqual(self.call("dispatch")["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_duplicate_restarts_and_changed_input_rejects(self):
        f = self.fixture
        first = self.disposition()
        f.store.close()
        f.store = Store.open(f.path, authority="execution-owner",
            expected_domains=tuple(sorted(f.domains, key=lambda value: value.domain_id)))
        f.compose()
        replay = self.disposition()
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(replay["disposition_ref"], first["disposition_ref"])
        self.assertEqual(self.call("preprovider-status")["retained_disposition_refs"], [first["disposition_ref"]])
        changed = self.disposition(disposition="fresh-explicit-manager-continuation", new_report_key="fresh-owner-intent")
        self.assertEqual(changed["outcome"], "rejected")
        self.assertEqual(changed["error"]["code"], "input_changed")
        self.assertEqual(f.port.read_due(self.callback), self.failed)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_every_exact_pin_is_required_and_type_sensitive(self):
        f = self.fixture
        status = self.call("preprovider-status")
        self.assertEqual(status["outcome"], "read", status)
        before = self.reports()
        for field, value in status["expected_preprovider_disposition_pins"].items():
            wrong = False if isinstance(value, int) else {} if isinstance(value, dict) else "foreign"
            with self.subTest(field=field):
                result = self.disposition(**{field: wrong})
                self.assertEqual(result["outcome"], "rejected", result)
                self.assertEqual(result["error"]["field"], field)
        self.assertEqual(self.reports(), before)
        self.assertEqual(f.port.read_due(self.callback), self.failed)

    def test_fresh_disposition_requires_new_report_without_creating_callback(self):
        f = self.fixture
        before_due = f.port.list_due()
        for key in (None, self.key, "owner-preprovider", "  new  "):
            self.assertEqual(self.disposition(disposition="fresh-explicit-manager-continuation",
                new_report_key=key)["outcome"], "rejected")
        result = self.disposition(disposition="fresh-explicit-manager-continuation", new_report_key="fresh-owner-intent")
        self.assertEqual(result["outcome"], "committed", result)
        self.assertEqual(result["new_report_key"], "fresh-owner-intent")
        self.assertFalse(result["dispatch_authorized"])
        self.assertEqual(f.port.list_due(), before_due)
        # The old report is never reused, and a new report has no implicit grant.
        self.assertEqual(self.call("dispatch")["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_stale_valid_readback_does_not_reuse_disposition_pins(self):
        f = self.fixture
        pins = self.call("preprovider-status")["expected_preprovider_disposition_pins"]
        before = self.reports()
        f.port.save_due(self.callback, self.failed, request_id="later-readback", expected_version=self.failed["version"])
        result = self.call("dispose-preprovider", request_key="owner-preprovider",
                           disposition="root-host-recovery", **pins)
        self.assertEqual(result["outcome"], "rejected", result)
        self.assertEqual(result["error"]["field"], "expected_continuation_version")
        self.assertEqual(self.reports(), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_missing_or_positive_transport_evidence_is_never_dispositioned(self):
        f = self.fixture
        mutations = [
            lambda a: a.update(process_created=True),
            lambda a: a.update(delivery_admission={"native_turn_started": True}),
            lambda a: a["result"].update(observed_turn_id="a-turn"),
            lambda a: a["result"]["raw_result"]["work_receipt"].update(process_id="123"),
            lambda a: a["result"]["raw_result"]["work_receipt"].pop("process_id"),
            lambda a: a["result"]["raw_result"]["work_envelope"].update(unsupported_error="other"),
            lambda a: a["result"]["raw_result"]["work_envelope"].update(reconciliation="other"),
            lambda a: a["result"]["raw_result"].update(worker_content=["effect"]),
            lambda a: a["result"]["raw_result"].update(provider_called=True),
        ]
        before_reports = self.reports()
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(self.failed)
            mutate(value["host_evidence"]["gateway_attempt"])
            current = f.port.read_due(self.callback)
            f.port.save_due(self.callback, value, request_id="altered-evidence-" + str(index), expected_version=current["version"])
            with self.subTest(index=index):
                self.assertEqual(self.call("preprovider-status")["outcome"], "rejected")
        self.assertEqual(self.reports(), before_reports)
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__": unittest.main()

"""Scoped owner disposition uses real temporary Store and maintained continuation."""
from dataclasses import replace
from unittest.mock import patch
import unittest

from herzchen.kernel.store import Store
from tests import test_manager_service_continuation as service


class ManagerNoOverlapDispositionTests(unittest.TestCase):
    reports = service.ManagerServiceContinuationTests.reports
    call = service.ManagerServiceContinuationTests.call

    def setUp(self):
        service.ManagerServiceContinuationTests.setUp(self)
        f = self.fixture
        prior = f.app._read(self.anchor)
        unknown = replace(prior, schedule_id="retained-unknown", completion_state="unknown",
            delivery_state="unknown", host_evidence={**dict(prior.host_evidence or {}), "gateway_attempt": {"state": "result",
                "physical_session_id": "manager-session", "process_created": False,
                "result": {"outcome": "unknown", "physical_session_id": "manager-session",
                           "observed_turn_id": None}}},
            last_result={"outcome": "unknown", "physical_session_id": "manager-session",
                         "native_session_created": False, "retry_allowed": False, "delivery_state": "preprovider_unknown"})
        f.port.save_due(unknown.schedule_id, unknown.to_dict(), request_id="retained-unknown-create", expected_version=0)
        self.current = unknown.schedule_id
        self.prepared = self.call(current=self.current)
        self.callback = self.prepared["continuation"]["schedule_id"]
        self.old = f.port.read_due(self.current)
        self.new = f.port.read_due(self.callback)

    def dispose(self, **changes):
        request = {"report_key": self.key, "operation": "dispose-no-overlap", "request_key": "owner-no-overlap",
            "expected_current_schedule_id": self.current, "expected_current_version": self.old["version"],
            "expected_continuation_schedule_id": self.callback, "expected_continuation_version": self.new["version"],
            "expected_project_id": self.fixture.project.id, "expected_manager": "manager", "expected_generation": 1,
            "expected_native_session_id": "manager-session",
            "expected_latest_turn_id": self.prepared["request"]["settled_turn_id"]}
        request.update(changes)
        f = self.fixture
        return service.manager_continuation_from_command(request=request, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.current,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session", read_reports=self.reports)

    def test_separate_controller_owner_and_manager_principal_are_exactly_scoped(self):
        f = self.fixture
        for sid in (self.anchor, self.current, self.callback):
            value = f.port.read_due(sid)
            value.update(lifecycle_owner="controller-owner", manager_ref="controller-owner")
            f.port.save_due(sid, value, request_id="controller-owner:" + sid, expected_version=value["version"])
        self.old, self.new = f.port.read_due(self.current), f.port.read_due(self.callback)
        with patch.object(f.app, "actor", "controller-owner"):
            result = self.dispose()
            self.assertEqual(result["outcome"], "committed", result)
            self.assertEqual(result["scope"]["owner_actor"], "controller-owner")
            self.assertEqual(result["scope"]["manager_principal"], "manager")
            self.assertFalse(self.call("status", current=self.current)["dispatch_held_by_current_unknown"])
            with patch.object(f.app, "manager_actor", "foreign"):
                self.assertEqual(self.dispose()["outcome"], "rejected")
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_status_exposes_exact_read_only_owner_pins_before_disposition(self):
        before = self.reports()
        result = self.call("status", current=self.current)
        self.assertEqual(result["outcome"], "read")
        self.assertTrue(result["dispatch_held_by_current_unknown"])
        self.assertEqual(result["expected_disposition_pins"]["expected_current_version"], self.old["version"])
        self.assertEqual(result["expected_disposition_pins"]["expected_continuation_version"], self.new["version"])
        self.assertEqual(result["expected_disposition_pins"]["expected_manager"], "manager")
        self.assertEqual(self.reports(), before)
        self.dispose()
        self.assertFalse(self.call("status", current=self.current)["dispatch_held_by_current_unknown"])

    def test_scoped_commit_admits_same_report_and_preserves_historical_unknown(self):
        f = self.fixture
        self.assertEqual(self.call("dispatch", current=self.current)["outcome"], "held")
        result = self.dispose()
        self.assertEqual(result["outcome"], "committed", result)
        self.assertFalse(result["provider_called"])
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(f.port.read_due(self.callback), self.new)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        dispatched = self.call("dispatch", current=self.current)
        self.assertEqual(dispatched["outcome"], "succeeded", dispatched)
        self.assertEqual(dispatched["continuation"]["schedule_id"], self.callback)
        self.assertEqual(dispatched["no_overlap_disposition_ref"], result["disposition_ref"])
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        repeated = self.call("dispatch", current=self.current)
        self.assertEqual(repeated["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

    def test_foreign_and_stale_expected_pins_reject_without_mutation(self):
        before = self.reports()
        fields = {"expected_current_schedule_id": "foreign", "expected_current_version": 99,
            "expected_continuation_schedule_id": "foreign", "expected_continuation_version": 99,
            "expected_project_id": "foreign", "expected_manager": "foreign", "expected_generation": 99,
            "expected_native_session_id": "foreign", "expected_latest_turn_id": "foreign"}
        for field, value in fields.items():
            with self.subTest(field=field):
                result = self.dispose(**{field: value})
                self.assertEqual(result["outcome"], "rejected", result)
                self.assertEqual(result["error"]["code"], "stale_or_foreign_disposition")
                self.assertEqual(self.reports(), before)
        with patch.object(self.fixture.app, "actor", "foreign"):
            self.assertEqual(self.dispose()["outcome"], "rejected")
        self.assertEqual(self.fixture.port.read_due(self.current), self.old)

    def test_absent_or_positive_native_effect_evidence_rejects(self):
        f = self.fixture
        for index, (process, native) in enumerate([(None, False), (True, False), (False, None), (False, True)]):
            value = f.port.read_due(self.current)
            value["host_evidence"]["gateway_attempt"]["process_created"] = process
            value["last_result"]["native_session_created"] = native
            f.port.save_due(self.current, value, request_id="changed-evidence-" + str(index), expected_version=value["version"])
            result = self.dispose(expected_current_version=f.port.read_due(self.current)["version"])
            self.assertEqual(result["outcome"], "rejected", result)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_false_creation_flags_do_not_authorize_an_uncertain_existing_session_turn(self):
        f = self.fixture
        value = f.port.read_due(self.current)
        value["last_result"]["delivery_state"] = "unknown"
        f.port.save_due(self.current, value, request_id="uncertain-existing-turn", expected_version=value["version"])
        result = self.dispose(expected_current_version=f.port.read_due(self.current)["version"])
        self.assertEqual(result["outcome"], "rejected", result)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_duplicate_survives_store_restart_and_changed_request_input_rejects(self):
        f = self.fixture
        first = self.dispose()
        self.assertEqual(first["outcome"], "committed", first)
        f.store.close()
        f.store = Store.open(f.path, authority="execution-owner", expected_domains=tuple(sorted(f.domains, key=lambda value: value.domain_id)))
        f.compose()
        replay = self.dispose()
        self.assertEqual(replay["outcome"], "replayed", replay)
        self.assertEqual(replay["disposition_ref"], first["disposition_ref"])
        self.assertEqual(f.port.read_due(self.current), self.old)
        self.assertEqual(len([row for row in self.reports() if row["value"].get("schema") == "otto.manager-no-overlap-disposition.v1"]), 1)
        self.assertEqual(self.dispose(expected_manager="foreign")["outcome"], "rejected")

    def test_new_readback_invalidates_committed_disposition_and_keeps_global_guard(self):
        f = self.fixture
        self.assertEqual(self.dispose()["outcome"], "committed")
        value = f.port.read_due(self.current)
        f.port.save_due(self.current, value, request_id="new-owner-readback-version", expected_version=value["version"])
        self.assertEqual(self.call("dispatch", current=self.current)["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_disposition_does_not_authorize_another_explicit_report(self):
        f = self.fixture
        self.assertEqual(self.dispose()["outcome"], "committed")
        report = next(row["value"] for row in self.reports() if row["value"].get("logical_request_key") == self.key)
        other = "another-owner-intent"
        f.app.assignments.append_report(f.app._read(self.anchor).assignment_ref,
            {**report, "logical_request_key": other}, expected_generation=1,
            logical_request_key=other, actor=f.actor)
        self.key = other
        self.call(current=self.current)
        self.assertEqual(self.call("dispatch", current=self.current)["outcome"], "held")
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__":
    unittest.main()

"""Real disposable owner; metadata-only current slots, not new authority."""
from copy import deepcopy
from dataclasses import replace
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.execution_host import _atomic_json
from otto.portfolio.manager_journey_client import add_manager_journey_parsers, requires_native_caller, command_result_summary, read_command_status
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.retained_projection import projection, read_projection, write_preparation_checkpoint
from otto.portfolio.worker_readiness import read_worker_readiness
from tests import test_execution_application as owner_fixture


class WorkerReadinessTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        prepared = self.f.app.assign_worker(**self.f.request())
        manager, _, _ = self.f.role_handles("manager", "manager", "manager-session")
        self.schedule = prepared["schedule_id"]
        self.state = {"project_ref": self.f.project.ref.to_dict(), "assignment_ref": manager.ref.to_dict(),
            "manager": "manager", "manager_generation": manager.generation,
            "task_refs": {"T1": self.f.task.ref.to_dict()}, "workers": {"T1": {
                "schedule_id": self.schedule, "assignment_ref": prepared["assignment_ref"],
                "principal": "worker", "generation": 1}}}
        self.service = object.__new__(ManagerJourneyService)
        self.service.server = SimpleNamespace(state=self.state, store=self.f.store)
        self.service.host = SimpleNamespace(bounded_transports=True)
        self.service.commands = ManagerJourneyCommands(owner=self.f.owner, portfolio=self.f.app.portfolio,
            state=self.state)

    def read(self):
        return read_worker_readiness(self.service, {"command": "worker-readiness"})

    def test_current_own_metadata_parity_no_recovery_history_provider_or_budget_mutation(self):
        before = self.f.store.consumer().snapshot_counts()
        due = self.f.port.read_due(self.schedule)
        # The explicit reader must not use a broad inventory or hydrate Due bodies.
        with patch.object(type(self.f.port), "read_due", side_effect=AssertionError("no recovery")), \
             patch.object(type(self.f.store.consumer()), "list_events", side_effect=AssertionError("no history")):
            result = self.read()
        row = result["current_worker_slots"][0]
        for key in ("stop_state", "completion_state", "host_state", "in_flight_request"):
            self.assertEqual(row[key], due[key])
        self.assertEqual(row["assignment_ref"], self.state["workers"]["T1"]["assignment_ref"])
        self.assertTrue(result["coverage"]["complete"])
        self.assertIn("not other projects", result["coverage"]["basis"])
        self.assertIsNone(result["ordinary_normal_allowance"]["remaining"])
        self.assertEqual(result["named_due_pool_snapshots"], [])
        self.assertEqual(self.f.store.consumer().snapshot_counts(), before)
        self.assertEqual(self.f.provider.calls, [])
        self.assertFalse(result["provider_called"])

    def test_named_due_pool_exact_metadata_balance_unavailable_no_history_or_substitution(self):
        limits = LimitService(self.f.store)
        ref = ResourceRef(self.f.actor.authority, "limit", "explicit-worker-pool")
        expected = limits.create_pool(ref, capacity_units=2, cumulative_allowance_units=3,
            logical_request_key="pool", actor=self.f.actor)
        due = self.f.app._read(self.schedule)
        self.f.port.save_due(self.schedule, replace(due, allowance_ref=ref.to_dict()).to_dict(),
            request_id="bind-pool", expected_version=due.version)
        before = self.f.store.consumer().snapshot_counts()
        result = self.read(); pool = result["named_due_pool_snapshots"][0]
        self.assertEqual(pool["pool_ref"], ref.to_dict())
        for key in ("version", "capacity_units", "cumulative_allowance_units"):
            self.assertEqual(pool[key], getattr(expected, key))
        for key in ("held_units", "used_units", "remaining_allowance_units"):
            self.assertIsNone(pool[key])
        self.assertIsNone(result["ordinary_normal_allowance"]["remaining"])
        self.assertEqual(self.f.store.consumer().snapshot_counts(), before)

    def test_prepared_inflight_unknown_and_failed_slots_never_claim_clear_native_custody(self):
        cases = (("active", "none", None), ("active", "none", "intent"),
                 ("stopped", "unknown", None), ("stopped", "failed", None),
                 ("completed", "succeeded", "still-in-flight"))
        for index, (stop, completion, inflight) in enumerate(cases):
            due = self.f.app._read(self.schedule)
            self.f.port.save_due(self.schedule, replace(due, stop_state=stop, completion_state=completion,
                in_flight_request=inflight).to_dict(), request_id="case-" + str(index), expected_version=due.version)
            row = self.read()["current_worker_slots"][0]
            self.assertTrue(row["active_or_uncertain"])
            self.assertEqual(row["native_liveness"], "not established by this metadata read")
            self.assertEqual(row["custody_release"], "not evaluated by this metadata read")
        self.assertEqual(self.f.provider.calls, [])

    def test_inventory_boundary_and_summary_no_hidden_roster_clipping(self):
        self.state["workers"] = {"T" + str(i): {"schedule_id": "missing-" + str(i),
            "assignment_ref": self.state["workers"]["T1"]["assignment_ref"], "principal": "worker", "generation": 1}
            for i in range(32)}
        self.state["task_refs"] = {key: self.f.task.ref.to_dict() for key in self.state["workers"]}
        result = self.read()
        self.assertEqual(len(result["current_worker_slots"]), 32)
        self.assertIsNone(result["active_or_uncertain_current_slots"])
        self.state["workers"]["T32"] = self.state["workers"]["T0"]
        with self.assertRaises(ValueError): self.read()
        result["current_worker_slots"][0]["detail"] = "x" * 60000
        summary = command_result_summary(result)
        self.assertIn("detail-required", summary["readiness_availability"])
        self.assertNotIn("current_worker_slots", summary)

    def test_stale_manager_foreign_selector_and_slot_rejected(self):
        original = deepcopy(self.state)
        cases = [lambda: self.state.update(manager_generation=99),
                 lambda: self.state["workers"]["T1"].update(generation=99),
                 lambda: self.state["workers"]["T1"]["assignment_ref"].update(authority="foreign"),
                 lambda: self.state["workers"]["T1"]["assignment_ref"].update(revision="rev-1"),
                 lambda: self.state["task_refs"]["T1"].update(id="foreign-task")]
        for mutate in cases:
            self.state.clear(); self.state.update(deepcopy(original)); mutate()
            with self.assertRaises(PermissionError): self.read()
        self.state.clear(); self.state.update(original)
        with self.assertRaises(ValueError): read_worker_readiness(self.service,
            {"command": "worker-readiness", "project_ref": self.f.project.ref.to_dict()})
        self.assertEqual(self.f.provider.calls, [])

    def test_missing_or_oversize_metadata_explicit_unknown_not_zero(self):
        self.state["workers"]["T1"]["schedule_id"] = "missing"
        result = self.read()
        self.assertFalse(result["coverage"]["complete"])
        self.assertIsNone(result["active_or_uncertain_current_slots"])
        self.assertEqual(result["current_worker_slots"][0]["metadata_state"], "missing")
        self.state["workers"]["T1"]["schedule_id"] = self.schedule
        due = self.f.app._read(self.schedule)
        self.f.port.save_due(self.schedule, replace(due, host_evidence={"large": "x" * 40000}).to_dict(),
            request_id="large", expected_version=due.version)
        result = self.read()
        self.assertFalse(result["coverage"]["complete"])
        self.assertIsNone(result["active_or_uncertain_current_slots"])
        self.assertEqual(result["current_worker_slots"][0]["metadata_state"], "detail-required")
        self.assertEqual(result["current_worker_slots"][0]["metadata_bytes_parsed"], 0)

    def test_task_revision_advance_and_generic_host_unknown_do_not_invent_identity_hold(self):
        self.state["task_refs"]["T1"]["revision"] = "rev-2"
        due = self.f.app._read(self.schedule)
        self.f.port.save_due(self.schedule, replace(due, stop_state="completed", completion_state="succeeded",
            host_state="unknown", in_flight_request=None).to_dict(), request_id="completed", expected_version=due.version)
        result = self.read(); row = result["current_worker_slots"][0]
        self.assertFalse(row["active_or_uncertain"])
        self.assertEqual(row["host_state"], "unknown")
        self.assertIn("not itself", row["state_semantics"])
        self.assertNotEqual(row["target_task_ref"], row["current_task_ref"])

    def test_foreign_missing_and_stale_pool_are_explicit_not_normal_allowance(self):
        due = self.f.app._read(self.schedule)
        foreign = ResourceRef("foreign", "limit", "pool")
        self.f.port.save_due(self.schedule, replace(due, allowance_ref=foreign.to_dict()).to_dict(),
            request_id="foreign-pool", expected_version=due.version)
        with self.assertRaises(PermissionError): self.read()
        due = self.f.app._read(self.schedule)
        missing = ResourceRef(self.f.actor.authority, "limit", "missing")
        self.f.port.save_due(self.schedule, replace(due, allowance_ref=missing.to_dict()).to_dict(),
            request_id="missing-pool", expected_version=due.version)
        self.assertEqual(self.read()["named_due_pool_snapshots"][0]["availability"], "missing")
        ref = ResourceRef(self.f.actor.authority, "limit", "existing")
        LimitService(self.f.store).create_pool(ref, capacity_units=1, cumulative_allowance_units=1,
            logical_request_key="existing", actor=self.f.actor)
        due = self.f.app._read(self.schedule)
        self.f.port.save_due(self.schedule, replace(due, allowance_ref={**ref.to_dict(), "revision": "rev-99"}).to_dict(),
            request_id="stale-pool", expected_version=due.version)
        with self.assertRaises(PermissionError): self.read()

    def test_cli_is_native_bound_finite_read(self):
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest="command", required=True))
        self.assertEqual(vars(parser.parse_args(["worker-readiness"])), {"command": "worker-readiness"})
        self.assertTrue(requires_native_caller("worker-readiness"))
        context = {"role": "manager", "principal": "manager", "assignment_ref": self.state["assignment_ref"],
                   "generation": 1, "project_ref": self.state["project_ref"]}
        result = self.service.dispatch_bound(context, {"command": "worker-readiness"})
        self.assertEqual(command_result_summary(result)["coverage"], result["coverage"])
        for changed in ({"principal": "foreign"}, {"generation": 99},
                        {"project_ref": {**self.state["project_ref"], "id": "foreign"}}):
            with self.assertRaises(PermissionError): self.service.dispatch_bound({**context, **changed}, {"command": "worker-readiness"})


class TerminalProjectionOverflowTests(unittest.TestCase):
    def test_exact_raw_unknown_and_outcome_survive_optional_summary_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            for token, outcome in (("a" * 32, "unknown"), ("b" * 32, "ok")):
                path = Path(tmp) / ("response-" + token + ".json")
                value = {"outcome": outcome, "retry": False, "provider_called": False,
                    "handoff": {"effective_context": {"instructions": "x" * 100000}}}
                _atomic_json(path, value)
                raw = path.read_bytes()
                self.assertEqual(json.loads(raw), value)
                status = read_projection(path.with_name("status-" + path.name),
                    expected_binding={"request_id": token})
                self.assertEqual(status["artifact"]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(status["artifact"]["byte_length"], len(raw))
                self.assertEqual(status["summary"]["outcome"], outcome)
                self.assertFalse(status["summary"]["provider_called"])
                self.assertTrue(status["summary_availability"]["full_response_preserved"])
                self.assertEqual(status["io_work"]["payload_bytes_read"], 0)
                recovered = read_command_status(tmp, token)
                self.assertEqual(recovered["outcome"], outcome)
                self.assertEqual(recovered["summary_availability"]["state"], "detail-required")
                with self.assertRaises(PermissionError): read_projection(path.with_name("status-" + path.name),
                    expected_binding={"request_id": "foreign"})

    def test_preparation_and_default_projection_guards_remain_strict(self):
        with self.assertRaises(ValueError): projection({}, artifact={}, binding={}, summary={"large": "x" * 70000})
        # Preparation never opts into the terminal fallback. Force the exact
        # bound failure to verify call policy while original detail remains.
        with tempfile.TemporaryDirectory() as tmp, patch("otto.portfolio.retained_projection.MAX_PROJECTION_BYTES", 100):
            with self.assertRaises(ValueError): write_preparation_checkpoint(Path(tmp) / "checkpoint.json",
                {"outcome": "prepared"}, binding={"assignment_ref": "original", "generation": 1})
            self.assertFalse((Path(tmp) / "checkpoint.json").exists())
            self.assertTrue((Path(tmp) / "checkpoint.detail.json").exists())

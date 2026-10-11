"""Returned terminal handle follows the strict real Due reader unchanged."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from otto.portfolio.execution_host import _atomic_json
from otto.portfolio.manager_journey_client import command_result_summary, read_command_status
from otto.portfolio.occurrence_reads import exact_due, handle
from otto.portfolio.retained_projection import finite_summary
from tests import test_execution_application as fixture


class ExactOccurrenceSummaryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ExecutionApplicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.prepared = self.f.app.assign_worker(**self.f.request())
        self.schedule = self.prepared["schedule_id"]

    def summaries(self, occurrence):
        raw = {"outcome": "admitted", "provider_called": False, "occurrence": occurrence}
        yield command_result_summary(raw)
        yield finite_summary(raw)
        with tempfile.TemporaryDirectory() as tmp:
            token = "a" * 32
            _atomic_json(Path(tmp) / ("response-" + token + ".json"), raw)
            yield read_command_status(tmp, token)["summary"]

    def test_full_returned_summary_follows_same_real_occurrence_with_null_parent_no_effect(self):
        original = handle(self.f.port.read_due(self.schedule))
        counts = self.f.store.consumer().snapshot_counts()
        for summary in self.summaries(original):
            self.assertEqual(summary["occurrence"], original)
            self.assertIn("parent", summary["occurrence"])
            self.assertIsNone(summary["occurrence"]["parent"])
            self.assertEqual(exact_due(self.f.port, summary["occurrence"])["schedule_id"], self.schedule)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        self.assertEqual(self.f.provider.calls, [])

    def test_parent_join_preserved_completely_and_foreign_stale_handles_still_reject(self):
        parent = {"assignment_ref": self.prepared["assignment_ref"], "generation": 1,
                  "occurrence_ref": {"schedule_id": self.schedule},
                  "result_destination": {"assignment_ref": self.prepared["assignment_ref"],
                       "generation": 1, "schedule_id": self.schedule, "native_session_id": None}}
        request = self.f.request(); request.update(parent=parent, request_key="child-worker", principal="child")
        prepared = self.f.app.assign_worker(**request)
        original = handle(self.f.port.read_due(prepared["schedule_id"]))
        for summary in self.summaries(original):
            self.assertEqual(summary["occurrence"], original)
            exact_due(self.f.port, summary["occurrence"])
        for changed in ({"generation": 99}, {"assignment_ref": {**original["assignment_ref"], "revision": "rev-1"}},
                        {"project_ref": {**original["project_ref"], "id": "foreign"}}, {"parent": None}):
            candidate = {**deepcopy(original), **changed}
            for summary in self.summaries(candidate):
                with self.assertRaises(PermissionError): exact_due(self.f.port, summary["occurrence"])
        missing = deepcopy(original); missing.pop("parent")
        with self.assertRaises(ValueError): exact_due(self.f.port, missing)
        self.assertEqual(self.f.provider.calls, [])

    def test_overbound_handle_explicit_detail_required_not_partial_or_false_null_parent(self):
        original = handle(self.f.port.read_due(self.schedule))
        original["parent"] = {"provenance": "x" * 17000}
        for summary in self.summaries(original):
            self.assertNotIn("occurrence", summary)
            self.assertIn("detail-required", summary["occurrence_availability"])
        self.assertEqual(original["parent"]["provenance"], "x" * 17000)

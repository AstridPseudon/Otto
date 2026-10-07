"""Measured status readers preserve attribution without hydrating unrelated events."""
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work import WorkGraph
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.owner_issue_loop import OwnerIssueReaders
from tests import test_execution_application as owner_fixture


class StatusReadTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_subject_kind_predicate_composes_with_stream_and_subjects_before_hydration(self):
        f = self.f
        port = f.owner.assignments.command_port
        assignment = port.assign(f.project.ref, role="orchestrator", principal="manager", manager="manager",
            pins=[], logical_request_key="predicate-assignment", actor=f.actor)
        report = port.append_report(assignment.ref, {"project_ref": f.project.ref.to_dict(), "summary": "retained"},
            expected_generation=1, logical_request_key="predicate-report", actor=f.actor)
        expected = tuple(event for event in f.store.list_events() if event.subject.kind == "wrk.report")
        with patch.object(f.store, "_event_from_row", wraps=f.store._event_from_row) as hydrate:
            actual = f.store.consumer().list_events(subject_kinds=("wrk.report",))
            self.assertEqual(actual, expected)
            self.assertEqual(hydrate.call_count, len(expected))
        self.assertEqual(f.store.consumer().list_events(stream="report:" + assignment.ref.id,
            subjects=(report.ref,), subject_kinds=("wrk.report",)), expected)
        self.assertEqual(f.store.consumer().list_events(subjects=(report.ref,), subject_kinds=("wrk.result",)), ())
        self.assertEqual(f.store.consumer().list_events(subject_kinds=()), ())
        for invalid in ("wrk.report", ("",), (None,)):
            with self.assertRaises(ValueError):
                f.store.consumer().list_events(subject_kinds=invalid)
        with self.assertRaises(ValueError):
            f.store.consumer().list_events(subject_kinds=("wrk.report",),
                subjects=(ResourceRef("foreign", "wrk.report", report.ref.id),))
        self.assertEqual(f.provider.calls, [])

    def test_issue_report_predicate_preserves_cross_scope_and_historical_project_attribution(self):
        f = self.f
        graph = WorkGraph(f.store, actor=f.actor)
        outside = graph.create_project(title="Other scope", logical_request_key="outside-scope")
        port = f.owner.assignments.command_port
        external = port.assign(outside.ref, role="orchestrator", principal="manager", manager="manager",
            pins=[], logical_request_key="outside-assignment", actor=f.actor)
        old = port.append_report(external.ref, {"project_ref": f.project.ref.to_dict(), "summary": "previous supervisor"},
            expected_generation=1, logical_request_key="old-linked-report", actor=f.actor)
        current = port.reassign(external.ref, principal="manager", expected_generation=1,
            logical_request_key="supervisor-transfer", actor=f.actor)
        new = port.append_report(current.ref, {"project_ref": f.project.ref.to_dict(), "summary": "new supervisor"},
            expected_generation=2, logical_request_key="new-linked-report", actor=f.actor)
        excluded = port.append_report(current.ref, {"project_ref": outside.ref.to_dict()},
            expected_generation=2, logical_request_key="foreign-linked-report", actor=f.actor)
        task_role = port.assign(f.task.ref, role="worker", principal="manager", manager="manager",
            pins=[], logical_request_key="task-report-assignment", actor=f.actor)
        unlinked = port.append_report(task_role.ref, {"summary": "task scoped report"},
            expected_generation=1, logical_request_key="unlinked-report", actor=f.actor)
        operations = f.owner.consumer_operations()
        reader = operations._owner_reader
        calls = []
        class CheckedReader:
            def list_events(self, **kwargs):
                self_outer.assertEqual(kwargs, {"subject_kinds": ("wrk.report", "wrk.result")})
                calls.append(kwargs)
                return reader.list_events(**kwargs)
            def get_record(self, ref): return reader.get_record(ref)
        self_outer = self
        operations._owner_reader = CheckedReader()
        actual = OwnerIssueReaders(operations, f.port).reports(f.project.ref.to_dict())
        # The old global enumeration is a reference projection, not a new grant.
        class LegacyReader(CheckedReader):
            def list_events(self, **kwargs): return reader.list_events()
        operations._owner_reader = LegacyReader()
        expected = OwnerIssueReaders(operations, f.port).reports(f.project.ref.to_dict())
        self.assertEqual(actual, expected)
        self.assertEqual({row["ref"]["id"] for row in actual}, {old.ref.id, new.ref.id, unlinked.ref.id})
        self.assertNotIn(excluded.ref.id, {row["ref"]["id"] for row in actual})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            OwnerIssueReaders(operations, f.port).reports({**f.project.ref.to_dict(), "authority": "foreign"})
        self.assertEqual(f.provider.calls, [])

    def test_pending_inventory_reads_only_granted_current_records_and_current_lifecycle(self):
        f = self.f
        graph = WorkGraph(f.store, actor=f.actor)
        pending = graph.create_project(title="Next pending", logical_request_key="next-pending")
        foreign = graph.create_project(title="Not granted", logical_request_key="not-granted")
        graph.set_lifecycle(f.project.ref, "active", logical_request_key="active-project")
        operations = f.owner.consumer_operations()
        operations.project_read_grant = ProjectReadGrant(f.actor,
            (f.project.id, pending.id, "missing-project"), "test-host", "v2")
        reader = operations._owner_reader
        reads = []
        class ExactReader:
            def list_events(self, **kwargs): raise AssertionError("inventory must not hydrate events")
            def get_record(self, ref):
                reads.append(ref)
                return reader.get_record(ref)
        operations._owner_reader = ExactReader()
        actual = operations.read("work.pending.list", {}, actor="manager")
        self.assertEqual(actual["project_refs"], [pending.ref.to_dict()])
        self.assertEqual({ref.id for ref in reads}, set(operations.project_read_grant.project_ids))
        self.assertNotIn(foreign.id, {ref.id for ref in reads})
        reads.clear()
        self.assertEqual(operations.read("work.pending.list", {}, actor="other")["outcome"], "denied")
        self.assertEqual(operations.read("work.pending.list", {"parent_ref": foreign.ref.to_dict()}, actor="manager")["outcome"], "denied")
        self.assertEqual(reads, [])
        self.assertEqual(operations.read("work.pending.list", {"parent_ref": pending.ref.to_dict()}, actor="manager")["count"], 0)
        self.assertEqual(f.provider.calls, [])


if __name__ == "__main__":
    unittest.main()

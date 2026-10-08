"""Exact assignment stream lookup preserves semantics without global values."""
import unittest
from tests import test_execution_application as fixture

class AssignmentObservationLookupTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ExecutionApplicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
    def test_exact_stream_and_revision_filters_without_global_payload_sort(self):
        f = self.f; p = f.owner.assignments.command_port
        a, _, _ = f.role_handles('worker', 'one', 'one-session')
        b = p.assign(f.project.ref, role='worker', principal='other', session='other-session', logical_request_key='other-assignment')
        first = p.append_report(a.ref, {'small': 1}, expected_generation=1, logical_request_key='small')
        result = p.append_result(a.ref, {'small': 2}, expected_generation=1, logical_request_key='small-result')
        for i in range(12):
            p.append_result(b.ref, {'large': 'x' * 100000}, expected_generation=1, logical_request_key='unrelated-'+str(i))
        statements = []; f.store.connection.set_trace_callback(statements.append)
        try:
            observed = p.list_observations(a.ref)
            reports = p.list_observations(a.ref, kind='report')
        finally: f.store.connection.set_trace_callback(None)
        self.assertEqual([r.ref.id for r in observed], sorted([first.ref.id, result.ref.id]))
        self.assertEqual(reports, (first,))
        lookups = [s for s in statements if s.startswith('SELECT subject_authority')]
        self.assertEqual(len(lookups), 3)
        self.assertTrue(all(a.id in s and 'ORDER BY sequence' in s for s in lookups))
        self.assertFalse(any('kind IN' in s or 'ORDER BY id' in s for s in statements))
        self.assertFalse(any(b.id in s for s in statements))
        changed = p.reassign(a.ref, session='new', expected_generation=1, logical_request_key='change')
        self.assertEqual(p.list_observations(changed.ref), ())
        second = p.append_report(changed.ref, {'small': 3}, expected_generation=2, logical_request_key='new-report')
        self.assertEqual(p.list_observations(changed.ref), (second,))
        self.assertEqual(p.list_observations(changed.ref, kind='unknown'), ())

if __name__ == '__main__': unittest.main()

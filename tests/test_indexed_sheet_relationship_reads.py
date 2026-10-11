"""Optional relationship indexes preserve complete current canonical selection."""
import hashlib
import json
import unittest
from types import SimpleNamespace

from herzchen.contracts import ResourceRef
from herzchen.domains.work.sheet import _ProjectSheetEngine
from herzchen.kernel.store import Store
from tests import test_execution_application as owner_fixture


def sheet(store):
    engine = object.__new__(_ProjectSheetEngine)
    engine._ProjectSheetEngine__writer = SimpleNamespace(connection=store._connection, authority=store.authority)
    return engine


class IndexedSheetRelationshipReadsTests(unittest.TestCase):
    def test_eventless_legacy_decoys_exact_hash_order_and_scaling(self):
        store = Store.create(':memory:', authority='owner')
        self.addCleanup(store.close)
        engine = sheet(store)
        wanted = ResourceRef('owner', 'wrk.assignment', 'assignment-café-"quoted"', 'rev-3')
        selected = [('z-report', 'wrk.report', wanted.to_dict()),
            ('a-result', 'wrk.result', {**wanted.to_dict(), 'revision': 'rev-1'}),
            ('dispatch', 'wrk.dispatch', wanted.to_dict())]
        for ident, kind, ref in selected:
            store.put_identity(ResourceRef('owner', kind, ident, 'rev-1'), {'assignment': ref, 'body': 'retained'})
        for ident, ref in [('authority', {**wanted.to_dict(), 'authority': 'foreign'}),
            ('kind', {**wanted.to_dict(), 'kind': 'work.task'}),
            ('substring', {**wanted.to_dict(), 'id': wanted.id + '-suffix'}),
            ('embedded', {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'elsewhere'})]:
            store.put_identity(ResourceRef('owner', 'wrk.result', ident, 'rev-1'), {'assignment': ref, 'history': wanted.to_dict()})
        for n, value in enumerate((None, 9, True, [], [wanted.to_dict()], 'not-json', '')):
            store.put_identity(ResourceRef('owner', 'wrk.result', 'nonobject-' + str(n), 'rev-1'), {'assignment': value})
        store.put_identity(ResourceRef('owner', 'wrk.result', 'missing', 'rev-1'), {'body': 'no relation'})
        for n in range(256):
            store.put_identity(ResourceRef('owner', 'wrk.result', 'unrelated-' + str(n), 'rev-1'),
                {'assignment': {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'elsewhere'}, 'body': 'x' * 16384})
        kinds = ('wrk.dispatch', 'wrk.result', 'wrk.report')
        before = engine._related_rows(kinds, 'assignment', (wanted, wanted))
        expected = [tuple(r) for r in before]
        digest = lambda: hashlib.sha256(repr([tuple(r) for r in store._connection.execute('SELECT * FROM identities ORDER BY authority,kind,id')]).encode()).hexdigest()
        original = digest()
        built = store.prepare_identity_lookup_indexes()
        self.assertIn('identities_work_assignment_lookup', built['created_indexes'])
        self.assertEqual(digest(), original)
        # Optional acceleration must not add a new write constraint on a
        # legacy nonobject slot. It cannot become a canonical relationship.
        store.put_identity(ResourceRef('owner', 'wrk.result', 'late-malformed', 'rev-1'), {'assignment': 'not-json'})
        counts = []
        for size in (256, 2048):
            if size > 256:
                for n in range(256, size):
                    store.put_identity(ResourceRef('owner', 'wrk.result', 'unrelated-' + str(n), 'rev-1'),
                        {'assignment': {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'elsewhere'}, 'body': 'x' * 16384})
            steps = []
            store._connection.set_progress_handler(lambda: steps.append(1) or 0, 1)
            try:
                actual = engine._related_rows(kinds, 'assignment', (wanted, wanted))
            finally:
                store._connection.set_progress_handler(None, 0)
            self.assertEqual([tuple(r) for r in actual], expected)
            self.assertLess(len(steps), 500)
            counts.append(len(steps))
        self.assertLessEqual(counts[1], counts[0] + 50)
        self.assertEqual(store.list_events(), ())  # No append stream was needed.

    def test_current_canonical_revision_overrides_old_append_stream(self):
        f = owner_fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        port = f.owner.assignments.command_port
        assignment = port.assign(f.project.ref, role='orchestrator', principal='manager', manager='manager',
            pins=[], logical_request_key='indexed-sheet-assignment', actor=f.actor)
        report = port.append_report(assignment.ref, {'summary': 'retained'}, expected_generation=1,
            logical_request_key='indexed-sheet-report', actor=f.actor)
        original_events = f.store.list_events(stream='report:' + assignment.ref.id)
        self.assertTrue(original_events)
        f.store.prepare_identity_lookup_indexes()
        engine = sheet(f.store)
        self.assertEqual([r['id'] for r in engine._related_rows(('wrk.report',), 'assignment', (assignment.ref,))], [report.ref.id])
        identity = f.store.get_identity(report.ref)
        changed = ResourceRef(f.store.authority, 'wrk.assignment', 'current-different-assignment', 'rev-7')
        f.store.revise_identity(identity.ref, {**identity.payload, 'assignment': changed.to_dict()}, revision='rev-2',
            expected_revision=identity.ref.revision, expected_version=identity.version)
        self.assertEqual(engine._related_rows(('wrk.report',), 'assignment', (assignment.ref,)), ())
        self.assertEqual([r['current_revision'] for r in engine._related_rows(('wrk.report',), 'assignment', (changed,))], ['rev-2'])
        self.assertEqual(f.store.list_events(stream='report:' + assignment.ref.id), original_events)


if __name__ == '__main__':
    unittest.main()

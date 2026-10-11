"""Explicit accelerators preserve current exact selector/admission semantics."""
import sqlite3
import tempfile
import unittest
from unittest import mock
from itertools import chain, repeat
from pathlib import Path
from herzchen.contracts import ResourceRef
from herzchen.kernel.schema import IDENTITY_LOOKUP_INDEXES, SCHEMA_REVISION, verify_physical_schema
from herzchen.kernel.store import Store, SchemaMismatchError

PATHS = {('target', 'native_adapter'): 'codex',
    ('host_evidence', 'gateway_attempt', 'delivery_authorization', 'physical_session_id'): 'native'}

def payload(session='native', project='project-a', **extra):
    return dict(project_ref=project, target={'native_adapter': 'codex'},
        host_evidence={'gateway_attempt': {'delivery_authorization': {'physical_session_id': session}}}, **extra)

class IndexedIdentityLookupTests(unittest.TestCase):
    def test_explicit_build_reopen_current_cas_and_indexed_no_scan(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fixture.sqlite'
            s = Store.create(path, authority='owner')
            wanted = s.put_identity(ResourceRef('owner', 'otto.due-record', 'wanted', 'rev-1'), payload())
            for n in range(24):
                s.put_identity(ResourceRef('owner', 'otto.due-record', 'foreign-' + str(n), 'rev-1'),
                    payload('other-' + str(n), 'foreign', body='x' * 65536))
            before = s.get_identity(wanted.ref)
            result = s.prepare_identity_lookup_indexes()
            self.assertEqual(set(result['created_indexes']), set(IDENTITY_LOOKUP_INDEXES))
            self.assertEqual(s.get_identity(wanted.ref), before)
            self.assertEqual(s.prepare_identity_lookup_indexes()['created_indexes'], [])
            sql = "SELECT id FROM identities WHERE authority=? AND kind='otto.due-record' AND json_extract(payload_json, '$.target.native_adapter')=? AND json_extract(payload_json, '$.host_evidence.gateway_attempt.delivery_authorization.physical_session_id')=?"
            plan = list(s._connection.execute('EXPLAIN QUERY PLAN ' + sql, ('owner', 'codex', 'native')))
            self.assertTrue(any('identities_due_native_lookup' in row[3] for row in plan), plan)
            steps = []
            s._connection.set_progress_handler(lambda: steps.append(1) or 0, 1)
            self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches=PATHS), (wanted.ref,))
            s._connection.set_progress_handler(None, 0)
            self.assertLess(len(steps), 250)  # No payload scan of the 24 foreign rows.
            newer = s.revise_identity(wanted.ref, payload('new-native'), revision='rev-2',
                expected_revision='rev-1', expected_version=wanted.version)
            self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches=PATHS), ())
            changed = dict(PATHS); changed[next(k for k in PATHS if k[0] == 'host_evidence')] = 'new-native'
            self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches=changed), (newer.ref,))
            s.close()
            reopened = Store.open(path, authority='owner')
            self.assertEqual(reopened.find_identity_refs(kind='otto.due-record', payload_matches=changed), (newer.ref,))
            reopened.close()

    def test_encoded_strings_nested_history_and_wrong_type_never_authorize(self):
        s = Store.create(':memory:', authority='owner')
        try:
            session = 'café "quoted" \\ newline\n'
            good = s.put_identity(ResourceRef('owner', 'otto.due-record', 'exact', 'rev-1'), payload(session))
            s.put_identity(ResourceRef('owner', 'otto.due-record', 'embedded', 'rev-1'), payload('other', history=session))
            s.put_identity(ResourceRef('owner', 'otto.due-record', 'wrong-type', 'rev-1'), payload(7, history='7'))
            s.prepare_identity_lookup_indexes()
            matches = dict(PATHS); field = next(k for k in matches if k[0] == 'host_evidence'); matches[field] = session
            self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches=matches), (good.ref,))
            matches[field] = '7'; self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches=matches), ())
            self.assertEqual(s.find_identity_refs(kind='otto.due-record', payload_matches={('project_ref',): 'foreign'}), ())
        finally: s.close()

    def test_interrupted_build_rolls_back_and_foreign_or_changed_indexes_rejected(self):
        s = Store.create(':memory:', authority='owner')
        try:
            for n in range(30):
                s.put_identity(ResourceRef('owner', 'otto.due-record', str(n), 'rev-1'), payload(body='x' * 65536))
            statements = []
            s._connection.set_trace_callback(statements.append)
            clock = chain((0.0, 0.0), repeat(2.0))
            with mock.patch('herzchen.kernel.store.time.monotonic', side_effect=lambda: next(clock)):
                with self.assertRaises(sqlite3.OperationalError):
                    s.prepare_identity_lookup_indexes(timeout_seconds=1.0)
            s._connection.set_trace_callback(None)
            self.assertTrue(any(sql.startswith('CREATE INDEX identities_due_native_lookup') for sql in statements))
            self.assertTrue(verify_physical_schema(s._connection, SCHEMA_REVISION))
            self.assertEqual(list(s._connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'identities_due_%'")), [])
            s.prepare_identity_lookup_indexes()
            s._connection.execute('DROP INDEX identities_due_native_lookup')
            s._connection.execute('CREATE INDEX identities_due_native_lookup ON identities(id)')
            self.assertFalse(verify_physical_schema(s._connection, SCHEMA_REVISION))
            with self.assertRaises(SchemaMismatchError): s.prepare_identity_lookup_indexes()
        finally: s.close()

if __name__ == '__main__': unittest.main()

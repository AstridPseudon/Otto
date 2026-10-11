"""Closed-owner diagnostics and copy-on-write migration qualification."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import test_events_history as fixture
from herzchen.kernel.recovery import (ClosedOwnerCustody, closed_owner_custody,
    SnapshotError, storage_diagnostics_closed_owner)

class MaintenanceTests(unittest.TestCase):
    setUp = fixture.HistoryTests.setUp
    legacy_copy = fixture.HistoryTests.legacy_copy

    def test_storage_diagnostic_is_aggregate_only_and_preserves_records(self):
        legacy = self.legacy_copy()
        with closed_owner_custody(legacy, authority='owner', expected_domains=self.domains) as custody:
            before = custody.connection.total_changes
            with unittest.mock.patch('json.loads', side_effect=AssertionError('no JSON hydration')):
                report = storage_diagnostics_closed_owner(custody, group_limit=1)
            self.assertEqual(custody.connection.total_changes, before)
            self.assertFalse(report['payload_content_returned'])
            self.assertEqual(report['page_count'] * report['page_size'], report['source_bytes'])
            self.assertGreater(sum(x['rows'] for x in report['tables']), 0)
            self.assertNotIn(self.project.id, json.dumps(report))
            self.assertLess(len(json.dumps(report)), 20000)
        with self.assertRaisesRegex(Exception, 'no longer active'):
            storage_diagnostics_closed_owner(custody)

    def test_diagnostics_reject_unsealed_custody_and_unbounded_limit(self):
        with self.assertRaises(TypeError):
            storage_diagnostics_closed_owner(object())
        legacy = self.legacy_copy()
        with closed_owner_custody(legacy, authority='owner', expected_domains=self.domains) as custody:
            with self.assertRaises(ValueError):
                storage_diagnostics_closed_owner(custody, group_limit=100000)


class BoundedDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'diagnostic.sqlite'
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript('''
            CREATE TABLE identities(kind TEXT, payload_json TEXT);
            CREATE TABLE events(event_type TEXT, effects_json TEXT);
        ''')
        payload = '{"large":"' + ('x' * (256 * 1024)) + '"}'
        self.conn.executemany('INSERT INTO identities VALUES (?,?)', [('thing', payload)] * 8)
        self.conn.executemany('INSERT INTO events VALUES (?,?)', [('event', payload)] * 16)
        self.conn.commit()
        self.custody = object.__new__(ClosedOwnerCustody)
        self.custody.path = self.path
        self.custody.connection = self.conn
        self.custody.schema_revision = 'test'
        self.custody._active = True
        self.addCleanup(self.conn.close)

    def test_large_payloads_stream_without_sorters_or_mutation(self):
        statements = []
        self.conn.set_trace_callback(statements.append)
        before = self.conn.total_changes
        report = storage_diagnostics_closed_owner(self.custody)
        self.assertEqual(self.conn.total_changes, before)
        self.assertFalse(report['payload_content_returned'])
        self.assertFalse(report['records_modified'])
        self.assertNotIn('x' * 100, json.dumps(report))
        self.assertEqual(report['payload_groups']['events']['groups'][0]['payload_bytes'],
                         16 * len('{"large":"' + ('x' * (256 * 1024)) + '"}'))
        self.assertFalse(any('GROUP BY' in sql.upper() or 'ORDER BY' in sql.upper()
                             for sql in statements))
        plans = self.conn.execute('EXPLAIN QUERY PLAN SELECT event_type,length(CAST(effects_json AS BLOB)) FROM events').fetchall()
        self.assertFalse(any('TEMP B-TREE' in row[-1].upper() for row in plans))

    def test_row_and_vm_limits_return_honest_partial_results(self):
        before = self.conn.total_changes
        report = storage_diagnostics_closed_owner(self.custody, max_rows_per_table=3)
        self.assertFalse(report['records_modified'])
        self.assertEqual(self.conn.total_changes, before)
        events = next(row for row in report['tables'] if row['table'] == 'events')
        self.assertIsNone(events['rows'])
        self.assertEqual(events['rows_scanned'], 3)
        self.assertFalse(events['complete'])
        self.assertEqual(events['reason'], 'row_limit')
        self.assertEqual(report['page_state'], 'available')

        vm_limited = storage_diagnostics_closed_owner(self.custody, max_vm_steps=1)
        self.assertEqual(vm_limited['work']['state'], 'partial')
        self.assertEqual(vm_limited['work']['reason'], 'sqlite_vm_step_limit')
        self.assertFalse(vm_limited['records_modified'])

    def test_inactive_custody_error_is_not_masked_by_handler_cleanup(self):
        stale = object.__new__(ClosedOwnerCustody)
        stale.connection = sqlite3.connect(':memory:')
        stale.connection.close()
        stale._active = False
        with self.assertRaisesRegex(SnapshotError, 'closed-owner custody is no longer active'):
            storage_diagnostics_closed_owner(stale)


class CloneMigrationTests(unittest.TestCase):
    setUp = fixture.HistoryTests.setUp
    legacy_copy = fixture.HistoryTests.legacy_copy
    def prepare(self, custody):
        from herzchen.kernel.recovery import qualify_clone_filesystem
        from herzchen.kernel.migration import EventsMigration
        qualification = qualify_clone_filesystem(self.root)
        plan = EventsMigration.plan(source_path=custody.path,candidate_path=self.root/'new.sqlite',
            backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='same',
            backup_method='clonefile',headroom_bytes=1048576,candidate_growth_reserve_bytes=1048576,
            clone_qualification=qualification)
        return plan, qualification

    def test_real_independent_clone_apply_and_lost_switch_reply_resume(self):
        from herzchen.kernel.migration import EventsMigration, MigrationError
        legacy = self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan, q = self.prepare(custody)
            with EventsMigration.apply(custody,plan,clone_qualification=q) as migration:
                self.assertEqual(migration.journal['backup_method_evidence']['method'],'darwin-clonefile')
                self.assertNotEqual(legacy.stat().st_ino,(self.root/'backup.sqlite').stat().st_ino)
                while migration.step(limit=1)['phase'] != 'verified': pass
                with self.assertRaisesRegex(RuntimeError,'lost'):
                    migration.switch(phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError('lost')) if phase=='after-switch' else None)
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration.resume(custody,self.root/'migration.json') as migration:
                self.assertEqual(migration.journal['phase'],'switched')
                self.assertEqual(migration.installed_receipt()['migration_id'],'same')
                with self.assertRaises(MigrationError): migration.switch()

    def test_clone_interruption_resumes_original_journal_and_retains_partial(self):
        from herzchen.kernel.migration import EventsMigration, MigrationError
        legacy = self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan, q = self.prepare(custody)
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                EventsMigration.apply(custody,plan,clone_qualification=q,
                    phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError('interrupted')) if phase=='backup-clone' else None)
            self.assertTrue((self.root/'backup.sqlite.partial').exists())
            with self.assertRaisesRegex(MigrationError,'resume input differs'):
                EventsMigration.resume(custody,self.root/'migration.json',clone_qualification=q,expected_input={'migration_id':'foreign'})
            with self.assertRaisesRegex(MigrationError,'use resume'):
                EventsMigration.apply(custody,plan,clone_qualification=q)
            with EventsMigration.resume(custody,self.root/'migration.json',clone_qualification=q) as migration:
                self.assertTrue((self.root/'backup.sqlite.partial.interrupted-1').exists())
                while migration.step(limit=1)['phase']!='verified': pass
                migration.switch()

    def test_no_full_copy_fallback_and_same_journal_recovery(self):
        from herzchen.kernel.migration import EventsMigration
        from herzchen.kernel.recovery import SnapshotError
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan,q=self.prepare(custody)
            with unittest.mock.patch('herzchen.kernel.recovery._clonefile',side_effect=SnapshotError('unsupported')):
                with unittest.mock.patch('herzchen.kernel.migration.backup_closed_owner',side_effect=AssertionError('no fallback')):
                    with self.assertRaisesRegex(SnapshotError,'unsupported'):
                        EventsMigration.apply(custody,plan,clone_qualification=q)
            self.assertFalse((self.root/'backup.sqlite').exists())
            with EventsMigration.resume(custody,self.root/'migration.json',clone_qualification=q) as migration:
                self.assertEqual(migration.journal['migration_id'],'same')

    def test_stale_plan_and_fresh_capacity_hold_have_no_apply_effects(self):
        from herzchen.kernel.migration import EventsMigration,MigrationError
        from collections import namedtuple
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan,q=self.prepare(custody)
            altered=dict(plan,source_inode=-1)
            with self.assertRaisesRegex(MigrationError,'source changed'):
                EventsMigration.apply(custody,altered,clone_qualification=q)
            usage=namedtuple('usage','total used free')(1,1,0)
            with unittest.mock.patch('herzchen.kernel.migration.shutil.disk_usage',return_value=usage):
                with self.assertRaisesRegex(MigrationError,'capacity held before apply'):
                    EventsMigration.apply(custody,plan,clone_qualification=q)
            self.assertFalse((self.root/'migration.json').exists())

    def test_space_exhaustion_preserves_batch_and_can_resume(self):
        from herzchen.kernel.migration import EventsMigration,MigrationError
        from collections import namedtuple
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan,q=self.prepare(custody)
            with EventsMigration.apply(custody,plan,clone_qualification=q) as migration:
                before=migration.step(limit=1)
                with unittest.mock.patch('herzchen.kernel.migration.shutil.disk_usage',return_value=namedtuple('usage','total used free')(1,1,0)):
                    with self.assertRaisesRegex(MigrationError,'capacity held'): migration.step(limit=1)
            with EventsMigration.resume(custody,self.root/'migration.json') as migration:
                self.assertEqual(json.loads(dict(migration.owner.connection.execute('SELECT key,value FROM store_metadata'))['migration_progress']),before)
                while migration.step(limit=1)['phase']!='verified':pass
                migration.switch()

    def test_hardlink_probe_and_foreign_qualification_rejected(self):
        import os
        from herzchen.kernel.recovery import qualify_clone_filesystem,SnapshotError,clone_closed_owner
        with unittest.mock.patch('herzchen.kernel.recovery._clonefile',side_effect=os.link):
            with self.assertRaisesRegex(SnapshotError,'independent file'):
                qualify_clone_filesystem(self.root)
        other=self.root/'other';other.mkdir();q=qualify_clone_filesystem(other)
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with self.assertRaisesRegex(SnapshotError,'another directory'):
                clone_closed_owner(custody,self.root/'backup.sqlite',qualification=q)

    def test_changed_input_and_unsafe_paths_rejected(self):
        from herzchen.kernel.migration import EventsMigration,MigrationError
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            plan,q=self.prepare(custody)
            with EventsMigration.apply(custody,plan,clone_qualification=q): pass
            with self.assertRaisesRegex(MigrationError,'changed migration input'):
                EventsMigration.begin(custody,candidate_path=self.root/'other.sqlite',backup_path=self.root/'backup.sqlite',
                    journal_path=self.root/'migration.json',migration_id='same',backup_method='clonefile',clone_qualification=q)
        alias=self.root/'alias';alias.symlink_to(legacy)
        with self.assertRaisesRegex(MigrationError,'symlink'):
            EventsMigration.plan(source_path=legacy,candidate_path=alias,backup_path=self.root/'backup2',
                journal_path=self.root/'newjournal',migration_id='same',backup_method='clonefile',clone_qualification=q)

    def test_clone_requires_settled_sidecars_and_unchanged_source(self):
        from herzchen.kernel.recovery import qualify_clone_filesystem,clone_closed_owner,SnapshotError
        legacy=self.legacy_copy();q=qualify_clone_filesystem(self.root)
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            sidecar=legacy.with_name(legacy.name+'-wal');sidecar.write_bytes(b'unsettled')
            with self.assertRaisesRegex(SnapshotError,'unsettled'):
                clone_closed_owner(custody,self.root/'blocked.sqlite',qualification=q)
            sidecar.unlink()  # Disposable fixture only; never actual cleanup.
            original=dict(custody.source_file_state);custody.source_file_state['inode']=-1
            with self.assertRaisesRegex(SnapshotError,'source changed'):
                clone_closed_owner(custody,self.root/'blocked.sqlite',qualification=q)
            custody.source_file_state=original
            self.assertFalse((self.root/'blocked.sqlite').exists())

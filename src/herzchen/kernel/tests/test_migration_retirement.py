"""Exact completed-backup retirement; only disposable fixture files removed."""
import json
import unittest
from pathlib import Path
import test_events_history as fixture
from herzchen.kernel.migration import EventsMigration, MigrationError, _write_journal, _read_journal
from herzchen.kernel.recovery import closed_owner_custody

class RetirementTests(unittest.TestCase):
    setUp = fixture.HistoryTests.setUp
    legacy_copy = fixture.HistoryTests.legacy_copy
    def migrate(self, custody, complete=True):
        migration = EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='same')
        if complete:
            while migration.step(limit=2)['phase'] != 'verified': pass
            migration.switch()
        migration.close()
    def retire(self,custody,**overrides):
        journal=_read_journal(self.root/'migration.json')
        return EventsMigration.retire_backup(custody,self.root/'migration.json',**dict({'expected_backup':self.root/'backup.sqlite','expected_backup_digest':journal['backup_digest']},**overrides))
    def test_completed_release_resume_preserves_later_writes_and_journal(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            self.migrate(custody)
            custody.connection.execute("INSERT INTO store_metadata VALUES ('later_write','retained')")
            before_changes=custody.connection.total_changes
            before=(self.root/'migration.json').read_bytes()
            proof=self.retire(custody)
            self.assertTrue((self.root/'backup.sqlite').exists())
            self.assertTrue(proof['release_permitted']); self.assertFalse(proof['backup_deleted'])
            self.assertEqual(proof,self.retire(custody))
            (self.root/'backup.sqlite').unlink() # Fixture only; actual release never deletes.
            with unittest.mock.patch('herzchen.kernel.migration._file_digest',side_effect=AssertionError('no backup read')):
                with EventsMigration.resume(custody,self.root/'migration.json') as migration:
                    self.assertEqual(migration.installed_receipt()['migration_id'],'same')
                    with self.assertRaises(MigrationError): migration.step(limit=1)
                    with self.assertRaises(MigrationError): migration.switch()
            self.assertEqual(custody.connection.total_changes,before_changes)
            self.assertEqual((self.root/'migration.json').read_bytes(),before)
            self.assertEqual(custody.connection.execute("SELECT value FROM store_metadata WHERE key='later_write'").fetchone()[0],'retained')
    def test_interrupted_and_lost_reply_cannot_retire(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            self.migrate(custody,False)
            with self.assertRaisesRegex(MigrationError,'completed'): self.retire(custody)
            with EventsMigration.resume(custody,self.root/'migration.json') as migration:
                while migration.step(limit=2)['phase']!='verified':pass
                with self.assertRaisesRegex(RuntimeError,'lost'):
                    migration.switch(phase_hook=lambda p: (_ for _ in ()).throw(RuntimeError('lost')) if p=='after-switch' else None)
            with self.assertRaisesRegex(MigrationError,'completed'):self.retire(custody)
            with EventsMigration.resume(custody,self.root/'migration.json') as migration:
                self.assertEqual(migration.journal['phase'],'switched')
            self.retire(custody)
    def test_exact_path_digest_and_authenticated_custody(self):
        with self.assertRaises(TypeError):EventsMigration.retire_backup(object(),self.root/'migration.json',expected_backup='unused',expected_backup_digest='unused')
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            self.migrate(custody)
            with self.assertRaisesRegex(MigrationError,'path/digest'):self.retire(custody,expected_backup=self.root/'foreign.sqlite')
            with self.assertRaisesRegex(MigrationError,'path/digest'):self.retire(custody,expected_backup_digest='foreign')
            receipt=json.loads(dict(custody.connection.execute('SELECT key,value FROM store_metadata'))['migration_switch_receipt'])
            receipt['source_inventory']['events']['sha256']='foreign'
            custody.connection.execute("UPDATE store_metadata SET value=? WHERE key='migration_switch_receipt'",(json.dumps(receipt),))
            with self.assertRaisesRegex(MigrationError,'switch proof'):self.retire(custody)
    def test_foreign_retirement_and_changed_installed_identity_rejected(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            self.migrate(custody); self.retire(custody)
            retirement=self.root/'migration.json.backup-retirement.json'
            data=_read_journal(retirement);data['backup']='foreign';_write_journal(retirement,data)
            with self.assertRaisesRegex(MigrationError,'retirement proof'):EventsMigration.resume(custody,self.root/'migration.json')
            with self.assertRaisesRegex(MigrationError,'retirement differs'):self.retire(custody)
            retirement.unlink() # Disposable fixture only.
            self.retire(custody)
            custody.connection.execute("UPDATE store_metadata SET value='foreign' WHERE key='migration_id'")
            with self.assertRaisesRegex(MigrationError,'switch proof'):EventsMigration.resume(custody,self.root/'migration.json')
    def test_unretired_missing_backup_and_retired_interrupted_journal_fail(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            self.migrate(custody); self.retire(custody)
            journal=self.root/'migration.json'; data=_read_journal(journal);data['phase']='backfill';_write_journal(journal,data)
            with self.assertRaisesRegex(MigrationError,'completed'):EventsMigration.resume(custody,journal)
            data['phase']='switched';_write_journal(journal,data)
            (self.root/'migration.json.backup-retirement.json').unlink();(self.root/'backup.sqlite').unlink()
            with self.assertRaises(Exception):EventsMigration.resume(custody,journal)

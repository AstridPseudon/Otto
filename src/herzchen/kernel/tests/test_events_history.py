"""D02 transactional and offline-migration qualification on disposable copies."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor, ResourceRef, canonical_json
from herzchen.kernel import Store, WriterBusyError, MigrationRequiredError, SchemaMismatchError
from herzchen.kernel.schema import (LEGACY_DDL, LEGACY_COMPOSITION, LEGACY_SCHEMA_REVISION,
    LEGACY_SCHEMA_FINGERPRINT, SCHEMA_REVISION, SCHEMA_FINGERPRINT, COMPOSITION)
from herzchen.kernel.recovery import closed_owner_custody
from herzchen.kernel.migration import EventsMigration, MigrationError
from herzchen.kernel.history import project_relations, EvidenceHistoryPublisher
from herzchen.domains.work import WorkGraph, contributions
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.assignments import ResponsibilityAssignments


class Interrupted(Exception):
    pass


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store.create(self.root/'owner.sqlite', authority='owner')
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(contributions(include_assignment_resources=True))
        self.actor = AuthenticatedActor('owner','host','credential')
        self.graph = WorkGraph(self.store, actor=self.actor)
        self.project = self.graph.create_project(title='Project', logical_request_key='project')

    def event(self):
        return self.store._event_from_row(self.store.connection.execute('SELECT * FROM events ORDER BY append_position DESC LIMIT 1').fetchone())

    def test_creation_revision_membership_and_lifecycle_are_atomic(self):
        project = self.project
        event = self.event()
        history = event.effects['history_summary']['primary']
        self.assertFalse(history['before']['exists'])
        self.assertEqual(history['after']['ref'],project.ref.to_dict())
        task = self.graph.create_task(project, title='Task', logical_request_key='task')
        before = task.ref
        task = self.graph.revise(task, lifecycle='active', logical_request_key='revise')
        history = self.event().effects['history_summary']['primary']
        self.assertEqual(history['before']['ref'],before.to_dict())
        self.assertEqual(history['after']['ref'],task.ref.to_dict())
        self.assertEqual(history['before']['fields']['lifecycle'],'pending')
        self.assertEqual(history['after']['fields']['lifecycle'],'active')
        self.assertEqual(project_relations(history)[0]['id'],project.id)
        events_before = len(self.store.list_events())
        with self.assertRaises(Interrupted):
            with self.store.transaction():
                self.graph.revise(task, lifecycle='paused', logical_request_key='rolled-back')
                raise Interrupted()
        self.assertEqual(len(self.store.list_events()),events_before)
        self.assertIsNone(self.store.get_receipt('rolled-back'))
        self.assertEqual(self.graph.get(task).payload['lifecycle'],'active')
        positions = [r[0] for r in self.store.connection.execute('SELECT append_position FROM events ORDER BY append_position')]
        self.assertEqual(positions,list(range(1,len(positions)+1)))

    def test_batch_children_have_exact_parent_facets_without_child_events(self):
        batches = ProjectBatches(self.store,actor=self.actor)
        before = len(self.store.list_events())
        result = batches.apply_project_sheet(self.project, {'tasks':[{'id':'A','title':'Alpha'},{'id':'B','title':'Beta'}]}, logical_request_key='sheet')
        self.assertEqual(len(self.store.list_events()),before+1)
        event = self.event()
        facets = event.effects['history_summary']['facets']
        self.assertEqual(len(facets),2)
        self.assertEqual({x['after']['ref']['revision'] for x in facets},{'rev-1'})
        self.assertTrue(all(not x['before']['exists'] for x in facets))
        task = self.graph.get(result.mappings['A'])
        next_result = batches.apply_project_sheet(result.project,{'tasks':[{'id':'A','lifecycle':'active'}]},logical_request_key='sheet-next')
        facets = self.event().effects['history_summary']['facets']
        self.assertEqual(len(facets),1)
        self.assertEqual(facets[0]['before']['ref'],task.ref.to_dict())
        self.assertEqual(facets[0]['after']['fields']['lifecycle'],'active')
        count = len(self.store.list_events())
        replay = batches.apply_project_sheet(self.project, {'tasks':[{'id':'A','title':'Alpha'},{'id':'B','title':'Beta'}]}, logical_request_key='sheet')
        self.assertEqual(replay.receipt.event_ids,result.receipt.event_ids)
        self.assertEqual(len(self.store.list_events()),count)

    def test_batch_document_revision_and_association_facets_keep_parent_project(self):
        batches=ProjectBatches(self.store,actor=self.actor)
        document=ResourceRef('owner','dat.content.document','plan')
        def sheet(revision):
            return {'document_changes':[{'document':document.to_dict(),'revision':revision,'content':{'body':'x'*200000}}],
                'document_links':[{'document':document.to_dict(),'binding':'pinned','revision':revision,'key':'plan'}]}
        before=len(self.store.list_events())
        result=batches.apply_project_sheet(self.project,sheet('rev-1'),logical_request_key='documents-1')
        first=self.event().effects['history_summary']['facets']
        self.assertEqual(len(first),3)
        self.assertTrue(all(not f['before']['exists'] for f in first))
        self.assertTrue(all({p['id'] for p in project_relations(f)}=={self.project.id} for f in first))
        result=batches.apply_project_sheet(result.project,sheet('rev-2'),logical_request_key='documents-2')
        facets=self.event().effects['history_summary']['facets']
        self.assertEqual(len(self.store.list_events()),before+2)
        self.assertEqual(len(facets),3)
        head=next(f for f in facets if f['subject']['kind']=='dat.content.document')
        self.assertEqual(head['before']['fields']['current_revision']['revision'],'rev-1')
        self.assertEqual(head['after']['fields']['current_revision']['revision'],'rev-2')
        association=next(f for f in facets if f['subject']['kind']=='dat.content.association')
        self.assertTrue(any(r['relation']=='document' for r in association['relation_changes']))
        self.assertTrue(all(len(canonical_json(f).encode())<65536 for f in facets))
        self.assertNotIn('x'*1000,canonical_json(facets))

    def test_assignment_scope_generation_replacement_and_responsibility(self):
        task = self.graph.create_task(self.project,title='Task',logical_request_key='task')
        engine = ResponsibilityAssignments(self.store,actor=self.actor)
        assignment = engine.assign(task.ref,role='worker',principal='first',logical_request_key='assign')
        event = self.event()
        history = event.effects['history_summary']
        self.assertEqual(history['primary']['after']['fields']['generation'],1)
        self.assertEqual(project_relations(history['primary'])[0]['id'],self.project.id)
        self.assertEqual(len(history['facets']),1)
        changed = engine.reassign(assignment.ref,principal='second',reason='replacement',logical_request_key='replace')
        history = self.event().effects['history_summary']['primary']
        self.assertEqual(history['before']['fields']['principal'],'first')
        self.assertEqual(history['after']['fields']['principal'],'second')
        self.assertEqual(history['before']['fields']['generation'],1)
        self.assertEqual(history['after']['fields']['generation'],2)

    def test_concurrent_store_threads_allocate_owner_order_and_savepoint_rolls_back(self):
        import concurrent.futures
        def create(i):
            return self.graph.create_project(title=str(i),logical_request_key='thread-'+str(i))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(create,range(12)))
        positions = [r[0] for r in self.store.connection.execute('SELECT append_position FROM events ORDER BY append_position')]
        self.assertEqual(positions,list(range(1,len(positions)+1)))
        with self.store.transaction():
            with self.assertRaises(Interrupted):
                with self.store.transaction():
                    create(99)
                    raise Interrupted()
            create(100)
        self.assertIsNone(self.store.get_receipt('thread-99'))
        self.assertIsNotNone(self.store.get_receipt('thread-100'))

    def test_large_batch_requires_evidence_and_failure_rolls_back_everything(self):
        batches = ProjectBatches(self.store,actor=self.actor)
        rows = [{'id':str(i),'title':str(i)} for i in range(130)]
        before = self.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(Exception,'large history'):
            batches.apply_project_sheet(self.project,{'tasks':rows},logical_request_key='large')
        self.assertEqual(self.store.consumer().snapshot_counts(),before)
        self.assertIsNone(self.store.get_receipt('large'))

    def evidence(self):
        from test_evidence_reclaim import _current_pack
        from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
        register_evidence(self.store)
        pack = _current_pack()
        handler = EvidenceCommandHandler(self.store, self.root/'managed',pack=pack,
            adopted_pins=[item.to_dict() for item in pack.resources],
            authorize_lifecycle=lambda *_: True,
            resolve_dependencies=lambda *_: {"complete":True,"holds":()})
        self.store.configure_history_publisher(EvidenceHistoryPublisher(handler,self.actor))
        return handler

    def test_real_evidence_manifest_pin_range_and_essential_history_protection(self):
        handler = self.evidence()
        batches = ProjectBatches(self.store,actor=self.actor)
        result = batches.apply_project_sheet(self.project,{'tasks':[{'id':str(i),'title':str(i)} for i in range(130)]},logical_request_key='large')
        eid = result.receipt.event_ids[0]
        event = self.store._event_from_row(self.store.connection.execute('SELECT * FROM events WHERE event_id=?',(eid,)).fetchone())
        history = event.effects['history_summary']
        self.assertEqual(history['facets'],[])
        self.assertEqual(history['manifest']['facet_count'],130)
        pinned = ResourceRef.from_dict(history['manifest']['ref'])
        self.assertIsNotNone(pinned.revision)
        self.assertIn(pinned,event.after_refs)
        chunks=[];offset=0
        while True:
            page=handler.read_evidence(pinned,actor=self.actor,offset=offset,max_bytes=4096)
            self.assertLessEqual(len(page['bytes']),4096)
            chunks.append(page['bytes'])
            if page['next_offset'] is None:
                break
            offset=page['next_offset']
        data=b''.join(chunks)
        self.assertEqual(hashlib.sha256(data).hexdigest(),history['manifest']['byte_digest'])
        facets=[json.loads(line) for line in data.splitlines()]
        self.assertEqual(len(facets),130)
        self.assertEqual({f['after']['ref']['id'] for f in facets},{r.id for r in result.mappings.values()})
        self.assertTrue(all(f['facet_type']=='project_sheet_batch_child' for f in facets))
        self.assertEqual(len([e for e in self.store.list_events() if e.event_type=='work.project-sheet.applied']),1)
        preview=handler.reclaim_preview(result.project.ref,actor=self.actor,logical_request_key='protect',cutoff='9999Z')
        self.assertTrue(any(x['hold']=='dependency-unknown' for x in preview['items']))

    def test_failed_outer_commit_retains_evidence_residue_without_domain_history(self):
        self.evidence()
        batches=ProjectBatches(self.store,actor=self.actor)
        counts=self.store.consumer().snapshot_counts()
        flush=self.store._flush_history
        def fail(tx):
            flush(tx)
            raise Interrupted()
        with patch.object(self.store,'_flush_history',side_effect=fail):
            with self.assertRaises(Interrupted):
                batches.apply_project_sheet(self.project,{'tasks':[{'id':str(i),'title':str(i)} for i in range(130)]},logical_request_key='residue')
        self.assertEqual(self.store.consumer().snapshot_counts(),counts)
        self.assertIsNone(self.store.get_receipt('residue'))
        self.assertTrue(list((self.root/'managed').rglob('*.json')))
        # Exact staged bytes can be reconciled through retained Evidence
        # sidecars. Nothing silently prunes the failed publication residue.
        sidecars=[p for p in (self.root/'managed').rglob('*.json') if 'staging' in str(p)]
        self.assertTrue(sidecars)

    def test_backup_and_candidate_preparation_interruptions_resume_same_input(self):
        legacy=self.legacy_copy()
        kwargs=dict(candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='migration')
        for point in ('backup-copy','after-candidate-create'):
            with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
                with self.assertRaises(Interrupted):
                    EventsMigration.begin(custody,**kwargs,phase_hook=lambda p: (_ for _ in ()).throw(Interrupted()) if p==point else None)
        self.assertTrue(list(self.root.glob('backup.sqlite.partial.interrupted-*')))
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration.begin(custody,**kwargs) as migration:
                with self.assertRaises(MigrationError):
                    EventsMigration.begin(custody,**{**kwargs,'migration_id':'changed'})
                with self.assertRaises(WriterBusyError):
                    Store.open(self.root/'new.sqlite',authority='owner')
                while migration.step(limit=2)['phase']!='verified':
                    pass
                migration.switch()

    def test_legacy_readonly_admission_and_old_reference_truth(self):
        before=self.project.ref
        current=self.graph.revise(self.project,title='Changed',logical_request_key='changed')
        legacy=self.legacy_copy()
        with Store.open_readonly(legacy,authority='owner',expected_domains=self.domains) as reader:
            self.assertFalse(hasattr(reader,'mutate'))
            self.assertFalse(hasattr(reader,'connection'))
            self.assertEqual(reader.get_identity(before).ref,current.ref)
            self.assertNotEqual(reader.get_identity(before).ref,before)
            self.assertEqual(reader.get_receipt('changed'),self.store.get_receipt('changed'))

    def test_source_and_backup_tampering_and_projection_mismatch_refuse_switch(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            migration=EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='migration')
            self.addCleanup(migration.close)
            while migration.step(limit=2)['phase']!='verified':
                pass
            with migration.owner.transaction() as tx:
                tx.execute("UPDATE project_history SET summary_json='{}'")
            with self.assertRaisesRegex(MigrationError,'rebuild equality'):
                migration.switch()
            self.assertEqual(dict(custody.connection.execute('SELECT key,value FROM store_metadata'))['schema_revision'],LEGACY_SCHEMA_REVISION)

    def legacy_copy(self):
        self.domains = self.store.registered_domains()
        legacy = self.root/'legacy.sqlite'
        conn = sqlite3.connect(legacy)
        conn.executescript(LEGACY_DDL)
        for table in LEGACY_COMPOSITION:
            columns = [r[1] for r in conn.execute('PRAGMA table_info('+table+')')]
            for row in self.store.connection.execute('SELECT '+','.join(columns)+' FROM '+table):
                conn.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in columns)+')',tuple(row))
        for key,value in [('schema_revision',LEGACY_SCHEMA_REVISION),('schema_fingerprint',LEGACY_SCHEMA_FINGERPRINT),('composition',canonical_json(LEGACY_COMPOSITION))]:
            conn.execute('UPDATE store_metadata SET value=? WHERE key=?',(value,key))
        conn.execute("DELETE FROM store_metadata WHERE key IN ('source_next_append','history_generation','history_checkpoint','legacy_append_boundary')")
        # Genuine legacy events have no new source summaries. Preserve all
        # original effects, IDs, request receipts, decisions and debit payloads.
        for eid,effects in conn.execute('SELECT event_id,effects_json FROM events').fetchall():
            value = json.loads(effects); value.pop('history_summary',None)
            conn.execute('UPDATE events SET effects_json=? WHERE event_id=?',(canonical_json(value),eid))
        conn.commit();conn.close()
        return legacy

    def migrate(self,legacy,hook=None):
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='migration') as migration:
                while migration.step(limit=1)['phase'] != 'verified':
                    pass
                return migration.switch(phase_hook=hook)

    def test_legacy_admission_custody_and_verbatim_migration(self):
        self.graph.create_task(self.project,title='Task',logical_request_key='task')
        legacy = self.legacy_copy()
        with self.assertRaises(MigrationRequiredError):
            Store.open(legacy,authority='owner',expected_domains=self.domains)
        with self.assertRaises(WriterBusyError):
            with closed_owner_custody(self.store.path,authority='owner',expected_domains=self.domains):
                pass
        receipt = self.migrate(legacy)
        self.assertEqual(receipt['legacy_chronology'],'unknown')
        with Store.open(legacy,authority='owner',expected_domains=self.domains) as adopted:
            self.assertEqual(adopted.get_receipt('task'),self.store.get_receipt('task'))
            facets = [json.loads(r[0]) for r in adopted.connection.execute('SELECT summary_json FROM project_history')]
            self.assertTrue(all(f['coverage']=='legacy-field-gaps' for f in facets))
            self.assertTrue(all(f['before']['exists'] is None for f in facets))
            self.assertTrue(any('project_ref' in f['after']['unknown'] for f in facets))
            self.assertEqual(adopted.get_identity(self.project.ref).payload,self.store.get_identity(self.project.ref).payload)
            self.assertEqual(dict(adopted.connection.execute('SELECT key,value FROM store_metadata'))['source_next_append'],'3')
            new = WorkGraph(adopted,actor=self.actor).create_project(title='New',logical_request_key='successor-write')
            self.assertEqual(adopted.connection.execute('SELECT max(append_position) FROM events').fetchone()[0],3)
            # Old physical composition rejects the successor.
            with self.assertRaises(Exception):
                Store._verify(adopted.connection,'owner',self.domains,schema_revision=LEGACY_SCHEMA_REVISION)

    def test_resume_interrupted_copy_order_backfill_and_both_sides_of_switch(self):
        self.graph.create_task(self.project,title='Task',logical_request_key='task')
        self.graph.create_project(title='Other',logical_request_key='other')
        legacy = self.legacy_copy()
        journal = self.root/'migration.json'
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            migration = EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=journal,migration_id='migration')
            migration.close()
        interrupted = set()
        while True:
            with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
                with EventsMigration(custody,journal) as migration:
                    phase = json.loads(dict(migration.owner.connection.execute('SELECT key,value FROM store_metadata'))['migration_progress'])['phase']
                    if phase == 'verified':
                        with self.assertRaises(Interrupted):
                            migration.switch(phase_hook=lambda p: (_ for _ in ()).throw(Interrupted()) if p=='before-switch' else None)
                        break
                    modes = [mode for mode in ('before','after') if (phase,mode) not in interrupted]
                    if modes and phase in {'copy','order','normalize','backfill'}:
                        mode = modes[0]
                        interrupted.add((phase,mode))
                        with self.assertRaises(Interrupted):
                            migration.step(limit=1,phase_hook=lambda p: (_ for _ in ()).throw(Interrupted()) if p.startswith(mode+'-') else None)
                    else:
                        migration.step(limit=1)
        self.assertEqual(interrupted,{(phase,mode) for phase in ('copy','order','normalize','backfill') for mode in ('before','after')})
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration(custody,journal) as migration:
                with self.assertRaises(Interrupted):
                    migration.switch(phase_hook=lambda p: (_ for _ in ()).throw(Interrupted()) if p=='after-switch' else None)
        with Store.open(legacy,authority='owner',expected_domains=self.domains) as adopted:
            WorkGraph(adopted,actor=self.actor).create_project(title='After',logical_request_key='after-switch')
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration(custody,journal) as migration:
                self.assertEqual(migration.journal['phase'],'switched')
                self.assertIsNotNone(custody.connection.execute("SELECT logical_request_key FROM command_receipts WHERE logical_request_key='after-switch'").fetchone())
                with self.assertRaises(MigrationError):
                    migration.switch()

    def test_receipts_logical_keys_decisions_and_real_limit_debits_are_preserved_without_replay(self):
        from herzchen.kernel import LimitService
        limits=LimitService(self.store)
        pool_ref=ResourceRef('owner','limit','pool')
        pool=limits.create_pool(pool_ref,1,5,logical_request_key='pool',actor=self.actor)
        reservation=limits.reserve(pool_ref,ResourceRef('owner','reservation','reserved'),1,logical_request_key='reserved',actor=self.actor)
        debit=limits.settle(reservation,1,logical_request_key='debit',actor=self.actor)
        decision=ResourceRef('owner','assessment.decision','decision','rev-1')
        self.store.put_identity(decision,{'verdict':'accepted','candidate':self.project.ref.to_dict(),'gate':'gate'},version=1)
        self.store.put_reference(decision)
        legacy=self.legacy_copy()
        with patch.object(Store,'mutate',side_effect=AssertionError('domain/provider replay forbidden')):
            receipt=self.migrate(legacy)
        with Store.open(legacy,authority='owner',expected_domains=self.domains) as adopted:
            self.assertEqual(adopted.get_identity(decision),self.store.get_identity(decision))
            self.assertEqual(LimitService(adopted).get_pool(pool_ref),limits.get_pool(pool_ref))
            self.assertEqual(LimitService(adopted).get_reservation(ResourceRef('owner','reservation','reserved')),limits.get_reservation(ResourceRef('owner','reservation','reserved')))
            self.assertEqual(adopted.get_receipt('debit'),self.store.get_receipt('debit'))
            self.assertEqual(receipt['source_inventory']['command_receipts']['count'],4)

    def test_durable_append_resume_and_imported_event_replay(self):
        from dataclasses import replace
        original=self.event()
        imported=replace(original,event_id='imported',stream='imported',sequence=1,effects={'fact':'retained'})
        self.store.append_event(imported,transaction_id='external')
        before=dict(self.store.connection.execute('SELECT key,value FROM store_metadata'))['source_next_append']
        self.assertEqual(self.store.append_event(imported),imported)
        self.assertEqual(dict(self.store.connection.execute('SELECT key,value FROM store_metadata'))['source_next_append'],before)
        domains=self.store.registered_domains();path=self.store.path;self.store.close()
        self.store=Store.open(path,authority='owner',expected_domains=domains)
        self.addCleanup(self.store.close)
        WorkGraph(self.store,actor=self.actor).create_project(title='After',logical_request_key='after')
        self.assertEqual(self.store.connection.execute('SELECT max(append_position) FROM events').fetchone()[0],int(before))

    def test_source_drift_backup_drift_and_pending_candidate_admission(self):
        legacy=self.legacy_copy()
        journal=self.root/'migration.json'
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=journal,migration_id='migration').close()
        with self.assertRaises(MigrationRequiredError):
            Store.open(self.root/'new.sqlite',authority='owner')
        conn=sqlite3.connect(legacy)
        conn.execute("UPDATE identities SET payload_json='{}' WHERE kind='work.project'");conn.commit();conn.close()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with self.assertRaisesRegex(MigrationError,'source changed'):
                EventsMigration(custody,journal)
        conn=sqlite3.connect(self.root/'backup.sqlite')
        conn.execute("UPDATE identities SET payload_json='{}' WHERE kind='work.project'");conn.commit();conn.close()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with self.assertRaisesRegex(MigrationError,'backup digest'):
                EventsMigration(custody,journal)

    def test_recovery_successor_snapshot_restore_preserves_new_composition(self):
        from herzchen.kernel.recovery import create_snapshot,restore_snapshot
        source=ResourceRef('owner','source','source','rev-1')
        realm=ResourceRef('owner','realm','realm','rev-1')
        snapshot=create_snapshot(self.store,self.root/'snapshot',source_identity=source,realm_identity=realm)
        self.assertEqual(snapshot.schema_revision,SCHEMA_REVISION)
        result=restore_snapshot(self.root/'snapshot',self.root/'restored',expected_source_identity=source,
            expected_realm_identity=realm,expected_authority='owner',expected_composition=COMPOSITION,
            expected_composition_digest=snapshot.composition_digest,expected_schema_fingerprint=SCHEMA_FINGERPRINT)
        with Store.open(self.root/'restored'/'database.sqlite3',authority='owner',expected_domains=self.store.registered_domains()) as restored:
            self.assertEqual(restored.list_events(),self.store.list_events())

    def test_closed_owner_custody_cannot_be_fabricated_or_reused_after_exit(self):
        from herzchen.kernel.recovery import ClosedOwnerCustody, SnapshotError
        legacy=self.legacy_copy()
        with self.assertRaises(SnapshotError):
            ClosedOwnerCustody(legacy,'owner',None,(),LEGACY_SCHEMA_REVISION)
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            custody.require_active()
        with self.assertRaises(SnapshotError):
            EventsMigration(custody,self.root/'nonexistent-journal')

    def test_recovery_restores_a_migrated_successor_to_a_fresh_path(self):
        from herzchen.kernel.recovery import create_snapshot,restore_snapshot
        legacy=self.legacy_copy()
        self.migrate(legacy)
        source=ResourceRef('owner','source','source','rev-1')
        realm=ResourceRef('owner','realm','realm','rev-1')
        with Store.open(legacy,authority='owner',expected_domains=self.domains) as migrated:
            snapshot=create_snapshot(migrated,self.root/'migrated-snapshot',source_identity=source,realm_identity=realm)
            expected=migrated.list_events()
        restored=restore_snapshot(self.root/'migrated-snapshot',self.root/'restored-migrated',expected_source_identity=source,
            expected_realm_identity=realm,expected_authority='owner',expected_composition=COMPOSITION,
            expected_composition_digest=snapshot.composition_digest,expected_schema_fingerprint=SCHEMA_FINGERPRINT)
        with Store.open(self.root/'restored-migrated'/'database.sqlite3',authority='owner',expected_domains=self.domains) as owner:
            self.assertEqual(owner.list_events(),expected)

    def test_stale_assignment_scope_uses_retained_exact_revision_not_current_head(self):
        task=self.graph.create_task(self.project,title='Task',logical_request_key='task')
        assignments=ResponsibilityAssignments(self.store,actor=self.actor)
        assignment=assignments.assign(task.ref,role='worker',principal='first',logical_request_key='assignment')
        other=self.graph.create_project(title='Other',logical_request_key='other')
        self.graph.link_parent(task,other,logical_request_key='move')
        assignments.reassign(assignment.ref,principal='second',reason='replace',logical_request_key='replace')
        summary=self.event().effects['history_summary']['primary']
        self.assertEqual({p['id'] for p in project_relations(summary)},{self.project.id})
        self.assertTrue(all(r['coverage']=='retained-exact-revision-summary' for r in summary['project_resolution']))

    def test_individually_oversized_history_rejects_atomically(self):
        from herzchen.contracts import CommandEnvelope,TransactionContext
        counts=self.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(Exception,'historical state|typed history'):
            payload={**self.project.payload,'documents':['x'*70000]}
            envelope=CommandEnvelope(operation='work.revise',schema_revision='work.v1',target=self.project.ref,
                payload=payload,context=TransactionContext(actor=self.actor,logical_request_key='oversized',
                request_digest=hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
                expected_version=self.project.version,expected_revision=self.project.revision))
            handler=self.store.domain_handler(contributions(include_assignment_resources=True))
            handler.mutate(envelope,identity_payload=payload,event_type='work.revised',effects={})
        self.assertEqual(self.store.consumer().snapshot_counts(),counts)
        self.assertIsNone(self.store.get_receipt('oversized'))
        self.assertNotIn('documents',self.graph.get(self.project).payload.get('custom',{}))

    def test_legacy_oversized_fields_are_disclosed_without_losing_source_bytes(self):
        legacy=self.legacy_copy()
        conn=sqlite3.connect(legacy)
        eid,effects=conn.execute('SELECT event_id,effects_json FROM events LIMIT 1').fetchone()
        value=json.loads(effects)
        value['result_payload']={'project_ref':self.project.ref.to_dict(),'pins':['x'*100000]}
        exact=canonical_json(value)
        conn.execute('UPDATE events SET effects_json=? WHERE event_id=?',(exact,eid));conn.commit();conn.close()
        self.migrate(legacy)
        with Store.open(legacy,authority='owner',expected_domains=self.domains) as migrated:
            self.assertEqual(migrated.connection.execute('SELECT effects_json FROM events WHERE event_id=?',(eid,)).fetchone()[0],exact)
            summary=migrated.connection.execute('SELECT summary_json FROM project_history WHERE source_event_id=?',(eid,)).fetchone()[0]
            self.assertLessEqual(len(summary.encode()),65536)
            facet=json.loads(summary)
            self.assertEqual(facet['legacy']['bounded_field_gaps'],['pins'])
            self.assertIn('pins',facet['after']['unknown'])
            self.assertEqual(facet['after']['fields']['project_ref'],self.project.ref.to_dict())

    def test_switch_custody_closes_replacement_connection(self):
        legacy=self.legacy_copy()
        with closed_owner_custody(legacy,authority='owner',expected_domains=self.domains) as custody:
            with EventsMigration.begin(custody,candidate_path=self.root/'new.sqlite',backup_path=self.root/'backup.sqlite',journal_path=self.root/'migration.json',migration_id='migration') as migration:
                while migration.step(limit=2)['phase']!='verified':
                    pass
                migration.switch()
                replacement=custody.connection
                self.assertEqual(replacement.execute('SELECT 1').fetchone()[0],1)
        with self.assertRaises(sqlite3.ProgrammingError):
            replacement.execute('SELECT 1')

    def test_unknown_migration_progress_cannot_weaken_admission(self):
        path=self.store.path;self.domains=self.store.registered_domains();self.store.close()
        conn=sqlite3.connect(path)
        conn.execute("INSERT INTO store_metadata VALUES ('migration_id','unknown')")
        conn.execute("INSERT INTO store_metadata VALUES ('migration_progress',?)",(canonical_json({'phase':'unknown'}),))
        conn.execute("UPDATE store_metadata SET value='999' WHERE key='source_next_append'")
        conn.commit();conn.close()
        with self.assertRaises(SchemaMismatchError):
            Store.open(path,authority='owner',expected_domains=self.domains)

    def test_completion_bridge_preserves_exact_effect_checks_with_history_capture(self):
        from dataclasses import replace
        from tests.test_completion_project_refresh import CompletionProjectRefreshTests
        fixture=CompletionProjectRefreshTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.refresh()
        reader=fixture.owner.graph.reader;lookup=type(reader).__getattr__;events=reader.list_events
        counts=fixture.f.f.store.consumer().snapshot_counts()
        for variant in ('invalid_history','unknown_effect'):
            def changed(*,stream=None):
                rows=events(stream=stream)
                if stream=='work:'+fixture.project.id:
                    return tuple(replace(e,effects={**e.effects,**({'history_summary':{'schema':'forged'}} if variant=='invalid_history' else {'unqualified_fact':True})})
                        if e.event_type=='work.project.supervision-transferred' else e for e in rows)
                return rows
            with self.subTest(variant=variant),patch.object(type(reader),'__getattr__',lambda obj,name:changed if obj is reader and name=='list_events' else lookup(obj,name)):
                with self.assertRaises(PermissionError):
                    fixture.commands.finish_task(fixture.finish)
            self.assertEqual(fixture.f.f.store.consumer().snapshot_counts(),counts)

    def test_physical_schema_tampering_is_rejected(self):
        self.domains = self.store.registered_domains()
        path=self.store.path; self.store.close()
        conn=sqlite3.connect(path);conn.execute('CREATE INDEX surprise ON events(event_type)');conn.close()
        with self.assertRaises(SchemaMismatchError):
            Store.open(path,authority='owner',expected_domains=self.domains)


if __name__ == '__main__':
    unittest.main()

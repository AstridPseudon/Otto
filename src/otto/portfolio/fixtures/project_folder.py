"""Disposable B02 owner proof. Run with PYTHONPATH=src python this_file.py."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from herzchen.content import DocumentAssociation, domain_contribution as content_contribution
from herzchen.content.model import document_path
from herzchen.contracts import ResourceRef, ReferenceBinding
from otto.portfolio.document_navigation import ProjectDocumentOperations
from otto.portfolio.documents import ProjectDocumentReader
from otto.portfolio.project_folder import ProjectFolderOwner, validate_files
from otto.portfolio.fixtures.project_authoring import ProjectAuthoringProof


class ProjectFolderProof(ProjectAuthoringProof):
    # Keep the predecessor regression separate, while reusing its real owner.
    def import_files(self, key='import', files=None):
        result = self.portfolio.import_folder(actor='owner', request_id=key,
            project_json={'title': 'Files', 'outcome': 'Research'},
            files=files or {'README.md': '[topic](docs/research/topic.md)',
                           'docs/research/topic.md': '[index](../../README.md)'})
        self.assertEqual(result['outcome'], 'imported', result)
        return result

    def reader(self):
        from herzchen.content.packets import ContextPacketService
        return ProjectDocumentReader(sheet_reader=self.owner.sheet, content_reader=self.owner.content,
            visibility_reader=ContextPacketService(self.store.domain_handler((content_contribution(),))))

    def doc(self, ref, path):
        rows = self.reader().list_documents(ref, actor=self.owner.owner_actor)['documents']
        return next(row for row in rows if any(member['key'] == path for member in row['memberships']))

    def checkin(self, opened, changes, key='check-in'):
        return self.portfolio.check_in_project(opened['project_ref'], session_id=opened['session_id'],
            project_json=opened['project_json'], document_changes=changes, actor='owner', request_id=key)

    def test_nested_roundtrip_relative_navigation_and_raw_provenance(self):
        imported = self.import_files()
        ref = imported['project_ref']
        reader = self.reader()
        from herzchen.content.packets import ContextPacketService
        nav = ProjectDocumentOperations(document_reader=reader, context_reader=ContextPacketService(self.store.domain_handler((content_contribution(),))), authoring=object())
        source = self.doc(ref, 'docs/research/topic.md')['document_ref']
        resolved = nav.resolve_relative_link(ref, source, '../../README.md', actor=self.owner.owner_actor)
        self.assertEqual(resolved['outcome'], 'resolved', resolved)
        self.assertEqual(resolved['resolved_path'], 'README.md')
        escaped = nav.resolve_relative_link(ref, source, '../../../outside.md', actor=self.owner.owner_actor)
        self.assertEqual(escaped['reason'], 'relative_link_escapes_project')
        opened = self.open(ref)
        checkout = self.root / opened['session_id']
        self.assertEqual((checkout/'docs/research/topic.md').read_text(), opened['document_files']['docs/research/topic.md'])
        exported = self.portfolio.export_folder(ref, actor='owner', request_id='export')
        self.assertEqual(exported['files'], opened['document_files'])
        self.assertFalse(exported['provenance']['canonical_transfer'])
        reimported = self.portfolio.import_folder(actor='owner',request_id='roundtrip',
            project_json=exported['project_json'],files=exported['files'])
        self.assertEqual(reimported['outcome'],'imported',reimported)
        project = self.owner.graph.get(ResourceRef.from_dict(ref))
        self.assertEqual(project.lifecycle.value, 'pending')
        self.assertNotIn('otto_transfer', project.payload['metadata'])
        for row in reader.list_documents(ref, actor=self.owner.owner_actor)['documents']:
            self.assertEqual(row['document']['import_mode'], 'owned')
            self.assertIsNone(row['document'].get('source_ref'))
        replay = self.import_files()
        self.assertEqual(replay['project_ref'], ref)
        changed = self.portfolio.import_folder(actor='owner', request_id='import',
            project_json={'title': 'Files', 'outcome': 'Research'}, files={'README.md': 'changed'})
        self.assertEqual(changed['outcome'], 'conflict', changed)
        self.restart()
        self.assertEqual(self.portfolio.export_folder(ref, actor='owner', request_id='export')['files'], exported['files'])

    def test_edit_add_move_unlink_identity_history_and_replay(self):
        imported = self.import_files()
        ref = imported['project_ref']
        original = self.doc(ref, 'docs/research/topic.md')['document_ref']
        opened = self.open(ref)
        changes = [{'operation':'edit','path':'docs/research/topic.md','content':'Updated'},
                   {'operation':'add','path':'docs/new.md','content':'New'}]
        finished = self.checkin(opened, changes)
        self.assertEqual(finished['outcome'], 'finished', finished)
        replay = self.checkin(opened, changes)
        self.assertEqual(replay['outcome'], 'replayed', replay)
        changed = self.checkin(opened, [{'operation':'edit','path':'docs/research/topic.md','content':'different'}])
        self.assertEqual(changed['outcome'], 'conflict', changed)
        self.assertEqual(self.doc(ref, 'docs/research/topic.md')['document_ref'], original)
        history = self.reader().list_revisions(ref, original, actor=self.owner.owner_actor)
        self.assertEqual(len(history['revisions']), 2, history)
        opened2 = self.open(finished['project_ref'], 'open2')
        moved = self.checkin(opened2, [{'operation':'move','path':'docs/research/topic.md',
                                     'to_path':'docs/design/topic.md'}], 'move')
        self.assertEqual(moved['outcome'], 'finished', moved)
        self.assertEqual(self.doc(ref, 'docs/design/topic.md')['document_ref'], original)
        opened3 = self.open(moved['project_ref'], 'open3')
        unlinked = self.checkin(opened3, [{'operation':'unlink','path':'docs/design/topic.md'}], 'unlink')
        self.assertEqual(unlinked['outcome'], 'finished', unlinked)
        head = self.owner.content.read(ResourceRef.from_dict(original))
        self.assertEqual(head['current_revision']['revision'], 'rev-2')
        self.assertEqual(self.owner.content.read(ResourceRef.from_dict({**original,'revision':'rev-1'}))['content'], '[index](../../README.md)')

    def test_interrupted_import_recovers_exact_receipts_after_restart(self):
        original = ProjectFolderOwner._folder_link
        def interrupt(owner, project, document, path, actor, key, **options):
            if path == 'docs/research/topic.md':
                raise RuntimeError('fixture interruption before second link')
            return original(owner, project, document, path, actor, key, **options)
        with patch.object(ProjectFolderOwner, '_folder_link', interrupt):
            partial = self.portfolio.import_folder(actor='owner', request_id='import',
                project_json={'title':'Files','outcome':'Research'},
                files={'README.md':'[topic](docs/research/topic.md)',
                       'docs/research/topic.md':'[index](../../README.md)'})
        self.assertEqual(partial['outcome'], 'partial', partial)
        self.assertEqual(len(partial['committed']), 1)
        self.assertEqual(len(partial['pending']), 1)
        self.assertEqual(len(partial['child_receipts']), 3)
        self.restart()
        complete = self.import_files()
        self.assertEqual(complete['project_ref'], partial['project_ref'])
        self.assertEqual(len(self.reader().list_documents(complete['project_ref'], actor=self.owner.owner_actor)['documents']),2)
        self.assertEqual(complete['committed'][0]['receipts'],partial['committed'][0]['receipts'])

    def test_partial_checkin_and_stale_document_are_honest(self):
        ref = self.import_files()['project_ref']
        opened = self.open(ref)
        # A concurrent head advances without changing the project sheet.
        document = self.doc(ref,'docs/research/topic.md')['document_ref']
        from herzchen.content import ContentDocument, ContentRevision
        from herzchen.contracts import TransactionContext
        typed = ContentDocument.from_dict(self.owner.content.read(ResourceRef.from_dict(document))['document'])
        revision = ContentRevision(typed.ref,'rev-2','Concurrent',self.owner.owner_actor,parent_revision='rev-1')
        self.owner.content.execute(self.owner.content.build_append_revision(
            TransactionContext(self.owner.owner_actor,'concurrent','c'*64,expected_revision='rev-1'),typed,revision))
        changes = [{'operation':'edit','path':'README.md','content':'Committed first'},
                   {'operation':'edit','path':'docs/research/topic.md','content':'Must not overwrite'}]
        result = self.checkin(opened, changes)
        self.assertEqual(result['outcome'],'partial', result)
        self.assertEqual(len(result['committed']),1)
        self.assertEqual(len(result['pending']),1)
        self.assertEqual(result['pending'][0]['base_revision_ref']['revision'],'rev-1')
        self.assertEqual(result['pending'][0]['observed_current_revision_ref']['revision'],'rev-2')
        self.assertEqual(result['committed'][0]['revision_ref']['revision'],'rev-2')
        self.assertTrue(result['project_sheet_pending'])
        self.assertFalse(result['atomic'])
        self.assertEqual(self.owner.content.read(ResourceRef.from_dict(document))['revision']['content'],'Concurrent')
        self.restart()
        replay = self.checkin(opened, changes)
        self.assertEqual(replay['outcome'],'partial', replay)
        self.assertEqual(replay['committed'],result['committed'])
        self.assertTrue((self.root/opened['session_id']/'README.md').exists())
        released = self.portfolio.release_project(ref, session_id=opened['session_id'],actor='owner',request_id='release-stale')
        self.assertEqual(released['outcome'],'released',released)
        current = self.owner.graph.get(ResourceRef.from_dict(ref)).ref
        rebased = self.open(current,'rebase-open')
        repaired = self.checkin(rebased,[changes[1]],'rebase-check-in')
        self.assertEqual(repaired['outcome'],'finished',repaired)
        self.assertEqual(repaired['committed'][0]['document_ref'],document)
        self.assertEqual(repaired['committed'][0]['revision_ref']['revision'],'rev-3')
        self.assertEqual(self.doc(ref,'README.md')['current_revision_ref']['revision'],'rev-2')

    def test_interrupted_checkin_after_link_reports_receipts_and_resumes(self):
        ref = self.import_files()['project_ref']
        opened = self.open(ref)
        original = ProjectFolderOwner._folder_link
        def interrupt(owner, project, document, path, actor, key, **options):
            if options.get('unlink'):
                raise RuntimeError('fixture interruption before unlink')
            return original(owner, project, document, path, actor, key, **options)
        changes = [{'operation':'move','path':'docs/research/topic.md','to_path':'docs/design/topic.md'}]
        with patch.object(ProjectFolderOwner, '_folder_link', interrupt):
            partial = self.checkin(opened, changes)
        self.assertEqual(partial['outcome'], 'partial', partial)
        self.assertEqual(len(partial['committed']), 0)
        self.assertEqual(len(partial['child_receipts']), 1)
        self.restart()
        completed = self.checkin(opened, changes)
        self.assertEqual(completed['outcome'], 'finished', completed)
        self.assertEqual(completed['committed'][0]['receipts'][0], partial['child_receipts'][0])
        self.assertEqual(len(self.reader().list_documents(ref, actor=self.owner.owner_actor)['documents']), 2)

    def test_concurrent_destination_is_not_overwritten_and_retired_path_reused(self):
        ref = self.import_files()['project_ref']
        opened = self.open(ref)
        first = self.checkin(opened, [{'operation':'unlink','path':'docs/research/topic.md'}], 'unlink')
        again = self.open(first['project_ref'], 'open2')
        reused = self.checkin(again,[{'operation':'add','path':'docs/research/topic.md','content':'New identity'}], 'reuse')
        self.assertEqual(reused['outcome'], 'finished', reused)
        self.assertNotEqual(reused['committed'][0]['document_ref'], first['committed'][0]['document_ref'])
        opened3 = self.open(reused['project_ref'], 'open3')
        created = self.portfolio.create_document(ref,actor='owner',request_id='other-doc',content='Other')
        self.portfolio.link_document(ResourceRef('d01-fixture','work.project',ref['id']),
            created['document_ref'],actor='owner',request_id='other-link',namespace='project.files',key='docs/other.md')
        result = self.checkin(opened3,[{'operation':'add','path':'docs/other.md','content':'Overwrite'}], 'collision')
        self.assertEqual(result['outcome'], 'partial', result)
        self.assertEqual(result['committed'], [])
        self.assertEqual(self.owner.content.read(ResourceRef.from_dict(created['document_ref']))['revision']['content'], 'Other')

    def test_real_parser_import_export_and_document_actions(self):
        import argparse
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_client import add_manager_journey_parsers
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        from otto.portfolio.execution_host import _nested_capability
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest='command',required=True))
        server = SimpleNamespace(owner=self.owner, portfolio=self.portfolio,state={},due_port=None,_execution=lambda **kw:None)
        service = ManagerJourneyService(server=server,host=None,run_path=self.root,workspace=self.root,
            authoring_authorizer=lambda request:self.owner.owner_actor)
        command = vars(parser.parse_args(['project-authoring','--operation','import-folder',
            '--request-key','parser-import','--project-json','{"title":"Parser"}',
            '--files','{"docs/nested/a.md":"Actual parser"}']))
        self.assertEqual(_nested_capability(command),'admitted')
        result = service(command)
        self.assertEqual(result['outcome'],'imported',result)
        export = vars(parser.parse_args(['project-authoring','--operation','export-folder',
            '--request-key','parser-export','--project-ref',json.dumps(result['project_ref'])]))
        self.assertEqual(_nested_capability(export),'admitted')
        self.assertEqual(service(export)['files'],{'docs/nested/a.md':'Actual parser'})
        opened = self.open(result['project_ref'])
        command = vars(parser.parse_args(['project-authoring','--operation','check-in',
            '--request-key','parser-finish','--project-ref',json.dumps(result['project_ref']),
            '--project-json',json.dumps(opened['project_json']),'--session-id',opened['session_id'],
            '--document-changes','[{"operation":"edit","path":"docs/nested/a.md","content":"Edited"}]']))
        self.assertEqual(_nested_capability(command),'admitted')
        self.assertEqual(service(command)['outcome'],'finished')

    def test_genuine_transfer_is_distinct_and_interrupted_transfer_resumes(self):
        from herzchen.kernel.store import Store
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        from otto.portfolio.herzchen_binding import HerzchenBindingConfig, FiniteWorkOperations
        from otto.portfolio.intake import OttoPortfolio
        ref = self.import_files()['project_ref']
        rows = self.reader().list_documents(ref,actor=self.owner.owner_actor)['documents']
        snapshot = self.portfolio.export_project(ref,actor='owner',request_id='transfer-export',
            document_refs=[row['document_ref'] for row in rows],association_refs=[member['association_ref']
                for row in rows for member in row['memberships']])['snapshot']
        target_path = self.root/'target.sqlite'
        target_store = Store.create(target_path,authority='target-fixture')
        target_store.register_domain_handler(self.domains)
        target = PortfolioOwnerBootstrap(target_store,binding=HerzchenBindingConfig('target-fixture','fixture-credential'),owner_actor='owner')
        portfolio = OttoPortfolio(target.consumer_operations())
        original = FiniteWorkOperations._link_document
        def interrupt(operations,payload,**options):
            if options['request_id'].endswith(':document-link:1'):
                raise RuntimeError('fixture transfer interruption')
            return original(operations,payload,**options)
        with patch.object(FiniteWorkOperations,'_link_document',interrupt):
            partial = portfolio.import_project(snapshot,actor='owner',request_id='transfer')
        self.assertEqual(partial['outcome'],'partial',partial)
        target_store.close()
        target_store = Store.open(target_path,authority='target-fixture',expected_domains=tuple(sorted(self.domains,key=lambda domain:domain.domain_id)))
        self.addCleanup(target_store.close)
        target = PortfolioOwnerBootstrap(target_store,binding=HerzchenBindingConfig('target-fixture','fixture-credential'),owner_actor='owner')
        portfolio = OttoPortfolio(target.consumer_operations())
        completed = portfolio.import_project(snapshot,actor='owner',request_id='transfer')
        self.assertEqual(completed['outcome'],'imported',completed)
        self.assertEqual(completed['source_ref'],ref)
        provenance = completed['content_provenance']
        self.assertTrue(all(row['content_equal'] for row in provenance['restored_documents']),provenance)
        replay = portfolio.import_project(snapshot,actor='owner',request_id='transfer')
        self.assertEqual(replay['outcome'],'replayed',replay)
        transfer_checkout = portfolio.checkout_project(completed['project_ref'],actor='owner',request_id='transfer-open')
        self.assertEqual(transfer_checkout['outcome'],'opened',transfer_checkout)
        moved = portfolio.check_in_project(completed['project_ref'],actor='owner',request_id='transfer-move',
            session_id=transfer_checkout['session_id'],project_json=transfer_checkout['project_json'],
            document_changes=[{'operation':'move','path':'docs/research/topic.md','to_path':'docs/moved.md'}])
        self.assertEqual(moved['outcome'],'finished',moved)
        bad = dict(snapshot)
        bad.pop('source_ref')
        import hashlib
        bad.pop('snapshot_digest')
        bad['snapshot_digest'] = hashlib.sha256(json.dumps(bad,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        rejected = portfolio.import_project(bad,actor='owner',request_id='bad-transfer')
        self.assertEqual(rejected['outcome'],'rejected',rejected)
        self.assertIsNone(target.graph.reader.get_receipt('bad-transfer'))

    def test_committed_append_before_return_is_visible_and_exactly_recovered(self):
        from otto.portfolio.owner_bootstrap import _CreateAndOpenOwnerEngine
        ref = self.import_files()['project_ref']
        opened = self.open(ref)
        original = _CreateAndOpenOwnerEngine._json_mapping
        def interrupt(value, field):
            if field == 'receipt' and value.get('operation') == 'dat.content.revision.append':
                raise RuntimeError('fixture interruption after append before response')
            return original(value, field)
        changes = [{'operation':'edit','path':'README.md','content':'Committed before lost response'}]
        with patch.object(_CreateAndOpenOwnerEngine,'_json_mapping',staticmethod(interrupt)):
            partial = self.checkin(opened, changes)
        self.assertEqual(partial['outcome'],'partial',partial)
        self.assertEqual(partial['pending'][0]['observed_current_revision_ref']['revision'],'rev-2')
        self.assertEqual(len(partial['child_receipts']),1)
        self.restart()
        complete = self.checkin(opened, changes)
        self.assertEqual(complete['outcome'],'finished',complete)
        self.assertEqual(complete['committed'][0]['receipts'][0],partial['child_receipts'][0])
        self.assertEqual(self.doc(ref,'README.md')['current_revision_ref']['revision'],'rev-2')

    def test_symlink_checkout_is_rejected_and_relative_hrefs_are_decoded(self):
        from herzchen.content.packets import ContextPacketService
        ref = self.import_files(files={'README.md':'[space](docs/space%20name.md)',
            'docs/space name.md':'Target'})['project_ref']
        nav = ProjectDocumentOperations(document_reader=self.reader(),authoring=object(),
            context_reader=ContextPacketService(self.store.domain_handler((content_contribution(),))))
        source = self.doc(ref,'README.md')['document_ref']
        self.assertEqual(nav.resolve_relative_link(ref,source,'docs/space%20name.md#heading',
            actor=self.owner.owner_actor)['outcome'],'resolved')
        self.assertEqual(nav.resolve_relative_link(ref,source,'#heading',actor=self.owner.owner_actor)['document_ref'],source)
        for href in ('%2fetc/passwd','docs/%5cfile.md','docs/%00file.md'):
            self.assertEqual(nav.resolve_relative_link(ref,source,href,actor=self.owner.owner_actor)['outcome'],'unavailable')
        def unsafe(checkout, initial_bytes, **values):
            path = self.root / checkout.session_id
            path.mkdir()
            (path/'project.json').write_bytes(initial_bytes)
            (path/'docs').symlink_to(self.root,target_is_directory=True)
            return {'path':str(path),'registered_files':['project.json']}
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        from otto.portfolio.herzchen_binding import HerzchenBindingConfig
        from otto.portfolio.intake import OttoPortfolio
        owner = PortfolioOwnerBootstrap(self.store,binding=HerzchenBindingConfig('d01-fixture','fixture-credential'),
            owner_actor='owner',materializer=unsafe)
        result = OttoPortfolio(owner.consumer_operations()).checkout_project(ref,actor='owner',request_id='unsafe-open')
        self.assertEqual(result['outcome'],'saved_project_edit_not_opened',result)
        self.assertFalse((self.root/'space name.md').exists())

    def test_interruption_after_project_creation_preserves_parent_replay(self):
        files = {'README.md':'Frozen input'}
        with patch.object(ProjectFolderOwner,'_folder_apply',side_effect=RuntimeError('fixture interruption after project creation')):
            partial = self.portfolio.import_folder(actor='owner',request_id='early-import',
                project_json={'title':'Early'},files=files)
        self.assertEqual(partial['outcome'],'partial',partial)
        self.assertEqual(len(partial['committed']),1)
        self.assertEqual(partial['pending'],['README.md'])
        self.restart()
        changed = self.portfolio.import_folder(actor='owner',request_id='early-import',
            project_json={'title':'Early'},files={'README.md':'Changed'})
        self.assertEqual(changed['outcome'],'conflict',changed)
        completed = self.portfolio.import_folder(actor='owner',request_id='early-import',
            project_json={'title':'Early'},files=files)
        self.assertEqual(completed['outcome'],'imported',completed)
        self.assertEqual(completed['project_ref'],partial['project_ref'])

    def test_unsafe_paths_are_rejected_before_import(self):
        for path in ('../escape.md','/abs.md','docs//x.md','docs/./x.md','C:/x.md','docs\\x.md','https://x', 'docs/%2e.md'):
            with self.subTest(path=path):
                result = self.portfolio.import_folder(actor='owner', request_id='unsafe',
                    project_json={'title':'Files'}, files={path:'bad'})
                self.assertEqual(result['outcome'],'rejected', result)
                self.assertIsNone(self.owner.graph.reader.get_receipt('unsafe:project'))
        for files in ({'a.md':'a','A.md':'b'}, {'docs':'a','docs/x.md':'b'}, {'project.json':'bad'}):
            with self.assertRaises(ValueError):
                validate_files(files)
        with self.assertRaises(ValueError):
            DocumentAssociation(ResourceRef('d01-fixture','work.project','p'),'other.namespace',
                'nested/file.md',ReferenceBinding(ResourceRef('d01-fixture','dat.content.document','d'),'current'))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ProjectFolderProof(name) for name in ProjectFolderProof.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

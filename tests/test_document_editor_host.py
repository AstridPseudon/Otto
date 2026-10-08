"""Connected buffer host/owner ingress tests using real scoped DAT/EDT."""
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest

from herzchen.content.packets import domain_contribution as packets
from herzchen.domains.assessment.module import contribution as assessment
from otto.portfolio.fixtures import project_authoring
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.execution_host import ExecutionHost
from herzchen.contracts import ResourceRef


class DocumentEditorHostTests(unittest.TestCase):
    def setUp(self):
        self.f = project_authoring.ProjectAuthoringProof()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.store.register_domain_handler((packets(), assessment()))
        self.project = {k:v for k,v in self.f.create().items() if k != "revision"}
        binding = self.f.owner.binding
        self.owner = PortfolioOwnerBootstrap(self.f.store, binding=binding, owner_actor='owner',
            project_read_grant=ProjectReadGrant(binding.authenticated_actor('owner'),
                (self.project['id'],), 'fixture-owner', '1'))
        created = self.f.portfolio.create_document(self.project, actor='owner', request_id='doc',
            content={'text': 'Opening'}, access_mode='write', document_id='editor-doc')
        self.doc = {k: v for k, v in created['document_ref'].items() if k != 'revision'}
        self.f.portfolio.link_document(self.project, self.doc, actor="owner", request_id="link", access_mode="read")
        self.project = {k:v for k,v in self.project.items() if k != "revision"}
        self.now = 1000.0
        self.editor = self.compose()
        self.ingress = OwnerAuthoringIngress(actor=self.owner.owner_actor, owner_actor=self.owner.owner_actor,
            directory=self.f.root/'ipc')
        server = SimpleNamespace(owner=self.owner, portfolio=self.f.portfolio, state={},
            due_port=None, _execution=lambda **kw: None, document_editor=self.editor)
        self.service = ManagerJourneyService(server=server, host=None, run_path=self.f.root,
            workspace=self.f.root, authoring_authorizer=self.ingress.authorize)

    def compose(self):
        return DocumentEditorHost(owner=self.owner, directory=self.f.root/'editor',
            secret=b's'*32, clock=lambda:self.now)

    def request(self, operation, key, **values):
        return dict(command='document-authoring', operation=operation, request_key=key, **values)

    def call(self, request):
        receipt=self.ingress.publish({'schema':self.ingress.schema, 'request':request})
        result=self.service(request)
        Path(receipt['request_path']).unlink(missing_ok=True)
        json.dumps(result)
        return result

    def open(self, **values):
        opened = self.call(self.request('open','open',project_ref=self.project, document_ref=self.doc, **values))
        self.assertEqual(opened['outcome'],'opened',opened)
        self.session=dict(project_ref=self.project, document_ref=self.doc, handle=opened['handle'])
        return opened

    def head(self):
        return self.owner.content.read(ResourceRef.from_dict(self.doc))['current_revision']['revision']

    def test_real_capture_default_idle_and_serialized_poll_publish_one_revision(self):
        opened=self.open()
        self.assertEqual(opened['inactivity_seconds'],900)
        head=self.head()
        saved=self.call(self.request('save','save',**self.session, editor_buffer={'content':{'text':'Edited'}}))
        self.assertTrue(saved['buffer_captured'])
        self.assertEqual(saved['last_content_edit'],1000)
        self.assertEqual(self.head(),head)
        self.now=1010
        unchanged=self.call(self.request('save','unchanged',**self.session, editor_buffer={'content':{'text':'Edited'}}))
        self.assertEqual(unchanged['last_content_edit'],1000)
        self.assertEqual(self.editor.poll_idle(self.ingress),[])
        self.now=1900
        receipts=self.editor.poll_idle(self.ingress)
        self.assertEqual(len(receipts),1)
        self.assertEqual(self.editor.poll_idle(self.ingress),[])
        request=json.loads(Path(receipts[0]['request_path']).read_text())
        checked=self.service(request)
        self.assertEqual(checked['outcome'],'checked_in',checked)
        self.assertTrue(checked['notification']['durable'])
        self.assertFalse(checked['cleanup_pending'])
        self.assertEqual(checked['publication']['assignment_adoption'],'not_performed')
        self.assertNotEqual(self.head(),head)
        self.assertFalse((Path(opened['handle']['checkout_path'])/'document.json').exists())

    def test_restart_does_not_publish_uncaptured_buffer_and_explicit_discard_preserves_head(self):
        opened=self.open(inactivity_seconds=0)
        head=self.head()
        self.call(self.request('save','save',**self.session,editor_buffer={'content':{'text':'Draft'}}))
        restarted=self.compose()
        self.service.server.document_editor=restarted
        self.assertEqual(restarted.poll_idle(self.ingress),[])
        inventory=self.call(self.request('inventory','inventory'))
        entry=next(s for s in inventory['sessions'] if s['session_id']==opened['handle']['session_id'])
        self.assertTrue(entry['recovery_pending'])
        self.assertNotIn('token',entry)
        resumed=self.call(self.request('resume','resume',**self.session))
        self.assertFalse(resumed['idle_armed'])
        inhibited=self.call(self.request('idle-close','uncaptured',**self.session))
        self.assertEqual(inhibited['outcome'],'writer_active',inhibited)
        discarded=self.call(self.request('discard','discard',**self.session))
        self.assertTrue(discarded['nonpublishing'])
        self.assertEqual(self.head(),head)
        # Canonical retained draft remains available by explicit owner recovery.
        recovered=self.call(self.request('recover','recover',session_id=opened['handle']['session_id']))
        json.dumps(recovered)

    def test_foreign_grant_handle_and_external_checkout_change_cannot_publish(self):
        opened=self.open(inactivity_seconds=0)
        request=self.request('save','save',**self.session,editor_buffer={'content':{'text':'Draft'}})
        with self.assertRaises(PermissionError): self.service(request)
        self.call(request)
        forged=dict(self.session);forged['handle']={**forged['handle'],'token':'foreign'}
        with self.assertRaises(Exception): self.call(self.request('status','forged',**forged))
        changed={**self.session,'project_ref':{**self.project,'id':'foreign'}}
        with self.assertRaises(PermissionError): self.call(self.request('status','foreign-project',**changed))
        head=self.head()
        (Path(opened['handle']['checkout_path'])/'document.json').write_text('{"content":"outside editor"}')
        result=self.call(self.request('idle-close','external-change',**self.session))
        self.assertEqual(result['outcome'],'writer_active',result)
        self.assertEqual(self.head(),head)

    def test_explicit_finish_and_invalid_buffer_have_the_same_guarded_boundary(self):
        opened=self.open()
        head=self.head()
        self.call(self.request('save','invalid-save',**self.session,
            editor_buffer={'schema_revision':'unsupported','content':'invalid'}))
        rejected=self.call(self.request('finish','invalid-finish',**self.session))
        self.assertFalse(rejected['dat_revision_advanced'],rejected)
        self.assertEqual(self.head(),head)
        self.assertTrue((Path(opened['handle']['checkout_path'])/'document.json').exists())
        self.call(self.request('discard','invalid-discard',**self.session))
        reopened=self.call(self.request('open','reopen',project_ref=self.project,document_ref=self.doc))
        self.session['handle']=reopened['handle']
        self.call(self.request('save','valid-save',**self.session,
            editor_buffer={'content':{'text':'Explicit'}}))
        finished=self.call(self.request('finish','valid-finish',**self.session))
        self.assertEqual(finished['outcome'],'finished',finished)
        self.assertFalse(finished['cleanup_pending'])
        self.assertTrue(finished['notification']['durable'])
        self.assertEqual(finished['publication']['dat_revision_ref']['revision'],self.head())
        self.assertFalse((Path(reopened['handle']['checkout_path'])/'document.json').exists())

    def test_existing_wait_loop_publishes_then_owner_lane_executes_real_idle_attempt(self):
        self.open(inactivity_seconds=0)
        self.call(self.request('save','save',**self.session,editor_buffer={'content':{'text':'From poll'}}))
        host=ExecutionHost(directory=self.f.root/'ipc', handler=self.service)
        host.start();self.addCleanup(host.close)
        stop=threading.Event()
        loop=threading.Thread(target=host.wait_until_stopped,args=(stop.is_set,),
            kwargs={'poll_seconds':.01,'idle_poll':lambda:self.editor.poll_idle(self.ingress)})
        loop.start()
        deadline=time.monotonic()+3
        response=None
        while time.monotonic()<deadline:
            for path in (self.f.root/'ipc').glob('response-*.json'):
                value=json.loads(path.read_text())
                if value.get('outcome')=='checked_in': response=value;break
            if response:break
            time.sleep(.01)
        stop.set();loop.join(3)
        self.assertIsNotNone(response)
        self.assertTrue(response['durable_checked_in'])

if __name__=='__main__':unittest.main()

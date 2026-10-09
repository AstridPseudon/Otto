"""External root capability joins real portfolio direction without native impersonation."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import threading
import time
from otto.portfolio.execution_host import ExecutionHost, _nested_capability
from otto.portfolio.identity_context import HostIngress
from otto.portfolio.tests import test_portfolio_direction as portfolio_fixtures
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress

class ExternalOwnerContextTests(unittest.TestCase):
    def setUp(self):
        self.f=portfolio_fixtures.PortfolioDirectionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        root,self.subject,self.pin,self.project=self.f.setup_portfolio();self.root=root
        self.state={'orchestrator_assignment_ref':root.ref.to_dict()}
        self.ingress=OwnerAuthoringIngress(actor=self.f.owner.owner_actor,owner_actor=self.f.owner.owner_actor,directory=self.f.path.parent/'owner-context-ipc')
        self.service=ManagerJourneyService(server=SimpleNamespace(owner=self.f.owner,state=self.state,_execution=None,portfolio=None,due_port=None),host=None,run_path=self.f.path.parent,workspace=self.f.path.parent,authoring_authorizer=self.ingress.authorize)
    def call(self,operation,**kwargs):
        request={'command':'owner-context','operation':operation,'request_key':'root-'+operation,**kwargs}
        receipt=self.ingress.publish({'schema':self.ingress.schema,'request':request})
        return self.service(json.loads(Path(receipt['request_path']).read_text()))
    def test_exact_external_owner_identity_and_adopted_context(self):
        request={'command':'owner-context','operation':'whoami','request_key':'root-read'}
        with self.assertRaises(PermissionError):self.service(request)
        identity=self.call('whoami');self.assertEqual(identity['assignment_ref'],self.root.ref.to_dict());self.assertEqual(identity['role'],'orchestrator');self.assertFalse(identity['native_process_identity_claimed']);self.assertFalse(identity['native_delivery_verified'])
        context=self.call('effective-context');self.assertEqual(context['assignment_direction']['effective_ref'],self.pin.to_dict());self.assertEqual(len(context['shared_role_resources']),1)
        self.assertEqual(context['shared_role_resources'][0]['content']['supporting_refs'],[self.pin.to_dict()])
    def test_no_self_claimed_identity_subject_or_ungranted_restart(self):
        request={'command':'owner-context','operation':'whoami','request_key':'root-read'}
        for field,value in [('actor','owner'),('assignment_ref',self.root.ref.to_dict()),('native_id','claimed'),('pid',123)]:
            with self.subTest(field=field),self.assertRaises(PermissionError):self.ingress.publish({'schema':self.ingress.schema,'request':{**request,field:value}})
        self.ingress.publish({'schema':self.ingress.schema,'request':request})
        restarted=OwnerAuthoringIngress(actor=self.f.owner.owner_actor,owner_actor=self.f.owner.owner_actor,directory=self.f.path.parent/'owner-context-ipc')
        with self.assertRaises(PermissionError):restarted.authorize(request)
        self.state['orchestrator_assignment_ref']={**self.root.ref.to_dict(),'revision':'rev-999'}
        with self.assertRaises(PermissionError):self.call('whoami',request_key='stale-root')
    def test_foreign_owner_and_nonportfolio_assignment_are_rejected(self):
        request={'command':'owner-context','operation':'whoami','request_key':'foreign-root'}
        self.ingress.publish({'schema':self.ingress.schema,'request':request})
        self.service.authoring_authorizer=lambda _:self.f.binding.authenticated_actor('foreign')
        with self.assertRaises(PermissionError):self.service(request)
        self.service.authoring_authorizer=self.ingress.authorize
        self.state['orchestrator_assignment_ref']=self.f.assignment.ref.to_dict()
        with self.assertRaises(PermissionError):self.service(request)
    def test_native_wait_admits_only_exact_owner_reads_without_releasing_custody(self):
        before=self.f.store.consumer().snapshot_counts()
        begun,finished=threading.Event(),threading.Event()
        observed,errors={},[]
        def handler(request):
            if request['command']=='start-manager':
                def transport():
                    begun.set()
                    if not finished.wait(5):raise RuntimeError('test transport did not settle')
                    return {'outcome':'succeeded'}
                return ExecutionHost.external_call(transport)
            return self.service(request)
        host=ExecutionHost(directory=self.ingress.directory,handler=handler)
        def submit():
            try:
                self.assertTrue(begun.wait(2))
                requests=[{'command':'owner-context','operation':op,'request_key':'during-'+op}
                          for op in ('whoami','effective-context','direction-read','direction-history')]
                requests += [{'command':'owner-context','operation':'direction-draft','request_key':'held-draft',
                              'content':{'text':'must remain held'},'expected_revision':'rev-1'},
                             {'command':'owner-context','operation':'direction-adopt','request_key':'held-adopt',
                              'document_ref':self.pin.to_dict(),'expected_binding_ref':{}}]
                for request in requests:
                    published=self.ingress.publish({'schema':self.ingress.schema,'request':request})
                    response=Path(published['response_path'])
                    deadline=time.monotonic()+3
                    while not response.exists() and time.monotonic()<deadline:time.sleep(.005)
                    self.assertTrue(response.exists(),request)
                    observed[request['operation']]=json.loads(response.read_text())
                forged={'command':'owner-context','operation':'whoami','request_key':'ungranted-read'}
                path=self.ingress.directory/'request-deadbeef.json';path.write_text(json.dumps(forged))
                response=self.ingress.directory/'response-deadbeef.json'
                deadline=time.monotonic()+3
                while not response.exists() and time.monotonic()<deadline:time.sleep(.005)
                self.assertTrue(response.exists());observed['forged']=json.loads(response.read_text())
            except BaseException as exc:errors.append(exc)
            finally:finished.set()
        thread=threading.Thread(target=submit);thread.start()
        outer=host._dispatch({'command':'start-manager'},ingress=HostIngress('file-ipc',self.ingress.directory/'outer'))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        if errors:raise errors[0]
        self.assertEqual(outer['outcome'],'succeeded')
        for op in ('whoami','effective-context','direction-read','direction-history'):
            self.assertEqual(observed[op]['outcome'],'read',observed[op]);self.assertTrue(observed[op]['read_only'])
        for op in ('direction-draft','direction-adopt'):
            self.assertEqual(observed[op]['outcome'],'held');self.assertFalse(observed[op]['effects_started'])
        self.assertEqual(observed['forged']['outcome'],'error');self.assertEqual(observed['forged']['error'],'PermissionError')
        self.assertEqual(self.f.store.consumer().snapshot_counts(),before)
        self.assertEqual(_nested_capability({'command':'owner-context','operation':'whoami','request_key':'x','assignment_ref':self.root.ref.to_dict()}),'held')
    def test_owned_draft_scope_adoption_keeps_assignment_effective_pin_honest(self):
        before=self.call('direction-read');root_before=self.f.owner.assignments.get(self.root.ref)
        drafted=self.call('direction-draft',content={'text':'Coordinate the authorised canonical queue; references, not a duplicated project roster.'},expected_revision='rev-1')
        after_draft=self.call('direction-read',request_key='after-draft');self.assertEqual(after_draft['assignment_direction']['effective_ref'],self.pin.to_dict())
        self.assertTrue(after_draft['scope_direction']['pending_scope_adoption'])
        pin=drafted['draft']['revision_ref'];adopted=self.call('direction-adopt',document_ref=pin,expected_binding_ref=before['scope_direction']['binding_ref'])
        self.assertFalse(adopted['assignment_resources_refreshed']);after=self.call('direction-read',request_key='after-adopt')
        self.assertEqual(after['scope_direction']['effective_ref'],pin);self.assertEqual(after['assignment_direction']['assignment_adopted_ref'],self.pin.to_dict())
        self.assertEqual(self.f.owner.assignments.get(self.root.ref).ref,root_before.ref)
        self.assertEqual(self.f.owner.graph.get(self.project.ref).payload['lifecycle'],'pending')

if __name__=='__main__':unittest.main()

"""Real disposable owner and issued secondary policy; synthetic native adapter."""
from copy import deepcopy
from types import SimpleNamespace
from dataclasses import replace
import hashlib
import unittest
from herzchen.contracts import ResourceRef
from herzchen.content import ContentRevision
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.orchestrator_client import OrchestratorAdmissions, ScopedOrchestratorClient
from otto.portfolio.supervisor_direction_client import SupervisorDirectionAuthoring, OPERATIONS, scoped_supervisor_handler
from otto.portfolio.manager_journey_service import manager_head, ManagerJourneyService
from tests.test_execution_application import ExecutionApplicationTests

class SupervisorDirectionClientTests(unittest.TestCase):
 def setUp(self):
  self.f=f=ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  from unittest.mock import patch
  from herzchen.domains.work.assignments import ResponsibilityAssignments
  original_assign=ResponsibilityAssignments.assign
  def assign_with_root_chat(port,*args,**kwargs):
   if kwargs.get('role')=='orchestrator':kwargs.setdefault('session',{'host':'codex','native_id':'own-root-chat'})
   return original_assign(port,*args,**kwargs)
  with patch.object(ResponsibilityAssignments,'assign',assign_with_root_chat):
   main=f.owner.assignments.assign(ResourceRef(f.store.authority,'wrk.portfolio','shared'),role='orchestrator',principal='manager',logical_request_key='main')
  self.main=main
  from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
  from otto.portfolio.herzchen_binding import ProjectReadGrant
  f.owner=PortfolioOwnerBootstrap(f.store,binding=f.binding,owner_actor='manager',portfolio_ref=main.scope,main_assignment_ref=main.ref,project_read_grant=ProjectReadGrant(f.actor,(f.project.id,),'test-host','v1'))
  f.app=f.owner.execution_application(due_port=f.port,adapter=f.app.runtime.adapter,clock=f.app.clock)
  admissions=OrchestratorAdmissions(f.owner,main_assignment_ref=main.ref.to_dict(),generation=1)
  req=admissions.request(conversation_ref={'host':'codex','native_id':'secondary-chat'},requested_project_ids=[f.project.id],request_key='secondary')
  self.binding=admissions.admit(actor=f.owner.owner_actor,request_ref=req['request_ref'],project_ids=[f.project.id],operations=sorted(OPERATIONS),request_key='secondary-policy')
  self.root=f.owner.assignments.get(self.binding['assignment_ref'])
  f.owner.consumer_operations().execute('work.orchestrator.projects.attach',{'target_assignment_ref':self.root.ref.to_dict(),'target_assignment_revision':self.root.revision,'target_assignment_generation':1,'projects':[{'project_ref':f.project.ref.to_dict(),'project_version':f.project.version,'assignment_ref':None,'assignment_revision':None,'assignment_generation':None}]},request_id='supervision',actor='manager')
  f.project=f.owner.graph.get(f.project.ref)
  delivery=SimpleNamespace(describe=lambda project:{'assignment_ref':self.root.ref.to_dict(),'generation':self.root.generation,'principal':self.root.principal,'conversation_ref':self.root.session})
  f.app=f.owner.execution_application(due_port=f.port,adapter=f.app.runtime.adapter,clock=f.app.clock,issue_delivery=delivery)
  manager,guide,mandate=f.role_handles('manager','manager','manager-session')
  subject=ResourceRef.from_dict(manager.payload['responsibility_ref'])
  self.content={'schema':'herzchen.instructions.v1','name':'DIRECTION','entrypoint':'MANAGER.md','instructions':'Existing directive','bundle_digest':hashlib.sha256(b'Existing directive').hexdigest(),'export_manifest_digest':'fixture','required':True,'supporting_refs':[]}
  doc=f.app.portfolio.create_document(f.project.ref.to_dict(),actor='manager',request_id='direction-doc',document_id='direction',role='direction',content=self.content)
  self.pin=doc['record']['payload']['current_revision']
  surface=f.owner.direction_surface();bind=surface.initial_bind(subject,{**self.pin,'revision':None},logical_request_key='direction-bind')
  surface.update(subject,self.pin,expected_binding_ref=bind['binding_ref'],logical_request_key='initial-direction')
  self.manager_base_name='shared-database-read-index-adoption-20261011-v1-onboarding-BASE@rev-1'
  before=f.owner.content.read(ResourceRef.from_dict(guide));body=deepcopy(before['content']);body['name']=self.manager_base_name;body['supporting_refs']=[self.pin]
  document=__import__('herzchen.content',fromlist=['ContentDocument']).ContentDocument.from_dict(f.owner.content.read(ResourceRef.from_dict({**guide,'revision':None}))['document'])
  rev=ContentRevision(document.ref,'rev-2',body,f.actor,parent_revision=guide['revision'])
  from herzchen.contracts import TransactionContext
  tx=TransactionContext(f.actor,'BASE-body',hashlib.sha256(b'BASE-body').hexdigest(),expected_revision=guide['revision'])
  f.owner.content.execute(f.owner.content.build_append_revision(tx,document,rev))
  resources=[{'resource_ref':rev.ref.to_dict(),'resource_name':self.manager_base_name,'content_digest':validate_instruction_content(body),'required':True}]
  manager=f.owner.assignments.adopt_resources(manager.ref,resources=resources,expected_revision=manager.revision,expected_generation=1,logical_request_key='BASE-adopt',actor=f.actor)
  prepared=f.app.prepare_role(role='manager',project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),assignment_ref=manager.ref.to_dict(),generation=1,mandate_ref=mandate,context_refs=(rev.ref.to_dict(),mandate),request_key='settled-manager',instruction='Inspect task',model='gpt-test',reasoning='high',profile='workspace-write',native_session_id='manager-session')
  launched=f.app.start(schedule_id=prepared['schedule_id']);self.assertEqual(launched['outcome'],'succeeded',launched)
  self.anchor=f.port.read_due(prepared['schedule_id'])
  self.worker=f.app.assign_worker(**{**f.request(),'request_key':'active-worker'})
  self.worker_before=deepcopy(f.port.read_due(self.worker['schedule_id']))
  self.state={'project_ref':f.project.ref.to_dict(),'assignment_ref':manager.ref.to_dict(),'manager_generation':1,'manager':'manager','requested_model':'gpt-test','requested_reasoning':'high','schedule_id':prepared['schedule_id'],'guide_ref':rev.ref.to_dict(),'mandate_ref':mandate}
  server=SimpleNamespace(owner=f.owner,state=self.state,due_port=f.port,_save_state=lambda:None)
  self.service=SimpleNamespace(server=server,_current_manager_schedule=lambda:manager_head(self.state),_execution=lambda **kw:f.app)
  self.service._current_manager_schedule=lambda:ManagerJourneyService._current_manager_schedule(self.service)
  facade=scoped_supervisor_handler(services=[self.service],fallback=lambda request,root:(_ for _ in ()).throw(PermissionError('unsupported fixed-view operation')))
  self.client=ScopedOrchestratorClient(owner=f.owner,binding=self.binding,handlers={op:facade for op in OPERATIONS})
 def call(self,operation,payload=None,key='read'):
  return self.client.call({'operation':operation,'project_id':self.f.project.id,'request_key':key,'request':payload})
 def draft_and_intent(self):
  read=self.call('supervisor-direction-read');content={**self.content,'instructions':'Updated project direction','bundle_digest':hashlib.sha256(b'Updated project direction').hexdigest()}
  draft=self.call('supervisor-direction-draft',{'content':content,'expected_revision':read['direction']['latest_ref']['revision']},'draft')
  latest=self.call('supervisor-direction-read')
  return {'document_ref':draft['draft']['revision_ref'],'expected_direction_ref':latest['direction']['latest_ref'],'expected_binding_ref':latest['direction']['binding_ref'],'expected_manager_ref':latest['manager_assignment_ref'],'expected_manager_generation':1,'expected_schedule_id':latest['manager_schedule_id']}
 def test_draft_adopt_exact_receipt_callback_replay_worker_unchanged(self):
  intent=self.draft_and_intent();calls=len(self.f.provider.calls)
  result=self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  self.assertEqual(result['outcome'],'adopted');self.assertFalse(result['provider_called'])
  self.assertEqual(result['delivery'],'prepared-not-started');self.assertEqual(self.f.port.read_due(self.worker['schedule_id']),self.worker_before)
  self.assertEqual(self.f.port.read_due(self.anchor['schedule_id']),self.anchor)
  self.assertEqual(len(self.f.provider.calls),calls)
  read=self.call('supervisor-direction-read');self.assertEqual(read['direction']['effective_ref'],intent['document_ref'])
  self.assertEqual(read['direction_surface'],'manager-responsibility')
  self.assertEqual(read['supervisor_instruction_adoption'],'not-read-or-changed-by-this-operation')
  self.assertNotEqual(result['manager_assignment_ref'],intent['expected_manager_ref'])
  self.assertEqual(result['manager_assignment_ref']['id'],intent['expected_manager_ref']['id'])
  self.assertEqual(self.state['schedule_id'],result['continuation']['schedule_id'])
  self.assertEqual(self.state['guide_ref'],result['BASE_ref'])
  self.assertEqual(self.state['mandate_ref'],self.f.port.read_due(self.state['schedule_id'])['target']['mandate_ref'])
  counts=self.f.store.consumer().snapshot_counts()
  replay=self.call('supervisor-direction-adopt-and-continue',intent,'apply');self.assertEqual(replay['outcome'],'replayed')
  self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
  self.assertEqual(replay['continuation']['schedule_id'],result['continuation']['schedule_id'])
  # Real application native fixture: delivered new BASE + directive, one start.
  delivered=self.f.app.start(schedule_id=result['continuation']['schedule_id']);self.assertEqual(delivered['outcome'],'succeeded',delivered)
  self.assertEqual(len(self.f.provider.calls),calls+1)
  again=self.f.app.start(schedule_id=result['continuation']['schedule_id']);self.assertEqual(again['outcome'],'replayed');self.assertEqual(len(self.f.provider.calls),calls+1)

 def test_current_owner_root_client_composes_supervisor_facade(self):
  from tempfile import TemporaryDirectory
  from otto.portfolio.root_direction_client import install_owner_root_client
  # Move this exact manager project under the current owner root. A one-project
  # scope is sufficient when its canonical supervision join is current.
  project=self.f.owner.graph.get(ResourceRef.from_dict(self.state['project_ref']))
  relation=project.payload['metadata']['otto_orchestrator']
  transfer=self.f.owner.orchestration_port.transfer_supervision(actor=self.f.owner.owner_actor,
   request_id='move-supervisor-project-to-owner-root',portfolio_ref=self.main.scope.to_dict(),
   project_ref=project.ref.to_dict(),expected_project_revision=project.ref.revision,
   expected_project_version=project.version,current_assignment_ref=relation['assignment_ref'],
   current_assignment_revision=relation['assignment_revision'],current_assignment_generation=relation['generation'],
   target_assignment_ref=self.main.ref.to_dict(),target_assignment_revision=self.main.ref.revision,
   target_assignment_generation=self.main.generation,overlap_acknowledged=True)
  self.state['project_ref']=transfer['project_ref']
  self.state['orchestrator_assignment_ref']=self.main.ref.to_dict()
  fallback=lambda request,root: (_ for _ in ()).throw(PermissionError('unsupported fixed-view operation'))
  project_handler=scoped_supervisor_handler(services=[self.service],fallback=fallback)
  ids=[self.f.project.id]
  with TemporaryDirectory() as directory:
   locator,client=install_owner_root_client(service=self.service,directory=directory,
    conversation_ref=self.main.session,request_key='main-root-supervisor-scope',project_ids=ids,
    project_handler=project_handler)
   self.assertTrue(OPERATIONS.issubset(set(locator['binding']['operations'])))
   request=lambda op,payload,key:{'operation':op,'project_id':self.f.project.id,'request_key':key,'request':payload}
   read=client.call(request('supervisor-direction-read',{},'main-read'))
   self.assertEqual(read['outcome'],'read');self.assertEqual(read['manager_assignment_ref'],self.state['assignment_ref'])
   revised={**self.content,'instructions':'Main-root scoped update',
    'bundle_digest':hashlib.sha256(b'Main-root scoped update').hexdigest()}
   draft=client.call(request('supervisor-direction-draft',{'content':revised,
    'expected_revision':read['direction']['latest_ref']['revision']},'main-draft'))
   current=client.call(request('supervisor-direction-read',{},'main-readback'))
   intent={'document_ref':draft['draft']['revision_ref'],'expected_binding_ref':current['direction']['binding_ref'],
    'expected_direction_ref':current['direction']['latest_ref'],'expected_manager_ref':current['manager_assignment_ref'],
    'expected_manager_generation':current['manager_generation'],'expected_schedule_id':current['manager_schedule_id']}
   calls=len(self.f.provider.calls)
   result=client.call(request('supervisor-direction-adopt-and-continue',intent,'main-adopt'))
   self.assertEqual(result['outcome'],'adopted');self.assertEqual(result['delivery'],'prepared-not-started')
   self.assertFalse(result['provider_called']);self.assertEqual(len(self.f.provider.calls),calls)
   self.assertEqual(self.f.port.read_due(self.worker['schedule_id']),self.worker_before)
   self.assertEqual(self.state['assignment_ref']['id'],intent['expected_manager_ref']['id'])
   self.assertEqual(self.state['schedule_id'],result['continuation']['schedule_id'])
   with self.assertRaises(PermissionError):
    client.call({'operation':'supervisor-direction-read','project_id':'foreign-project','request_key':'main-foreign'})
 def test_stale_foreign_changed_key_and_current_head_rejected_before_effect(self):
  intent=self.draft_and_intent();counts=self.f.store.consumer().snapshot_counts()
  for change in [{'expected_manager_generation':2},{'expected_schedule_id':'foreign'},{'expected_manager_ref':{**intent['expected_manager_ref'],'revision':'rev-0'}},{'document_ref':{**intent['document_ref'],'id':'foreign'}}]:
   with self.assertRaises((PermissionError,ValueError)):self.call('supervisor-direction-adopt-and-continue',{**intent,**change},'bad')
   self.assertEqual(counts,self.f.store.consumer().snapshot_counts())
  with self.assertRaises(PermissionError):self.client.call({'operation':'supervisor-direction-read','project_id':'foreign','request_key':'bad'})
  with self.assertRaises(PermissionError):self.call('supervisor-direction-draft',{'content':self.content,'expected_revision':self.pin['revision'],'actor':'manager'},'actor')
  self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  with self.assertRaises(PermissionError):self.call('supervisor-direction-adopt-and-continue',{**intent,'expected_manager_generation':2},'apply')
 def test_unsettled_manager_holds_without_adoption(self):
  intent=self.draft_and_intent();self.f.port.save_due(self.anchor['schedule_id'],{**self.anchor,'completion_state':'unknown'},request_id='unknown-manager',expected_version=self.anchor['version'])
  counts=self.f.store.consumer().snapshot_counts();result=self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  self.assertEqual(result['outcome'],'held');self.assertFalse(result['canonical_effect_recorded']);self.assertEqual(counts,self.f.store.consumer().snapshot_counts())

 def test_commit_before_state_publication_loss_reopens_exact_receipt(self):
  from unittest.mock import patch
  from herzchen.kernel.store import Store
  from otto.attention import issue_store_due_record_port, due_record_contribution
  from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
  from otto.portfolio.herzchen_binding import ProjectReadGrant
  intent=self.draft_and_intent();old=deepcopy(self.state);calls=len(self.f.provider.calls)
  with patch.object(self.service.server,'_save_state',side_effect=OSError('publication failed')):
   with self.assertRaises(OSError):self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  committed=self.f.owner.assignments.get(old['assignment_ref']);self.assertNotEqual(committed.ref.to_dict(),old['assignment_ref'])
  # Actual canonical Store close/reopen; local state reconstructs old disk bytes.
  main=self.main.ref
  adapter=self.f.app.runtime.adapter;clock=self.f.app.clock
  domains=tuple(sorted(self.f.store.registered_domains(),key=lambda d:d.domain_id))
  self.f.store.close();self.f.store=Store.open(self.f.path,authority='execution-owner',expected_domains=domains)
  self.f.owner=PortfolioOwnerBootstrap(self.f.store,binding=self.f.binding,owner_actor='manager',portfolio_ref=self.root.scope,main_assignment_ref=main,project_read_grant=ProjectReadGrant(self.f.actor,(self.f.project.id,),'test-host','v1'))
  self.f.port=issue_store_due_record_port(self.f.store.domain_handler((due_record_contribution(),)),self.f.actor)
  delivery=SimpleNamespace(describe=lambda project:{'assignment_ref':self.root.ref.to_dict(),'generation':1,'principal':self.root.principal,'conversation_ref':self.root.session})
  self.f.app=self.f.owner.execution_application(due_port=self.f.port,adapter=adapter,clock=clock,issue_delivery=delivery)
  self.state.clear();self.state.update(old);self.service.server.owner=self.f.owner;self.service.server.due_port=self.f.port
  self.client.owner=self.f.owner;facade=SupervisorDirectionAuthoring(self.service);self.client.handlers={op:facade.call for op in OPERATIONS}
  before=self.f.store.consumer().snapshot_counts();result=self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  self.assertEqual(result['outcome'],'replayed');self.assertEqual(self.state['assignment_ref'],committed.ref.to_dict())
  self.assertEqual(manager_head(self.state),result['continuation']['schedule_id']);self.assertEqual(before,self.f.store.consumer().snapshot_counts());self.assertEqual(len(self.f.provider.calls),calls)
  self.assertEqual(self.state['schedule_id'],result['continuation']['schedule_id'])
  self.assertEqual(self.state['guide_ref'],result['BASE_ref'])
  readiness=self.f.app.runtime.prepare_execution_readiness(due=self.f.app._read(self.state['schedule_id']))
  self.assertIsInstance(readiness,dict)
  self.assertEqual(self.f.port.read_due(self.worker['schedule_id']),self.worker_before)

 def test_rollback_after_staged_head_leaves_state_and_canonical_rows_unchanged(self):
  from unittest.mock import patch
  from otto.portfolio.manager_journey_service import advance_manager_head
  intent=self.draft_and_intent();before=deepcopy(self.state);counts=self.f.store.consumer().snapshot_counts()
  def fail(staged,**kw):
   advance_manager_head(staged,**kw)
   raise RuntimeError('failure after staged head')
  with patch('otto.portfolio.manager_journey_service.advance_manager_head',side_effect=fail):
   with self.assertRaises(RuntimeError):self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  self.assertEqual(self.state,before);self.assertEqual(counts,self.f.store.consumer().snapshot_counts())
  self.assertEqual(self.f.port.read_due(self.worker['schedule_id']),self.worker_before)
  result=self.call('supervisor-direction-adopt-and-continue',intent,'apply');self.assertEqual(result['outcome'],'adopted')

 def test_large_existing_direction_and_finite_bound_preserve_content(self):
  support=self.f.app.portfolio.create_document(self.f.project.ref.to_dict(),actor='manager',request_id='supporting-doc',document_id='supporting',role='guide',content={**self.content,'name':'SUPPORT'})['record']['payload']['current_revision']
  content={**self.content,'instructions':'x'*21000,'bundle_digest':hashlib.sha256(('x'*21000).encode()).hexdigest(),'supporting_refs':[support]}
  read=self.call('supervisor-direction-read');draft=self.call('supervisor-direction-draft',{'content':content,'expected_revision':read['direction']['latest_ref']['revision']},'large')
  self.assertEqual(self.f.owner.content.read(ResourceRef.from_dict(draft['draft']['revision_ref']))['content'],content)
  current=self.call('supervisor-direction-read')
  intent={'document_ref':draft['draft']['revision_ref'],'expected_direction_ref':current['direction']['latest_ref'],'expected_binding_ref':current['direction']['binding_ref'],'expected_manager_ref':current['manager_assignment_ref'],'expected_manager_generation':current['manager_generation'],'expected_schedule_id':current['manager_schedule_id']}
  applied=self.call('supervisor-direction-adopt-and-continue',intent,'large-adopt')
  self.assertEqual(applied['direction_ref'],draft['draft']['revision_ref'])
  self.assertEqual(self.f.owner.content.read(ResourceRef.from_dict(applied['direction_ref']))['content']['supporting_refs'],[support])
  self.assertEqual(self.f.port.read_due(self.worker['schedule_id']),self.worker_before)
  too_large={**content,'instructions':'y'*66000,'bundle_digest':hashlib.sha256(('y'*66000).encode()).hexdigest()}
  counts=self.f.store.consumer().snapshot_counts()
  with self.assertRaises(ValueError):self.call('supervisor-direction-draft',{'content':too_large,'expected_revision':draft['draft']['revision_ref']['revision']},'oversize')
  self.assertEqual(counts,self.f.store.consumer().snapshot_counts())

 def test_original_worker_callback_after_adoption_uses_new_manager_contract(self):
  intent=self.draft_and_intent();result=self.call('supervisor-direction-adopt-and-continue',intent,'apply')
  worker=self.f.app.start(schedule_id=self.worker['schedule_id']);self.assertEqual(worker['outcome'],'succeeded',worker)
  # A result arriving while the new manager callback is still prepared merges
  # into that one head; original worker and parent identities are unchanged.
  callback=self.f.app.continue_manager_from_worker(manager_schedule_id=result['continuation']['schedule_id'],worker_schedule_id=worker['schedule_id'],execute=False)
  self.assertEqual(callback['schedule_id'],result['continuation']['schedule_id'])
  due=self.f.port.read_due(callback['schedule_id']);self.assertEqual(due['host_evidence']['worker_result_continuation']['worker_assignment_ref'],self.worker['assignment_ref'])
  before=len(self.f.provider.calls);run=self.f.app.start(schedule_id=due['schedule_id']);self.assertEqual(run['outcome'],'succeeded',run)
  self.assertEqual(len(self.f.provider.calls),before+1);self.assertIn('Updated project direction',self.f.provider.calls[-1])
  self.assertEqual(self.f.port.read_due(self.anchor['schedule_id']),self.anchor)

 def test_foreign_or_stale_issued_supervisor_and_first_binding_are_not_adoption(self):
  for change in ({'generation':2},{'conversation_ref':{'host':'codex','native_id':'foreign'}},{'principal':'foreign'}):
   client=ScopedOrchestratorClient(owner=self.f.owner,binding={**self.binding,**change},handlers=self.client.handlers)
   with self.assertRaises(PermissionError):client.call({'operation':'supervisor-direction-read','project_id':self.f.project.id,'request_key':'bad'})
  # A first binding is outside this scoped facade; no unrelated scope/BASE
  # is silently made mandatory while a worker is retained.
  from unittest.mock import patch
  surface=self.f.owner.direction_surface()
  with patch.object(surface,'read',return_value={'state':'unbound'}),patch.object(type(self.f.owner),'direction_surface',return_value=surface):
   result=self.call('supervisor-direction-draft',{'content':self.content,'expected_revision':None},'first')
  self.assertEqual(result['outcome'],'held');self.assertFalse(result['canonical_effect_recorded'])

 def test_in_flight_worker_survives_directive_and_delayed_terminal_callback(self):
  import threading, time
  from pathlib import Path
  from otto.portfolio.execution_host import ExecutionHost
  f=self.f
  f.provider.work_started,f.provider.work_release=threading.Event(),threading.Event()
  host=ExecutionHost(directory=Path(f.temporary.name)/'directive-ipc',handler=lambda request:None,bounded_transports=True)
  host.start()
  try:
   completion=host._owner_request(lambda:f.app.start(schedule_id=self.worker['schedule_id']))
   self.assertTrue(f.provider.work_started.wait(5))
   active=host._owner_request(lambda:deepcopy(f.port.read_due(self.worker['schedule_id'])))
   self.assertEqual(active['stop_state'],'active');self.assertIsNotNone(active['in_flight_request'])
   self.assertIn('gateway_attempt',active['host_evidence']);self.assertFalse(completion.done)
   assignment=host._owner_request(lambda:deepcopy(f.owner.assignments.get(active['assignment_ref'])))
   self.assertTrue(host._owner_request(lambda:host._executions[self.worker['schedule_id']]['running']))
   intent=host._owner_request(self.draft_and_intent)
   adopted=host._owner_request(lambda:self.call('supervisor-direction-adopt-and-continue',intent,'active-apply'))
   self.assertEqual(adopted['outcome'],'adopted');self.assertFalse(adopted['provider_called'])
   self.assertEqual(host._owner_request(lambda:f.port.read_due(self.worker['schedule_id'])),active)
   self.assertEqual(host._owner_request(lambda:f.owner.assignments.get(active['assignment_ref'])),assignment)
   self.assertFalse(completion.done)
   f.provider.work_release.set()
   deadline=time.monotonic()+5
   while not completion.done and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(completion.done);self.assertIsNone(completion.error)
   self.assertEqual(completion.value['outcome'],'succeeded')
   self.assertEqual(completion.value['assignment_ref'],active['assignment_ref'])
   # The original worker parent remains the historical anchor. The real
   # service selector uses the adopted current manager head for its callback.
   self.assertEqual(active['target'].get('manager_schedule_id'),self.worker_before['target'].get('manager_schedule_id'))
   current=host._owner_request(self.service._current_manager_schedule)
   self.assertEqual(current,adopted['continuation']['schedule_id'])
   callback=host._owner_request(lambda:f.app.continue_manager_from_worker(manager_schedule_id=current,worker_schedule_id=self.worker['schedule_id'],execute=False))
   self.assertEqual(callback['schedule_id'],adopted['continuation']['schedule_id'])
   duplicate=host._owner_request(lambda:f.app.continue_manager_from_worker(manager_schedule_id=callback['schedule_id'],worker_schedule_id=self.worker['schedule_id'],execute=False))
   self.assertEqual(duplicate['schedule_id'],callback['schedule_id'])
   before=len(f.provider.calls)
   delivered=host._owner_request(lambda:f.app.start(schedule_id=callback['schedule_id']))
   deadline=time.monotonic()+5
   while not delivered.done and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(delivered.done);self.assertIsNone(delivered.error)
   self.assertEqual(delivered.value['outcome'],'succeeded');self.assertEqual(len(f.provider.calls),before+1)
   self.assertIn('Updated project direction',f.provider.calls[-1])
  finally:
   f.provider.work_release.set();host.close()

if __name__=='__main__':unittest.main()

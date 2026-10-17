"""Completed reconstruction retains immutable supports; new delivery stays current."""
from copy import deepcopy
import hashlib,json,unittest
from herzchen.content import ContentDocument,ContentRevision
from herzchen.contracts import ResourceRef,TransactionContext,canonical_json
from otto.portfolio.role_context import supporting_context,RoleContextError
from tests import test_execution_application as fixture

class CompletedWorkerSupportTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.ExecutionApplicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.port=self.f.app.portfolio.operations.content_port
  created=self.f.app.portfolio.create_document(self.f.project.ref.to_dict(),actor='manager',request_id='immutable-support-create',document_id='old-run-config',role='run_configuration',content={'text':'delivered version'})
  self.pin=created['record']['payload']['current_revision']
  self.base={'resource_ref':dict(self.pin,id='BASE'),'content':{'supporting_refs':[self.pin]}}
  self.original=supporting_context(self.base,self.port)
  stable=ResourceRef(self.pin['authority'],self.pin['kind'],self.pin['id'])
  current=self.port.read(stable);doc=ContentDocument.from_dict(current['document']);revision=ContentRevision(stable,'rev-2',{'text':'future version'},self.f.actor,parent_revision=self.pin['revision']);payload={'document':doc,'revision':revision}
  ctx=TransactionContext(self.f.actor,'immutable-support-change',hashlib.sha256(canonical_json(payload).encode()).hexdigest(),expected_revision=self.pin['revision'])
  self.port.execute(self.port.build_append_revision(ctx,doc,revision))
 def test_completed_exact_support_reconstructs_original_bytes_not_new_head(self):
  result=supporting_context(self.base,self.port,completed_support_refs=(self.pin,))
  self.assertEqual(result,self.original)
  self.assertEqual(self.port.read(ResourceRef(self.pin['authority'],self.pin['kind'],self.pin['id']))['current_revision']['revision'],'rev-2')
 def test_new_delivery_still_rejects_stale_head(self):
  with self.assertRaisesRegex(RoleContextError,'missing or stale'):
   supporting_context(self.base,self.port)
 def test_different_pin_does_not_authorize_stale_support_and_missing_exact_rejects(self):
  with self.assertRaisesRegex(RoleContextError,'missing or stale'):
   supporting_context(self.base,self.port,completed_support_refs=({**self.pin,'id':'other'},))
  missing={**self.pin,'revision':'rev-404'};base=deepcopy(self.base);base['content']['supporting_refs']=[missing]
  with self.assertRaises(RoleContextError):supporting_context(base,self.port,completed_support_refs=(missing,))

class CompletedNativeSupportGateTests(unittest.TestCase):
 def fixture(self):
  from types import SimpleNamespace
  brief={'instruction_contract':{},'context':{'supporting_context':[{'ref':{'authority':'owner','kind':'dat.content.document','id':'support','revision':'rev-1'}}]}}
  authorization={'brief_sha256':hashlib.sha256(json.dumps(brief,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
  evidence={'owner_delivery_authorization':authorization}
  parsed={'task_bound_evidence':evidence,'model':'gpt-test','reasoning':'high'}
  verifier=SimpleNamespace(observe_context=lambda *a,**kw:parsed)
  result={'context_digest_verified':True,'outcome':'succeeded','resource_evidence':{'brief':brief},'task_bound_evidence':evidence,'observed_model':'gpt-test','observed_reasoning':'high','raw_result':{'work_envelope':{'exit_status':0,'host_evidence':{'otto_host_turn_context':{}}}}}
  return result,verifier,authorization
 def test_success_and_exact_setup_unknown_use_same_verified_native_pins(self):
  from otto.agents.owner_runtime import _completed_worker_support_refs
  result,verifier,authorization=self.fixture()
  pins=_completed_worker_support_refs(result,verifier,authorization);self.assertEqual(len(pins),1)
  result.update(outcome='unknown',unknown_reason='adopted operating setup changed before delivery')
  self.assertEqual(_completed_worker_support_refs(result,verifier,authorization),pins)
  result['unknown_reason']='transport_missing';self.assertEqual(_completed_worker_support_refs(result,verifier,authorization),())
 def test_wrong_authorization_native_and_failed_transport_reject(self):
  from otto.agents.owner_runtime import _completed_worker_support_refs,OwnerRoleRuntimeError
  for change in ('auth','native','transport'):
   with self.subTest(change=change):
    result,verifier,authorization=self.fixture()
    if change=='auth':authorization=dict(authorization,brief_sha256='0'*64)
    if change=='native':result['observed_model']='foreign'
    if change=='transport':result['raw_result']['work_envelope']['exit_status']=1
    with self.assertRaises(OwnerRoleRuntimeError):_completed_worker_support_refs(result,verifier,authorization)
 def test_other_provider_schema_keeps_original_current_brief_validation(self):
  from otto.agents.owner_runtime import _completed_worker_support_refs
  result,verifier,authorization=self.fixture();del result['raw_result']['work_envelope']['exit_status']
  self.assertEqual(_completed_worker_support_refs(result,verifier,authorization),())

class AcceptedCompletionCitationTests(unittest.TestCase):
 def setUp(self):
  from tests import test_evidence_wiring
  self.fixture=test_evidence_wiring.ProductionEvidenceWiringTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  self.f=self.fixture.f
  self.decision=ResourceRef.from_dict(self.fixture._accept_managed('citation'))
  decision_identity=self.f.store.get_identity(self.decision)
  self.evidence_ref=decision_identity.payload['evidence_refs'][0]
  pin=decision_identity.payload['evidence_digests'][0]
  self.digest=pin['digest'] if isinstance(pin,dict) else pin
  self.manager=self.fixture.manager
 def complete(self,refs=None,hashes=None,gates=None,key='citation-complete'):
  return self.fixture.owner.assignments.complete(self.f.task.ref,project=self.f.project.ref,assignment=self.manager.ref,
   actor=self.f.actor,logical_request_key=key,expected_generation=1,expected_project_revision=self.f.project.revision,
   expected_task_revision=self.f.task.revision,disposition='accepted',evidence_refs=refs or [self.evidence_ref],
   evidence_hashes=hashes if hashes is not None else {'native-result':self.digest},
   gate_refs=gates or [self.decision],candidate_ref=self.fixture.candidate)
 def unrelated_task_evidence(self):
  other_task=ResourceRef(self.f.actor.authority,'work.task','other-task')
  self.f.store.put_identity(other_task,{'record_type':'work.item','kind':'task','id':'other-task',
   'project_ref':self.f.project.ref,'title':'Other task','lifecycle':'active','dependencies':[],'metadata_namespaces':{}},version=0)
  other_assignment=self.fixture.owner.assignments.assign(scope=other_task,role='worker',principal='worker',logical_request_key='citation-other-assignment',actor=self.f.actor)
  return self.fixture.owner.assignments.append_result(other_assignment.ref,{'other':'task'},logical_request_key='citation-other-result',actor=self.f.actor).ref
 def test_refuses_another_tasks_retained_evidence(self):
  unrelated=self.unrelated_task_evidence()
  with self.assertRaisesRegex(Exception,'exactly match accepted decision evidence'):
   self.complete(refs=[self.evidence_ref,unrelated],key='citation-extra')
 def test_refuses_wrong_list_digest(self):
  with self.assertRaisesRegex(Exception,'digest|mismatch'):
   self.complete(hashes=['0'*64],key='citation-list-wrong')
 def test_refuses_wrong_mapping_digest(self):
  with self.assertRaisesRegex(Exception,'digest|mismatch'):
   self.complete(hashes={'native-result':'0'*64},key='citation-map-wrong')
 def test_refuses_missing_required_scope(self):
  plain=fixture.ExecutionApplicationTests();plain.setUp();self.addCleanup(plain.doCleanups)
  no_scope=plain.task
  no_assignment=plain.app.assignments.assign(scope=no_scope.ref,role='manager',principal='manager',logical_request_key='citation-no-scope-manager',actor=plain.actor)
  with self.assertRaisesRegex(Exception,'no required assessment scope'):
   plain.app.assignments.complete(no_scope.ref,project=plain.project.ref,assignment=no_assignment.ref,expected_generation=1,
    expected_project_revision=plain.project.revision,expected_task_revision=no_scope.revision,disposition='accepted',
    evidence_refs=[no_scope.ref],evidence_hashes=[self.digest],gate_refs=[no_scope.ref],candidate_ref=no_scope.ref,
    logical_request_key='citation-no-scope-complete',actor=plain.actor)
 def test_exact_accepted_pinned_evidence_succeeds(self):
  accepted=self.complete(hashes=[self.digest],key='citation-correct-list')
  self.assertEqual(accepted['outcome'],'completed',accepted)

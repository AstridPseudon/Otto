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

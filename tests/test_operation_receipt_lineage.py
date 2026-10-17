"""Bounded kernel receipt lineage on disposable real Store/nominal runtime."""
from dataclasses import replace
import tempfile,unittest
from pathlib import Path
from herzchen.contracts import AuthenticatedActor,ResourceRef,CommandReceipt,ReceiptStatus,CommandEnvelope,TransactionContext
from herzchen.kernel import Store
from herzchen.kernel.operations import OperationManager,OperationRequest,OperationState,UnknownOutcomeError,OperationError,request_digest
from herzchen.kernel.store import OperationOwnerCapability,RuntimeOperationOwner,RuntimeOperationReader

class ReceiptLineageTests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
  self.store=Store.create(Path(self.directory.name)/'owner.sqlite',authority='owner');self.addCleanup(self.store.close)
  self.actor=AuthenticatedActor('owner','actor','credential');self.manager=OperationManager(self.store)
 def request(self,key):return OperationRequest('fixture.operation','fixture.v1',ResourceRef('owner','adapter','fixture'),self.actor,key,'a'*64,{'task':key})
 def test_prepare_replay_transition_avoid_foreign_hydration_and_preserve_receipt_order(self):
  first=self.manager.prepare(self.request('first'));unrelated=self.manager.prepare(self.request('unrelated'))
  original=self.store._event_from_row;seen=[]
  def observe(row):
   seen.append(row['subject_id']);self.assertNotEqual(row['subject_id'],'unrelated','unrelated payload must not be hydrated');return original(row)
  self.store._event_from_row=observe
  repeated=self.manager.prepare(self.request('first'));self.assertEqual(repeated.operation_ref,first.operation_ref)
  final=self.manager.record_outcome(first,OperationState.COMMITTED,{'verified':True},transition_key='first-done')
  receipt=self.store.get_receipt('first-done');events=self.store.issue_operation_owner().event_lineage(receipt)
  self.assertEqual(tuple(x.event_id for x in events),receipt.event_ids);self.assertEqual(final.state,OperationState.COMMITTED)
  self.assertTrue(seen);self.assertTrue(all(x=='first'for x in seen))
 def test_empty_foreign_and_missing_receipt_ids_fail_closed_without_extra_events(self):
  first=self.manager.prepare(self.request('first'));receipt=self.store.get_receipt('first');owner=self.store.issue_operation_owner()
  original=self.store.list_events;calls=[]
  def observe(**kwargs):calls.append(kwargs);return original(**kwargs)
  self.store.list_events=observe
  self.assertEqual(owner.event_lineage(replace(receipt,event_ids=())),());self.assertEqual(calls,[])
  with self.assertRaises(ValueError):owner.event_lineage(replace(receipt,result_ref=ResourceRef('foreign','operation','first','rev-1')))
  self.assertEqual(calls,[])
  self.assertEqual(owner.event_lineage(replace(receipt,event_ids=('missing',))),());self.assertEqual(calls,[{'subjects':(receipt.result_ref,)}])
 def test_legacy_no_result_ref_uses_exact_target_and_keeps_durable_order(self):
  first=self.manager.prepare(self.request('first'));self.manager.record_outcome(first,OperationState.COMMITTED,{},transition_key='first-done');one=self.store.get_receipt('first');two=self.store.get_receipt('first-done');receipt=replace(one,result_ref=None,event_ids=two.event_ids+one.event_ids)
  events=self.store.issue_operation_owner().event_lineage(receipt);self.assertEqual(tuple(x.event_id for x in events),one.event_ids+two.event_ids)
 def test_legacy_prepared_payload_replays_and_can_be_claimed_once(self):
  request=self.request('legacy-prepared');target=ResourceRef('owner','operation','legacy-prepared');request=request.canonicalized(target)
  # Retained pre-EF1 Store envelope and event effects: neither carries
  # effect_ref, which is now derived from the operation identity.
  payload={
   'record_type':'operation','operation':request.operation,'schema_revision':request.schema_revision,
   'adapter_ref':request.adapter_ref.to_dict(),'request_actor':request.actor.to_dict(),
   'logical_request_key':request.logical_request_key,'request_digest':request.request_digest,
   'request_payload':dict(request.payload),'physical_invocation_ref':None,'external_owner_ref':None,
   'expected_revision':None,'expected_version':None,'edit_token':None,'correlation_id':None,
   'causation_id':None,'state':'prepared','result':{},
  }
  envelope=request.envelope(target,expected_revision=None,expected_version=0,edit_token=None,payload=payload)
  legacy_effects={
   'state':'prepared','result':{},'adapter_ref':request.adapter_ref.to_dict(),
   'request_actor':request.actor.to_dict(),'physical_invocation_ref':None,'external_owner_ref':None,
   'request_payload':dict(request.payload),'request_digest':request.request_digest,
   'expected_revision':None,'expected_version':None,'edit_token':None,'correlation_id':None,
   'causation_id':None,'version':1,
  }
  retained=self.store.mutate(envelope,event_type='operation.prepared',
   result_ref=ResourceRef('owner','operation','legacy-prepared','rev-1'),effects=legacy_effects,stream='operations')
  replayed=self.manager.prepare(self.request('legacy-prepared'))
  self.assertEqual(replayed.operation_ref,retained.result_ref)
  self.assertEqual(replayed.state,OperationState.PREPARED)
  self.assertEqual(replayed.effect_ref,ResourceRef('owner','effect','legacy-prepared'))
  self.assertTrue(replayed.receipt.replayed)
  started=self.manager.claim_start(replayed,transition_key='legacy-prepared-start')
  self.assertEqual(started.state,OperationState.STARTED)
  with self.assertRaises(UnknownOutcomeError):
   self.manager.claim_start(replayed,transition_key='legacy-prepared-second-start')
 def test_legacy_outcome_effects_replay(self):
  prepared=self.manager.prepare(self.request('legacy-outcome'))
  result={'verified':True}
  old_payload=dict(self.store.get_identity(prepared.operation_ref).payload)
  old_payload.pop('effect_ref',None)
  old_payload.update(state='committed',result=result)
  old_request=OperationRequest(
   'operation.outcome',prepared.request.schema_revision,prepared.request.adapter_ref,prepared.request.actor,
   'legacy-outcome-done',request_digest({'operation':'legacy-outcome','state':'committed','result':result}),
   {'original_request_payload':dict(prepared.request.payload),'state':'committed','result':result},
   prepared.request.physical_invocation_ref,prepared.request.external_owner_ref,
   prepared.request.expected_revision,prepared.request.expected_version,prepared.request.edit_token,
   prepared.request.correlation_id,prepared.request.causation_id,
  )
  old_envelope=old_request.envelope(prepared.operation_ref,
   expected_revision=prepared.operation_ref.revision,expected_version=prepared.version,edit_token=None,
   payload=old_payload)
  old_effects={
   'state':'committed','result':result,'adapter_ref':prepared.request.adapter_ref.to_dict(),
   'request_actor':prepared.request.actor.to_dict(),'physical_invocation_ref':None,
   'external_owner_ref':None,'request_payload':dict(prepared.request.payload),
   'request_digest':prepared.request.request_digest,'expected_revision':None,'expected_version':None,
   'edit_token':None,'correlation_id':None,'causation_id':None,'version':2,
  }
  retained=self.store.mutate(old_envelope,event_type='operation.outcome',
   result_ref=ResourceRef('owner','operation','legacy-outcome','rev-2'),
   effects=old_effects,stream='operations')
  # Replay must match the receipt created with the pre-EF1 envelope shape.
  replay=self.manager.record_outcome(prepared,OperationState.COMMITTED,{'verified':True},transition_key='legacy-outcome-done')
  self.assertEqual(replay.operation_ref,retained.result_ref)
  self.assertEqual(replay.state,OperationState.COMMITTED)
 def test_runtime_owner_existing_lineage_contract_is_preserved(self):
  self.manager.prepare(self.request('first'));receipt=self.store.get_receipt('first');store=self.store;calls=[]
  class Reader(RuntimeOperationReader):
   authority='owner'
   @property
   def domain_descriptor_digest(self):return store.domain_descriptor_digest
   def registered_domains(self):return store.registered_domains()
   def get_identity(self,*args):return store.get_identity(*args)
   def get_receipt(self,*args):return store.get_receipt(*args)
   def list_events(self,**kwargs):return store.list_events(**kwargs)
  class Owner(RuntimeOperationOwner):
   authority='owner';reader=Reader()
   @property
   def domain_descriptor_digest(self):return store.domain_descriptor_digest
   def registered_domains(self):return store.registered_domains()
   def transaction(self):return store.transaction()
   def mutate(self,*args,**kwargs):return store.mutate(*args,**kwargs)
   def get_identity(self,*args):return store.get_identity(*args)
   def get_receipt(self,*args):return store.get_receipt(*args)
   def list_events(self,**kwargs):raise AssertionError('no inventory substitute for nominal lineage')
   def lookup_replay(self,*args):return None
   def event_lineage(self,value):calls.append(value);return store.list_events(subjects=(value.result_ref,))
  owner=OperationOwnerCapability.issue_runtime(Owner());events=owner.event_lineage(receipt);self.assertEqual(calls,[receipt]);self.assertEqual(tuple(x.event_id for x in events),receipt.event_ids)
 def test_no_double_start_across_crash(self):
  prepared=self.manager.prepare(self.request('crash-start'))
  started=self.manager.claim_start(prepared,transition_key='crash-start-claim')
  self.assertEqual(started.state,OperationState.STARTED)
  effect_ref=started.effect_ref

  # Model a process stopping immediately after the durable claim returned.
  self.store.close()
  self.store=Store.open(Path(self.directory.name)/'owner.sqlite',authority='owner')
  self.addCleanup(self.store.close)
  recovered_manager=OperationManager(self.store)
  recovered=recovered_manager.get('crash-start')
  self.assertEqual(recovered.state,OperationState.UNKNOWN)
  self.assertEqual(recovered.effect_ref,effect_ref)
  invocations=[]
  def invoke_after_successful_claim(record,key):
   claimed=recovered_manager.claim_start(record,transition_key=key)
   invocations.append(claimed.effect_ref)
  with self.assertRaises(UnknownOutcomeError):
   invoke_after_successful_claim(recovered,'second-claim')
  with self.assertRaises(UnknownOutcomeError):
   invoke_after_successful_claim(recovered,'crash-start-claim')
  self.assertEqual(invocations,[])

 def test_unknown_is_held_not_retried(self):
  prepared=self.manager.prepare(self.request('unknown-held'))
  self.manager.claim_start(prepared,transition_key='unknown-held-claim')
  self.store.close()
  self.store=Store.open(Path(self.directory.name)/'owner.sqlite',authority='owner')
  self.addCleanup(self.store.close)
  recovered_manager=OperationManager(self.store)
  unknown=recovered_manager.get('unknown-held')
  self.assertEqual(unknown.state,OperationState.UNKNOWN)
  with self.assertRaises(UnknownOutcomeError):
   recovered_manager.claim_start(unknown,transition_key='unknown-held-retry')

 def test_process_gone_effect_unknown_reconciles_once(self):
  prepared=self.manager.prepare(self.request('gone-effect'))
  started=self.manager.claim_start(prepared,transition_key='gone-effect-start')
  effect_ref=started.effect_ref
  self.store.close()
  self.store=Store.open(Path(self.directory.name)/'owner.sqlite',authority='owner')
  self.addCleanup(self.store.close)
  manager=OperationManager(self.store)
  unknown=manager.get('gone-effect')
  self.assertEqual(unknown.state,OperationState.UNKNOWN)
  result={'verified':True,'output':'artifact-1'}

  def retain_proof(key,*,proof_effect_ref=effect_ref,result_value=result):
   payload={'effect_ref':proof_effect_ref.to_dict(),'state':'committed','result':result_value}
   target=ResourceRef('owner','effect-proof',key)
   envelope=CommandEnvelope('effect.proof','fnd-04.operation.v1',target,
    TransactionContext(self.actor,key,request_digest(payload),expected_version=0),payload)
   return self.store.mutate(envelope,event_type='effect.terminal',
    result_ref=ResourceRef('owner','effect-proof',key,'rev-1'),effects=payload,stream='effects')

  with self.assertRaises(OperationError):
   manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='missing-proof',transition_key='gone-effect-resolve-missing')
  self.assertEqual(manager.get('gone-effect').state,OperationState.UNKNOWN)
  retain_proof('foreign-proof',proof_effect_ref=ResourceRef('owner','effect','other'))
  with self.assertRaises(OperationError):
   manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='foreign-proof',transition_key='gone-effect-resolve-foreign')
  retain_proof('changed-proof',result_value={'verified':False})
  with self.assertRaises(OperationError):
   manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='changed-proof',transition_key='gone-effect-resolve-changed')
  self.assertEqual(manager.get('gone-effect').state,OperationState.UNKNOWN)

  retain_proof('valid-proof')
  original_identity=self.store.get_identity(ResourceRef('owner','operation','gone-effect'))
  altered_custody=replace(unknown.request,external_owner_ref=ResourceRef('owner','external-owner','forged'))
  forged_custody=replace(unknown,request=altered_custody)
  self.assertEqual(forged_custody.effect_ref,unknown.effect_ref)
  self.assertEqual(forged_custody.version,unknown.version)
  with self.assertRaises(UnknownOutcomeError):
   manager.resolve_unknown(forged_custody,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='valid-proof',transition_key='gone-effect-forged-custody')
  retained=manager.get('gone-effect')
  retained_identity=self.store.get_identity(ResourceRef('owner','operation','gone-effect'))
  self.assertEqual(retained.state,OperationState.UNKNOWN)
  self.assertEqual(retained.request.external_owner_ref,unknown.request.external_owner_ref)
  self.assertEqual(retained_identity.version,original_identity.version)
  self.assertEqual(retained_identity.payload['external_owner_ref'],original_identity.payload['external_owner_ref'])
  altered_payload=replace(unknown.request,payload={'task':'forged'})
  forged_payload=replace(unknown,request=altered_payload)
  self.assertEqual(forged_payload.effect_ref,unknown.effect_ref)
  self.assertEqual(forged_payload.version,unknown.version)
  with self.assertRaises(UnknownOutcomeError):
   manager.resolve_unknown(forged_payload,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='valid-proof',transition_key='gone-effect-forged-payload')
  retained=manager.get('gone-effect')
  retained_identity=self.store.get_identity(ResourceRef('owner','operation','gone-effect'))
  self.assertEqual(retained.state,OperationState.UNKNOWN)
  self.assertEqual(retained.request.external_owner_ref,unknown.request.external_owner_ref)
  self.assertEqual(retained.request.payload,unknown.request.payload)
  self.assertEqual(retained_identity.ref,original_identity.ref)
  self.assertEqual(retained_identity.version,original_identity.version)
  self.assertEqual(retained_identity.payload['external_owner_ref'],original_identity.payload['external_owner_ref'])
  self.assertEqual(retained_identity.payload['request_payload'],original_identity.payload['request_payload'])
  retain_proof('bool-int-proof',result_value={'verified':1,'output':'artifact-1'})
  with self.assertRaises(UnknownOutcomeError):
   manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='bool-int-proof',transition_key='gone-effect-bool-int')
  self.assertEqual(manager.get('gone-effect').state,OperationState.UNKNOWN)

  reconciled=manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
   evidence_key='valid-proof',transition_key='gone-effect-resolve')
  self.assertEqual(reconciled.state,OperationState.COMMITTED)
  self.assertEqual(reconciled.result,result)
  identity=self.store.get_identity(ResourceRef('owner','operation','gone-effect'))
  evidence=identity.payload['resolution_evidence']
  self.assertEqual(evidence['evidence_key'],'valid-proof')
  self.assertTrue(evidence['event_id'])
  receipt_count=len(self.store.list_events(stream='operations'))
  replay=manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
   evidence_key='valid-proof',transition_key='gone-effect-resolve')
  self.assertEqual(replay.operation_ref,reconciled.operation_ref)
  with self.assertRaises(OperationError):
   manager.resolve_unknown(unknown,OperationState.COMMITTED,result,resolver=self.actor,
    evidence_key='valid-proof',transition_key='gone-effect-resolve-again')
  self.assertEqual(len(self.store.list_events(stream='operations')),receipt_count)
if __name__=='__main__':unittest.main()

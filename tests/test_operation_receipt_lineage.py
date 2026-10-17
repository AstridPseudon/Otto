"""Bounded kernel receipt lineage on disposable real Store/nominal runtime."""
from dataclasses import replace
import tempfile,unittest
from pathlib import Path
from herzchen.contracts import AuthenticatedActor,ResourceRef,CommandReceipt,ReceiptStatus
from herzchen.kernel import Store
from herzchen.kernel.operations import OperationManager,OperationRequest,OperationState,UnknownOutcomeError
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
if __name__=='__main__':unittest.main()

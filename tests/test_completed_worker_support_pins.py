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

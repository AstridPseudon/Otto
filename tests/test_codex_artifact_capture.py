import base64
import copy
import unittest
from otto.agents.native_result_verifier import CodexNativeResultVerifier
from otto.agents.herzchen_adapter import _digest
from otto.portfolio.occurrence_reads import read_captured_artifact

REF={'authority':'owner','kind':'wrk.result','id':'result-1','revision':'rev-1'}
def evidence(count=1):
 commands=[{'stdout':'installed help: run-worker read-result\n','status':'completed','exit_code':0}for _ in range(count)]
 output={'commands':commands}
 records=[{'session_id':'s','turn_id':'t','event_type':'item_completed','item_type':'CommandExecution','item_id':'cmd-'+str(i),'raw_line_sha256':'a'*64}for i in range(count)]
 return {'session_id':'s','turn_id':'t','provenance':'host_command_execution/item_completed','host_records':{'commands':records},'result_digest':_digest(output),'operation_result':{'status':'completed','result_digest':_digest(output),'output':output}}
def redigest(e):e['result_digest']=e['operation_result']['result_digest']=_digest(e['operation_result']['output'])
class CodexArtifactCaptureTests(unittest.TestCase):
 def test_exact_native_stdout_is_retained_without_filesystem_reads(self):
  e=evidence();p=CodexNativeResultVerifier().capture_summary(e,result_ref=REF);a=p['artifacts'][0]
  self.assertEqual(base64.b64decode(a['content_base64']),e['operation_result']['output']['commands'][0]['stdout'].encode())
  self.assertEqual(a['ref']['result_ref'],REF);self.assertEqual(a['name'],'native-command-0.stdout.txt');self.assertEqual(p['usage']['state'],'unavailable')
 def test_foreign_session_turn_and_missing_record_refused(self):
  for key,value in [('session_id','foreign'),('turn_id','foreign'),('event_type','item_started'),('item_type','AgentMessage'),('raw_line_sha256','bad'),('item_id','')]:
   with self.subTest(key=key):
    e=evidence();e['host_records']['commands'][0][key]=value
    with self.assertRaises(ValueError):CodexNativeResultVerifier().capture_summary(e,result_ref=REF)
 def test_changed_output_digest_and_partial_record_inventory_refused(self):
  e=evidence();e['operation_result']['output']['commands'][0]['stdout']='changed'
  with self.assertRaises(ValueError):CodexNativeResultVerifier().capture_summary(e,result_ref=REF)
  e=evidence();e['host_records']['commands']=[]
  with self.assertRaises(ValueError):CodexNativeResultVerifier().capture_summary(e,result_ref=REF)
 def test_bounds_failure_and_empty_output_never_invent_artifact(self):
  for value in ['', 'x'*65537]:
   e=evidence();e['operation_result']['output']['commands'][0]['stdout']=value;redigest(e);self.assertEqual(CodexNativeResultVerifier().capture_summary(e,result_ref=REF)['artifacts'],[])
  e=evidence();e['operation_result']['output']['commands'][0]['exit_code']=1;redigest(e);self.assertEqual(CodexNativeResultVerifier().capture_summary(e,result_ref=REF)['artifacts'],[])
  self.assertEqual(len(CodexNativeResultVerifier().capture_summary(evidence(17),result_ref=REF)['artifacts']),16)
 def test_no_commands_is_explicit_unavailable_usage_not_fake_zero(self):
  p=CodexNativeResultVerifier().capture_summary(evidence(0),result_ref=REF);self.assertEqual(p['artifacts'],[]);self.assertEqual(p['usage']['state'],'unavailable')
 def test_non_result_or_unversioned_ref_refused(self):
  for ref in [{**REF,'kind':'dat.content.document'},{**REF,'revision':None}]:
   with self.assertRaises(ValueError):CodexNativeResultVerifier().capture_summary(evidence(),result_ref=ref)

 def test_existing_reader_uses_bound_exact_bytes_and_rejects_foreign_or_corrupt_ref(self):
  from otto.portfolio.tests import test_worker_occurrences as fixtures
  fx=fixtures.WorkerOccurrenceTests();fx.setUp();self.addCleanup(fx.doCleanups)
  response=fx.launch();fx.yield_parent();self.assertEqual(fx.owner('start-retained-child',response['schedule_id'])['outcome'],'succeeded')
  due=fx.f.port.read_due(response['schedule_id']);ref=due['host_evidence']['captured_result_summary']['result_ref'];a=CodexNativeResultVerifier().capture_summary(evidence(),result_ref=ref)['artifacts'][0];due['host_evidence']['captured_artifacts']=[a]
  counts=fx.f.store.consumer().snapshot_counts();calls=len(fx.f.provider.calls)
  read=read_captured_artifact(due,artifact_ref=a['ref'],offset=2,max_bytes=7)
  self.assertEqual(read['outcome'],'available');self.assertEqual(base64.b64decode(read['content_base64']),b'stalled');self.assertFalse(read['eof'])
  foreign={**a['ref'],'result_ref':{**ref,'id':'foreign'}};self.assertEqual(read_captured_artifact(due,artifact_ref=foreign)['reason'],'artifact_foreign_ref')
  due['host_evidence']['captured_artifacts'][0]['sha256']='b'*64
  with self.assertRaises(ValueError):read_captured_artifact(due,artifact_ref=a['ref'])
  self.assertEqual(fx.f.store.consumer().snapshot_counts(),counts);self.assertEqual(len(fx.f.provider.calls),calls)

 def test_linked_context_native_commands_are_captured_but_unknown_provenance_refused(self):
  e=evidence();e['provenance']='host_final_answer/item_completed';self.assertEqual(len(CodexNativeResultVerifier().capture_summary(e,result_ref=REF)['artifacts']),1)
  e['provenance']='provider_asserted'
  with self.assertRaises(ValueError):CodexNativeResultVerifier().capture_summary(e,result_ref=REF)

 def test_provider_artifact_paths_are_ignored_and_boolean_exit_is_not_success(self):
  e=evidence();e['operation_result']['output']['artifacts']=[{'path':'/unowned/secret','content_base64':'ZmFrZQ=='}];redigest(e)
  a=CodexNativeResultVerifier().capture_summary(e,result_ref=REF)['artifacts'];self.assertEqual(len(a),1);self.assertNotIn('path',a[0]);self.assertNotEqual(base64.b64decode(a[0]['content_base64']),b'fake')
  e['operation_result']['output']['commands'][0]['exit_code']=False;redigest(e);self.assertEqual(CodexNativeResultVerifier().capture_summary(e,result_ref=REF)['artifacts'],[])

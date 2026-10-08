"""Fresh worker live caller context through real gateway/adapter owner ports.

External provider is a fixture; no live authentication claim. This catches the
missing callback composition before a worker terminal result can hide it.
"""
from dataclasses import replace
from unittest.mock import patch
import unittest
from herzchen.contracts import ResourceRef
from otto.agents.gateway import OwnerDueRecordAttemptCapture
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
from otto.portfolio.identity_context import HostCallerBinding
from tests import test_execution_application as application

class FreshWorkerAdmissionTests(unittest.TestCase):
 def fixture(self):
  f=application.ExecutionApplicationTests();f.setUp();self.addCleanup(f.doCleanups)
  handles=f.app.assign_worker(**f.request());return f,handles['schedule_id']
 def test_live_authorized_worker_context_before_result_and_no_initializer_admission(self):
  f,schedule=self.fixture();original=OwnerDueRecordAttemptCapture.record_delivery_admission;seen=[]
  def capture(owner_capture,key,session,turn,stamp):
   result=original(owner_capture,key,session,turn,stamp)
   due=f.app._read(schedule);attempt=due.host_evidence['gateway_attempt']
   self.assertEqual(attempt['state'],'claimed');self.assertNotIn('result',attempt)
   self.assertEqual(owner_capture.role,'worker');self.assertEqual(turn,'provider-turn-1')
   actor=f.binding.authenticated_actor(due.recipient)
   caller=HostCallerBinding(actor,ResourceRef.from_dict(due.assignment_ref),due.generation,f.app.native_adapter_identity(),session,schedule)
   context=f.app.caller_context(caller);self.assertEqual(context['principal'],'worker')
   with self.assertRaises(PermissionError):f.app.caller_context(replace(caller,native_session_id='foreign-session'))
   seen.append(context)
   return result
  with patch.object(OwnerDueRecordAttemptCapture,'record_delivery_admission',capture):
   result=f.app.start(schedule_id=schedule)
  self.assertEqual(result['outcome'],'succeeded',result)
  self.assertEqual(len(seen),1) # READY initializer has no authorized callback.
  self.assertEqual(len(f.provider.calls),1)
  self.assertEqual(f.app.start(schedule_id=schedule)['outcome'],'replayed')
  self.assertEqual(len(f.provider.calls),1)
 def test_cli_ready_initializer_is_excluded_from_fresh_worker_admission(self):
  import json
  from tests.test_fresh_manager_admission import FreshManagerTests
  fixture=FreshManagerTests();self.addCleanup(fixture.doCleanups)
  f,root=fixture.fixture();worker=f.app.assign_worker(**f.request())
  result=f.app.start(schedule_id=worker['schedule_id'])
  self.assertEqual(result['outcome'],'succeeded',result)
  attempt=f.port.read_due(worker['schedule_id'])['host_evidence']['gateway_attempt']
  self.assertEqual(attempt['delivery_admission']['observed_turn_id'],'work-turn')
  submitted=[json.loads(raw) for raw in (root/'submitted.jsonl').read_text().splitlines()]
  self.assertEqual([v['resume'] for v in submitted],[False,True])
  self.assertNotIn('otto-resource-brief',submitted[0]['prompt'])
  self.assertIn('otto-resource-brief',submitted[1]['prompt'])

 def test_missing_live_admission_does_not_authorize_a_worker_context(self):
  f,schedule=self.fixture();original=OwnerDueRecordAttemptCapture.record_delivery_admission;denied=[]
  def omit(owner_capture,key,session,turn,stamp):
   due=f.app._read(schedule);self.assertNotIn('delivery_admission',due.host_evidence['gateway_attempt'])
   caller=HostCallerBinding(f.binding.authenticated_actor(due.recipient),ResourceRef.from_dict(due.assignment_ref),due.generation,f.app.native_adapter_identity(),session,schedule)
   with self.assertRaisesRegex(PermissionError,'verified admission/readback'):f.app.caller_context(caller)
   denied.append(session)
   return original(owner_capture,key,session,turn,stamp)
  with patch.object(OwnerDueRecordAttemptCapture,'record_delivery_admission',omit):result=f.app.start(schedule_id=schedule)
  self.assertEqual(result['outcome'],'succeeded',result);self.assertEqual(len(denied),1)

if __name__=='__main__':unittest.main()

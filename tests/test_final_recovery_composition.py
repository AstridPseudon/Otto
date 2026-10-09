"""Final findings: default scoped discovery and composed reminder startup."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from otto.attention import issue_store_due_record_port, DueRecord
from unittest.mock import patch
from herzchen.kernel.store import DomainHandler
from tests import test_execution_application as execution_fixture
from tests.test_reminder_continuity import record
from otto.attention import DurableAttention
from otto.portfolio.recovery_discovery import BoundedRecoveryDiscovery
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.execution import ExecutionApplication
from tests.test_reminder_continuity import ReminderContinuityTests, NOW

class ScopedDiscoveryTests(unittest.TestCase):
 def test_default_project_reader_filters_current_records_before_payload_hydration(self):
  fixture=execution_fixture.ExecutionApplicationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  attention=DurableAttention(None,due_port=fixture.port)
  attention.schedule(replace(record(),schedule_id='current',project_ref=fixture.project.id),request_id='scoped-current')
  attention.schedule(replace(record(),schedule_id='foreign',project_ref='foreign'),request_id='scoped-foreign')
  reads=[];original=DomainHandler.get_identity
  def read(handler,ref):
   if ref.kind=='otto.due-record':reads.append(ref.id)
   return original(handler,ref)
  reader=BoundedRecoveryDiscovery(operations=None,due_port=fixture.port)
  with patch.object(DomainHandler,'list_events',side_effect=AssertionError('global history hydration')),patch.object(DomainHandler,'get_identity',read):
   actual=reader._occurrences(fixture.project.ref.to_dict(),[],None)
   self.assertEqual([x['schedule_id']for x in actual],['current'])
   self.assertEqual(reads,['current'])
   self.assertEqual(fixture.port.list_due({'project_ref':'absent'}),())
   self.assertEqual(reads,['current'])
  self.assertEqual(fixture.provider.calls,[])

class ComposedReminderTests(unittest.TestCase):
 def setUp(self):
  self.f=ReminderContinuityTests();self.f.setUp()
  self.s=ManagerJourneyService.__new__(ManagerJourneyService)
  self.s.commands=SimpleNamespace(_authorize=lambda:None)
  self.s.server=SimpleNamespace(state={'project_ref':{'id':'project'},'reminder_schedule_ids':['reminder']},due_port=self.f.due,reminder_attention=self.f.attention)
 def startup(self):return self.s._execution_control({'command':'execution-control','operation':'startup'})
 def prepare(self,state):
  return self.f.attention.prepare_host('reminder',request_id='retained-'+state,actor='manager',expected_version=self.f.attention._read('reminder').version,desired_state=state)
 def test_installed_startup_readback_recovers_exact_lost_response_then_due_coalesces_once(self):
  lost={'yes':True}
  def read(*_):
   if lost['yes']:raise RuntimeError('lost reply')
   return {**self.f.settings,'state':'active','observed_at':NOW.isoformat()}
  executor=self.f.executor(read=read);effect=self.prepare('active')['effect'];self.assertEqual(executor.execute(effect)['outcome'],'response_lost');self.s.server.reminder_host_executor=executor
  self.assertEqual(self.startup()['reminder_admission'],'held');self.assertEqual(len(self.f.updates),1)
  lost['yes']=False;result=self.startup();self.assertEqual(result['reminder_admission'],'ready');due=result['reminder_reconciliation']['rows'][0]['due'];self.assertEqual(due['missed_slots'],2)
  self.assertEqual(len(self.f.updates),1);self.assertEqual(len(self.f.attention.attention.requests),1)
  self.startup();self.assertEqual(len(self.f.updates),1);self.assertEqual(len(self.f.attention.attention.requests),1)
  view=self.s._execution_control({'command':'execution-control','operation':'reminder-read','schedule_id':'reminder'})
  self.assertTrue(view['read_only']);self.assertEqual(view['last_observed_host_wake']['state'],'unknown');self.assertEqual(view['last_admitted_due_occurrence']['state'],'admitted')
 def test_paused_and_mismatched_readback_hold_without_repeating_mutation(self):
  for mismatch in (False,True):
   self.setUp();self.prepare('paused');self.f.settings['status']='PAUSED'
   self.s.server.reminder_host_executor=self.f.executor(read=lambda *_:{**self.f.settings,'state':'paused',**({'prompt':'foreign'}if mismatch else{}),'observed_at':NOW.isoformat()})
   result=self.startup();self.assertEqual(result['reminder_admission'],'held');self.assertEqual(self.f.updates,[]);self.assertEqual(self.f.attention.attention.requests,[])
   self.assertEqual(result['reminder_reconciliation']['rows'][0]['status']['last_observed_host_wake']['state'],'unknown')
 def test_unavailable_composition_is_explicit_and_unknown_ids_do_not_admit_work(self):
  del self.s.server.reminder_attention
  result=self.startup();self.assertEqual(result['reminder_admission'],'held');self.assertEqual(result['reminder_reconciliation']['reason'],'owner_reminder_bridge_unavailable');self.assertEqual(self.f.attention.attention.requests,[])
  self.s.server.reminder_attention=self.f.attention;self.s.server.state['reminder_schedule_ids']=['missing']
  result=self.startup();self.assertEqual(result['reminder_admission'],'held');self.assertEqual(self.f.attention.attention.requests,[])
 def test_foreign_known_scope_is_rejected_and_no_request_can_override_ports(self):
  self.s.server.state['project_ref']={'id':'foreign'}
  with self.assertRaises(PermissionError):self.startup()
  with self.assertRaises(ValueError):self.s._execution_control({'command':'execution-control','operation':'startup','reminder_schedule_ids':['foreign']})
 def test_native_recovery_diagnosis_remains_available_under_separate_reminder_hold(self):
  fake=SimpleNamespace(recovery_status=lambda **kw:{'state':'returned'},recover=lambda **kw:{'outcome':'replayed'})
  fake.recover_startup=lambda **kw:ExecutionApplication.recover_startup(fake,**kw)
  effect=self.prepare('active')['effect'];self.assertIsNotNone(effect)
  self.s.server.reminder_host_executor=None
  result=self.s._startup_recovery(fake,['native'],execute=False)
  self.assertEqual(result['admission'],'ready');self.assertEqual(result['reminder_admission'],'held');self.assertEqual(result['occurrences'][0]['result']['outcome'],'replayed')

if __name__=='__main__':unittest.main()

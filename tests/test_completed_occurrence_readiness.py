"""Readiness follows one authentic settled completion input; effects stay strict."""
import copy,hashlib,json,unittest
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.owner_readers import completed_occurrence_task_reader,OwnerRoleRuntimeError
from tests import test_manager_journey_command as fixture

class CompletedOccurrenceReadinessTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.ManagerJourneyCommandTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  f=self.f.application;state=self.f.fixture.state;self.state=state
  task=f.owner.graph.reader.get_identity(ResourceRef.from_dict(state['task_refs']['PA01']))
  brief={'context':{'project_state':{'task':{'ref':task.ref.to_dict(),'payload':copy.deepcopy(task.payload),'lifecycle':task.payload['lifecycle']}}}}
  digest=hashlib.sha256(json.dumps(brief,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  result={'outcome':'succeeded','context_digest_verified':True,'physical_session_id':'retained-manager','observed_turn_id':'fixture-turn','assignment_ref':state['assignment_ref'],'generation':1,'task_ref':task.ref.to_dict(),'project_ref':state['project_ref'],'resource_evidence':{'brief':brief,'brief_sha256':digest}}
  self.due=SimpleNamespace(role='manager',completion_state='succeeded',stop_state='completed',in_flight_request=None,assignment_ref=state['assignment_ref'],generation=1,recipient='manager',target={'task_ref':task.ref.to_dict(),'project_ref':state['project_ref']},host_evidence={'gateway_attempt':{'result':result,'delivery_authorization':{'brief_sha256':digest},'delivery_admission':{'native_turn_started':True,'physical_session_id':'retained-manager','observed_turn_id':'fixture-turn'}}})
  reviewed=self.f.commands.review_task(self.f.request(key='complete-before-readiness'))
  self.assertEqual(reviewed['completion']['outcome'],'completed')
  self.assignment=self.f.fixture.manager
 def test_real_committed_completion_allows_readonly_snapshot_and_rejects_drift(self):
  f=self.f.application;before=f.owner.graph.reader.snapshot_counts()
  read=completed_occurrence_task_reader(f.owner.graph.reader,self.due,self.assignment)
  task=self.due.target['task_ref'];self.assertEqual(read({k:task[k] for k in ('authority','kind','id')})['ref'],task)
  runtime=f.owner.role_runtime(due_port=f.port,adapter=f.app.runtime.adapter)
  self.assertEqual(runtime.completed_task_readiness(self.due)({'authority':task['authority'],'kind':task['kind'],'id':task['id']})['ref'],task)
  # The invocation's ordinary task reader still observes the actual rev2 head.
  self.assertNotEqual(runtime._task_reader(self.state['project_ref'],task)({k:task[k] for k in ('authority','kind','id')})['ref'],task)
  for mutate in (lambda d:setattr(d,'generation',2),lambda d:setattr(d,'recipient','foreign'),lambda d:setattr(d,'stop_state','active'),lambda d:d.target['task_ref'].update(revision='rev-999'),lambda d:d.host_evidence['gateway_attempt']['delivery_authorization'].update(brief_sha256='0'*64),lambda d:d.host_evidence['gateway_attempt']['result']['resource_evidence']['brief']['context']['project_state']['task']['payload'].update(title='forged')):
   altered=copy.deepcopy(self.due);mutate(altered)
   with self.assertRaises(OwnerRoleRuntimeError):completed_occurrence_task_reader(f.owner.graph.reader,altered,self.assignment)
  self.assertEqual(f.owner.graph.reader.snapshot_counts(),before)
  self.assertEqual(f.provider.calls,[])

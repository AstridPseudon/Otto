"""Task closure uses the existing project-scoped current Due read contract."""
import unittest
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.manager_journey_command import ManagerJourneyCommands

class SettlementScopeTests(unittest.TestCase):
 def setUp(self):
  self.ref=ResourceRef('owner','wrk.result','candidate','rev-1')
  self.payload={'project_ref':ResourceRef('owner','work.project','project','rev-1').to_dict(),'task_ref':ResourceRef('owner','work.task','task','rev-1').to_dict(),'assignment_ref':ResourceRef('owner','wrk.assignment','worker','rev-1').to_dict(),'generation':1,'logical_request_key':'result-key'}
  self.due={'project_ref':'project','assignment_ref':self.payload['assignment_ref'],'generation':1,'last_completed_request':'result-key','in_flight_request':None,'target':{'task_ref':self.payload['task_ref'],'project_ref':self.payload['project_ref']},'schedule_id':'worker-one','stop_state':'completed','completion_state':'succeeded'}
  outer=self
  class Port:
   def list_due(self,scope=None):
    outer.assertEqual(scope,{'project_ref':'project'});outer.calls.append(scope);return outer.records
  self.calls=[];self.records=[self.due]
  owner=SimpleNamespace(graph=SimpleNamespace(reader=SimpleNamespace(get_identity=lambda ref:SimpleNamespace(payload={'value':self.payload}))))
  self.commands=ManagerJourneyCommands(owner=owner,portfolio=None,state={},due_port=Port())
 def test_exact_completed_candidate_projects_inventory_before_read(self):
  self.assertIsNone(self.commands._native_settlement({'candidate_ref':self.ref.to_dict()}));self.assertEqual(len(self.calls),1)
 def test_missing_or_ambiguous_matching_occurrence_never_settles(self):
  for records in ([],[self.due,{**self.due,'schedule_id':'duplicate'}]):
   self.records=records;self.assertEqual(self.commands._native_settlement({'candidate_ref':self.ref.to_dict()})['outcome'],'held')
 def test_foreign_or_changed_native_join_never_settles(self):
  for field,value in [('generation',2),('assignment_ref',ResourceRef('owner','wrk.assignment','foreign','rev-1').to_dict()),('last_completed_request','different')]:
   self.records=[{**self.due,field:value}];self.assertEqual(self.commands._native_settlement({'candidate_ref':self.ref.to_dict()})['outcome'],'held')
  self.records=[{**self.due,'target':{**self.due['target'],'project_ref':ResourceRef('owner','work.project','foreign','rev-1').to_dict()}}];self.assertEqual(self.commands._native_settlement({'candidate_ref':self.ref.to_dict()})['outcome'],'held')
 def test_malformed_project_fails_before_inventory(self):
  self.payload['project_ref']={'id':'project'}
  with self.assertRaises((KeyError,ValueError,TypeError)):self.commands._native_settlement({'candidate_ref':self.ref.to_dict()})
  self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main()

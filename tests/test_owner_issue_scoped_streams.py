"""Issue history stays scoped while preserving old BASE and supervisor records."""
from types import SimpleNamespace as NS
import unittest
from herzchen.contracts import ResourceRef
from otto.portfolio.owner_issue_loop import OwnerIssueReaders

class ScopedIssueStreamTests(unittest.TestCase):
 def test_old_manager_revision_and_transferred_supervisor_survive_without_global_hydration(self):
  project=ResourceRef('owner','work.project','project','rev-3')
  manager=ResourceRef('owner','wrk.assignment','manager','rev-3')
  old=ResourceRef('owner','wrk.assignment','old-root','rev-1')
  new=ResourceRef('owner','wrk.assignment','new-root','rev-2')
  task=ResourceRef('owner','work.task','task','rev-1')
  def report(n,a,p=project):
   return NS(ref=ResourceRef('owner','wrk.report',n,'rev-1'),version=1,payload={'assignment':a.to_dict(),'generation':1,'observation_kind':'report','value':{'project_ref':p.to_dict(),'summary':n}})
  records={x.ref.id:x for x in [report('old-manager',ResourceRef('owner','wrk.assignment','manager','rev-1')),report('old-supervisor',old),report('new-supervisor',new),report('foreign',new,ResourceRef('owner','work.project','elsewhere','rev-1'))]}
  calls=[]
  def events(*,stream=None,subjects=None):
   calls.append(stream)
   self.assertIsNotNone(stream,'global event hydration is forbidden')
   if stream=='work:project':return [NS(before_refs=(project,old),after_refs=(new,),effects={'from_assignment':old.to_dict(),'to_assignment':new.to_dict()})]
   ids={'report:manager':['old-manager'],'report:old-root':['old-supervisor'],'report:new-root':['new-supervisor','foreign']}.get(stream,[])
   return [NS(subject=records[n].ref)for n in ids]
  view={'project':{'observed':{'assignments':[{'ref':manager.to_dict()}]}},'tasks':[{'ref':task.to_dict(),'observed':{'assignments':[]}}]}
  record=NS(ref=project,payload={'metadata':{'otto_orchestrator':{'assignment_ref':new.to_dict()}}})
  operations=NS(sheet_port=NS(export=lambda ref:view),_owner_reader=NS(list_events=events,get_record=lambda ref:records[ref.id]))
  readers=OwnerIssueReaders(operations,None);readers.project=lambda value:record
  result=readers.reports(project.to_dict())
  self.assertEqual({x['ref']['id']for x in result},{'old-manager','old-supervisor','new-supervisor'})
  self.assertIn('report:old-root',calls);self.assertIn('result:manager',calls)
  self.assertEqual(next(x for x in result if x['ref']['id']=='old-manager')['assignment']['revision'],'rev-1')
 def test_due_selection_is_project_scoped_before_hydration(self):
  project=ResourceRef('owner','work.project','project','rev-1');calls=[]
  def list_due(scope):
   calls.append(scope);return [{'project_ref':'project','role':'manager','manager_ref':'manager','generation':1}]
  reader=OwnerIssueReaders(NS(),NS(list_due=list_due));reader.project=lambda ref:NS(ref=project);reader.current_manager=lambda ref:NS(ref=ResourceRef('owner','wrk.assignment','manager','rev-1'),generation=1)
  self.assertEqual(len(reader.due_records(project.to_dict())),1)
  self.assertEqual(calls,[{'project_ref':'project'}])

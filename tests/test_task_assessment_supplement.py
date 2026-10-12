"""Real owner per-task debit selection; global setup scope and old journals survive."""
import copy
import unittest
from herzchen.contracts import ResourceRef
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from tests import test_manager_journey_command as original

class TaskSupplementTests(unittest.TestCase):
    def setUp(self):
        self.f = original.ManagerJourneyCommandTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.commands = self.f.commands; self.state = self.f.fixture.state
        self.original = copy.deepcopy(self.state['assessment_policy'])
        self.config = {**self.original, 'pool_id':'task-correction-once',
                       'cumulative_allowance_units':1, 'task_criterion_pairs':['PA01/C01']}
        self.key='owner-task-correction-allocation'

    def bind(self):
        policy=LocalAssessmentPolicy.from_run_config(self.config,state=self.state)
        self.f.application.owner.create_manager_assessment_pool(project_ref=self.state['project_ref'],
            task_ref=self.state['task_refs']['PA01'], manager_assignment_ref=self.state['assignment_ref'],
            manager_actor=self.state['manager'],manager_generation=1,logical_request_key=self.key,assessment_policy=policy)
        self.state['task_assessment_supplements']={'PA01':{'policy':copy.deepcopy(self.config),'binding':{
            'project_ref':self.state['project_ref'], 'task_ref':self.state['task_refs']['PA01'],
            'assignment_ref':self.state['assignment_ref'], 'generation':1,'principal':self.state['manager'],
            'pool_ref':policy.pool_ref.to_dict(),'criterion_refs':[self.state['criterion_refs']['C01']],
            'allocation_key':self.key}}}
        return policy

    def test_review_and_read_input_same_task_pool_other_pending_task_keeps_main(self):
        self.bind()
        read=self.commands.review_input('PA01')
        self.assertEqual(read['assessment_policy_selection']['pool_ref']['id'],'task-correction-once')
        from otto.portfolio.manager_journey_client import command_result_summary
        self.assertEqual(command_result_summary(read)['assessment_policy_selection'],read['assessment_policy_selection'])
        self.assertEqual(self.commands._review_policy('PA06').pool_ref.id,self.original['pool_id'])
        result=self.commands.review_task({**self.f.request(key='new-task-correction'), 'finish':False})
        self.assertEqual(result['outcome'],'accepted')
        intent=self.commands._journal('new-task-correction','intent')
        self.assertEqual(intent['assessment_policy_selection'],read['assessment_policy_selection'])
        self.assertEqual(self.state['assessment_policy'],self.original)
        self.assertEqual(self.f.application.provider.calls,[])

    def test_legacy_partial_key_cannot_move_its_debit_into_new_pool(self):
        request={**self.f.request(key='legacy-partial'), 'finish':False}
        self.commands._journal('legacy-partial','intent',{'request':request,'task_ref':self.state['task_refs']['PA01'],
            'project_ref':self.state['project_ref'],'assignment_ref':self.state['assignment_ref'],'generation':1})
        self.bind(); before=self.f.application.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(PermissionError,'policy differs'):
            self.commands.review_task(request)
        self.assertEqual(before,self.f.application.store.consumer().snapshot_counts())

    def test_changed_policy_pin_refuses_same_review_key_without_second_charge(self):
        self.bind();request={**self.f.request(key='pinned-review'), 'finish':False}
        self.commands.review_task(request)
        self.state['task_assessment_supplements']['PA01']['policy']['purpose']='changed purpose'
        before=self.f.application.store.consumer().snapshot_counts()
        with self.assertRaises(PermissionError):self.commands.review_task(request)
        self.assertEqual(before,self.f.application.store.consumer().snapshot_counts())

    def test_finished_task_alias_advance_and_restart_replay_preserves_original_debit(self):
        self.bind();request=self.f.request(key='finished-corrective')
        first=self.commands.review_task(request)
        self.assertEqual(first['completion']['outcome'],'completed')
        task=ResourceRef.from_dict(self.state['task_refs']['PA01'])
        current=self.f.application.owner.graph.reader.get_identity_ref(task)
        self.assertNotEqual(current,task)
        self.state['task_refs']['PA01']=current.to_dict()
        from otto.portfolio.manager_journey_command import ManagerJourneyCommands
        restarted=ManagerJourneyCommands(owner=self.f.application.owner,portfolio=self.f.application.app.portfolio,
            state=copy.deepcopy(self.state))
        before=self.f.application.store.consumer().snapshot_counts()
        replay=restarted.review_task(request)
        self.assertEqual(replay['completion']['outcome'],'replayed')
        self.assertEqual(before,self.f.application.store.consumer().snapshot_counts())
        with self.assertRaises(PermissionError):
            restarted.review_task({**request,'request_key':'new-on-old-completion'})
        self.assertEqual(self.f.application.provider.calls,[])

    def test_authenticated_same_generation_resource_adoption_preserves_owner_supplement(self):
        self.bind();f=self.f.application;manager=self.f.fixture.manager
        import hashlib
        from herzchen.content.instructions import validate_instruction_content
        content={"schema":"herzchen.instructions.v1","name":"updated-supplement-guide","entrypoint":"MANAGER.md",
            "instructions":"Use exact owned task supplement","bundle_digest":hashlib.sha256(b"Use exact owned task supplement").hexdigest(),
            "export_manifest_digest":"new-selected-pack","required":True,"supporting_refs":[]}
        made=f.app.portfolio.create_document(f.project.ref.to_dict(),actor='manager',request_id='new-supplement-guide',
            document_id=content['name'],content=content)
        ref=made['record']['payload']['current_revision']
        adopted=f.owner.assignments.command_port.adopt_resources(manager.ref,
            resources=[{'resource_ref':ref,'resource_name':content['name'],'content_digest':validate_instruction_content(content),'required':True}],
            expected_revision=manager.revision,expected_generation=manager.generation,logical_request_key='adopt-supplement-guide',actor=f.actor)
        self.state['assignment_ref']=adopted.ref.to_dict()
        self.assertEqual(self.commands.review_input('PA01')['assessment_policy_selection']['pool_ref']['id'],'task-correction-once')
        self.assertEqual(self.f.application.provider.calls,[])

    def test_restart_replay_single_charge_and_exhaustion_never_falls_back_main(self):
        self.bind()
        request={**self.f.request(key='first-corrective',verdict='REWORK'), 'finish':False}
        self.commands.review_task(request)
        from otto.portfolio.manager_journey_command import ManagerJourneyCommands
        restarted=ManagerJourneyCommands(owner=self.f.application.owner,portfolio=self.f.application.app.portfolio,
                                         state=copy.deepcopy(self.state))
        before=self.f.application.store.consumer().snapshot_counts()
        self.assertEqual(restarted.review_task(request)['outcome'],'rework')
        self.assertEqual(before,self.f.application.store.consumer().snapshot_counts())
        from herzchen.kernel.limits import LimitService
        limits=LimitService(self.f.application.store)
        pool=self.commands._review_policy('PA01').pool_ref
        self.assertEqual(limits.get_pool(pool).cumulative_used_units,1)
        with self.assertRaises(Exception):
            restarted.review_task({**request,'request_key':'second-corrective'})
        self.assertEqual(limits.get_pool(pool).cumulative_used_units,1)
        self.assertEqual(self.state['assessment_policy'],self.original)
        self.assertEqual(self.f.application.provider.calls,[])

    def test_other_pending_tasks_still_qualify_full_original_operating_setup(self):
        from otto.portfolio.tests import test_operating_setup as setup_fixture
        from herzchen.domains.assessment import AssessmentModule
        from otto.portfolio.manager_journey_command import ManagerJourneyCommands
        from otto.portfolio.operating_setup import evaluate_setup
        ftest=setup_fixture.OperatingSetupTests();ftest.setUp();self.addCleanup(ftest.doCleanups)
        f=ftest.f;config=ftest.manual();due=f.port.read_due(config['roles']['manager'])
        second=f.owner.graph.create_task(f.project.ref,title='Other pending',logical_request_key='other-pending')
        assessment=AssessmentModule(f.store,actor=f.actor)
        ca=assessment.declare_scope('pending-a',parent_obligation=f.task.ref,protocol='fixture',criteria=[{'id':'A'}],
            designated_approver='manager',policy={'required_for_completion':True},logical_request_key='pending-a')
        cb=assessment.declare_scope('pending-b',parent_obligation=second.ref,protocol='fixture',criteria=[{'id':'B'}],
            designated_approver='manager',policy={'required_for_completion':True},logical_request_key='pending-b')
        state={'authority':f.actor.authority,'project_ref':f.project.ref.to_dict(),
            'task_refs':{'A':f.task.ref.to_dict(),'B':second.ref.to_dict()},
            'criterion_refs':{'A':ca.criterion_refs[0].to_dict(),'B':cb.criterion_refs[0].to_dict()},
            'assignment_ref':due['assignment_ref'],'manager':'manager','manager_generation':1}
        base={**self.original,'pool_id':'full-pending-main','task_criterion_pairs':['A/A','B/B']}
        state['assessment_policy']=copy.deepcopy(base)
        original_policy=LocalAssessmentPolicy.from_run_config(base,state=state)
        f.owner.create_manager_assessment_pool(project_ref=state['project_ref'],task_ref=state['task_refs']['A'],
            manager_assignment_ref=state['assignment_ref'],manager_actor='manager',manager_generation=1,
            logical_request_key='full-pending-main-allocation',assessment_policy=original_policy)
        app=f.owner.execution_application(due_port=f.port,adapter=f.app.runtime.adapter,clock=f.app.clock,
            manager_actor='manager',assessment_policy=original_policy)
        supplement={**base,'pool_id':'one-task-only','task_criterion_pairs':['A/A'],'cumulative_allowance_units':1}
        policy=LocalAssessmentPolicy.from_run_config(supplement,state=state)
        f.owner.create_manager_assessment_pool(project_ref=state['project_ref'],task_ref=state['task_refs']['A'],
            manager_assignment_ref=state['assignment_ref'],manager_actor='manager',manager_generation=1,
            logical_request_key='one-task-allocation',assessment_policy=policy)
        state['task_assessment_supplements']={'A':{'policy':supplement,'binding':{
            'project_ref':state['project_ref'],'task_ref':state['task_refs']['A'],
            'assignment_ref':state['assignment_ref'],'principal':'manager','generation':1,
            'pool_ref':policy.pool_ref.to_dict(),'criterion_refs':[state['criterion_refs']['A']],
            'allocation_key':'one-task-allocation'}}}
        commands=ManagerJourneyCommands(owner=f.owner,portfolio=app.portfolio,state=state,policy=base)
        self.assertEqual(commands._review_policy('A').pool_ref.id,'one-task-only')
        self.assertEqual(commands._review_policy('B').pool_ref.id,'full-pending-main')
        config['acceptance_tasks']=list(state['task_refs'].values())
        decision=evaluate_setup(app.runtime,f.project.ref.to_dict(),config)
        self.assertTrue(decision['ready'],decision['blockers'])
        self.assertEqual(state['assessment_policy'],base)
        self.assertEqual(f.provider.calls,[])

    def test_foreign_stale_missing_receipt_wrong_generation_and_other_task_refuse(self):
        self.bind();original=copy.deepcopy(self.state['task_assessment_supplements'])
        for field,value in [('project_ref',{**self.state['project_ref'],'id':'foreign'}),
                ('task_ref',self.state['task_refs']['PA06']),('assignment_ref',{**self.state['assignment_ref'],'revision':'rev-999'}),
                ('generation',2),('principal','foreign'),('allocation_key','missing'),
                ('criterion_refs',[self.state['criterion_refs']['C09']])]:
            with self.subTest(field=field):
                self.state['task_assessment_supplements']=copy.deepcopy(original)
                self.state['task_assessment_supplements']['PA01']['binding'][field]=value
                before=self.f.application.store.consumer().snapshot_counts()
                with self.assertRaises((PermissionError,ValueError)):self.commands.review_input('PA01')
                self.assertEqual(before,self.f.application.store.consumer().snapshot_counts())

if __name__=='__main__':unittest.main()

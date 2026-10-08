"""Connected real assignment CAS and retained acquisition; no real provider."""
import unittest
from dataclasses import replace
from tests import test_execution_application as fixture
from otto.portfolio.manager_replacement import OwnerManagerReplacement


class OwnerManagerReplacementTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ExecutionApplicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.manager,guide,mandate=self.f.role_handles('manager','manager','old-manager-session')
        prepared=self.f.app.prepare_role(role='manager',project_ref=self.f.project.ref.to_dict(),
            task_ref=self.f.task.ref.to_dict(),assignment_ref=self.manager.ref.to_dict(),generation=1,
            mandate_ref=mandate,context_refs=(guide,mandate),request_key='old-manager',
            instruction='Inspect the bounded journey',model='gpt-test',reasoning='high',profile='workspace-write')
        self.schedule=prepared['schedule_id']
        self.assertEqual(self.f.app.start(schedule_id=self.schedule)['outcome'],'succeeded')
        self.acquisitions=[]
        def acquire(prior):
            self.acquisitions.append(prior['schedule_id'])
            return {'outcome':'succeeded','terminal_verified':True,'physical_session_id':'new-manager-session',
                    'receipt':{'kind':'substituted-native-initializer'}}
        self.port=OwnerManagerReplacement(application=self.f.app,report_reader=self.f.owner.graph.reader.get_identity,acquire_session=acquire,
            context_builder=lambda assignment,generation,native:{'assignment_ref':assignment['ref'],
                'generation':generation,'conversation':native},readiness=lambda *_:{'ready':True})

    def test_real_same_assignment_replacement_and_replay_do_not_reacquire(self):
        result=self.port.replace(schedule_id=self.schedule,request_key='replace-journey')
        self.assertEqual(result['outcome'],'replaced',result)
        current=self.f.app.assignments.get(self.manager.ref)
        self.assertEqual(current.generation,2)
        self.assertEqual(current.session,'new-manager-session')
        replay=self.port.replace(schedule_id=self.schedule,request_key='replace-journey')
        self.assertEqual(replay['outcome'],'replayed',replay)
        self.assertEqual(self.acquisitions,[self.schedule])
        self.assertEqual(self.f.app._read(self.schedule).generation,1)

    def test_current_context_can_refresh_identical_BASE_in_the_new_generation(self):
        def context(assignment,generation,native):
            current=self.f.app.assignments.get(assignment['ref'])
            adopted=self.f.app.assignments.adopt_resources(current.ref,
                resources=current.payload['resource_adoptions'],expected_revision=current.revision,
                expected_generation=generation,logical_request_key='replacement-BASE',actor=self.f.actor)
            return {'assignment_ref':adopted.ref.to_dict(),'generation':generation,'conversation':native}
        self.port.context_builder=context
        result=self.port.replace(schedule_id=self.schedule,request_key='replace-adopted')
        self.assertEqual(result['status'],'ready',result)
        current=self.f.app.assignments.get(self.manager.ref)
        self.assertEqual(result['assignment']['ref'],current.ref.to_dict())
        self.assertEqual(current.generation,2)
        self.assertEqual(len(self.f.provider.calls),1)
        self.assertEqual(len(self.acquisitions),1)

    def test_unrelated_context_revision_is_not_resource_adoption_proof(self):
        self.port.context_builder=lambda assignment,generation,native: {
            'assignment_ref':{**assignment['ref'],'revision':'rev-999'},
            'generation':generation,'conversation':native}
        result=self.port.replace(schedule_id=self.schedule,request_key='replace-inexact-context')
        self.assertEqual(result['status'],'recoverable',result)
        self.assertEqual(result['error']['code'],'current_context_delivery_failed')
        self.assertEqual(len(self.acquisitions),1)

    def test_unknown_old_effect_never_initializes_or_reassigns(self):
        prior=self.f.app._read(self.schedule)
        unknown=replace(prior,completion_state='unknown')
        self.f.port.save_due(self.schedule,unknown.to_dict(),request_id='unknown-fixture',expected_version=prior.version)
        result=self.port.replace(schedule_id=self.schedule,request_key='replace-held')
        self.assertEqual(result['outcome'],'held')
        self.assertEqual(self.acquisitions,[])
        self.assertEqual(self.f.app.assignments.get(self.manager.ref).generation,1)

    def test_context_failure_retains_acquired_native_and_fences_foreign_generation(self):
        self.port.context_builder=lambda *_:(_ for _ in ()).throw(RuntimeError('context not prepared'))
        result=self.port.replace(schedule_id=self.schedule,request_key='replace-partial')
        self.assertEqual(result['outcome'],'partial',result)
        self.assertEqual(self.acquisitions,[self.schedule])
        self.port.context_builder=lambda assignment,generation,native:{'assignment_ref':assignment['ref'],
            'generation':generation,'conversation':native}
        resumed=self.port.replace(schedule_id=self.schedule,request_key='replace-partial')
        self.assertEqual(resumed['status'],'ready',resumed)
        current=self.f.app.assignments.get(self.manager.ref)
        self.f.app.assignments.reassign(current.ref,principal='manager',session='foreign-native',
            expected_generation=2,logical_request_key='foreign-reassignment',actor=self.f.actor)
        with self.assertRaises(PermissionError):
            self.port.replace(schedule_id=self.schedule,request_key='replace-partial')
        self.assertEqual(self.acquisitions,[self.schedule])

if __name__=='__main__':unittest.main()

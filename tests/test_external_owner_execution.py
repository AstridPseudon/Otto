"""Real owner-store joins with a synthetic provider; not installed-host proof."""
import copy
import json
from pathlib import Path
import unittest
from herzchen.contracts import ResourceRef
from otto.portfolio.external_owner_execution import OwnerExecutionIngress
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
from otto.portfolio.execution_host import _nested_capability, _starts_work
from otto.portfolio.occurrence_reads import handle
from otto.portfolio.resource_sync import normalize_instruction_contract
from otto.portfolio.tests import test_worker_occurrences as fixtures
from otto.portfolio.identity_context import HostIngress

class ExternalOwnerExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkerOccurrenceTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.yield_parent()
        self.s = self.f.service
        owner = self.f.server.owner
        root = owner.assignments.assign(ResourceRef(self.f.f.store.authority, 'wrk.portfolio', 'external-root'),
            role='orchestrator', principal=owner.owner_actor.actor, logical_request_key='external-root')
        root = owner.assignments.adopt_resources(root.ref, resources=self.f.manager.payload['resource_adoptions'],
            expected_revision=root.revision, expected_generation=1, logical_request_key='external-root-base', actor=owner.owner_actor)
        self.root = root
        self.f.server.state['orchestrator_assignment_ref'] = root.ref.to_dict()
        self.f.config['worker_operation_profiles'] = {}
        (self.f.run/'run.yaml').write_text(json.dumps(self.f.config))
        self.ingress = OwnerExecutionIngress(actor=owner.owner_actor,owner_actor=owner.owner_actor,directory=self.f.root/'root-ipc')
        self.s.external_execution_authorizer = self.ingress.authorize
        self.s.external_execution_policy = {'root_assignment_ref':root.ref.to_dict(),'generation':1,
            'project_ref':self.f.server.state['project_ref'],'task_ref':self.f.server.state['task_refs']['D02'],
            'task':'D02','principal':'external-leaf','route':'normal','model':'gpt-test','reasoning':'high',
            'native_adapter':self.f.f.app.native_adapter_identity(),'max_launches':1,
            'worker_turn_allowance':6,'capacity_units':1,'max_depth':1,'operation_profile':'read_only_inspection'}
    def request(self,operation,**kwargs):
        return {'command':'owner-execution','operation':operation,'request_key':'root-'+operation,**kwargs}
    def call(self,operation,**kwargs):
        r=self.request(operation,**kwargs)
        self.ingress.publish({'schema':self.ingress.schema,'request':r})
        result = self.f.host._dispatch(r, ingress=HostIngress("file-ipc", self.f.host.directory/"external-owned"))
        if result.get("outcome") == "error":
            raise {"PermissionError": PermissionError, "ValueError": ValueError}.get(result["error"], RuntimeError)(result.get("message", str(result)))
        return result
    def launch(self,**kwargs):
        return self.call('launch',focus='Inspect the installed commands and return factual evidence only.',**kwargs)
    def test_launch_exact_parent_historical_reads_consumption_and_leaf_contract(self):
        calls=len(self.f.f.provider.calls)
        answer=self.launch();self.assertEqual(answer['outcome'],'admitted',answer)
        occurrence=answer['occurrence'];due=self.f.f.port.read_due(occurrence['schedule_id'])
        self.assertEqual(due['profile'],'read-only');self.assertEqual(due['target']['launch_request']['external_parent']['assignment_ref'],self.root.ref.to_dict())
        self.assertEqual(len(self.f.f.provider.calls),calls)
        from otto.portfolio.owner_readers import mandate_reader
        m=mandate_reader(self.f.f.app.portfolio.operations,due['target']['project_ref'],due['target']['mandate_ref'])({k:due['target']['mandate_ref'][k]for k in ('authority','kind','id')})
        c=m['payload']['instruction_contract'];normalize_instruction_contract(c)
        self.assertNotIn('delegation',c);self.assertEqual(c['read_scope'],'linked_context');self.assertIn('file_write',c['authority']['forbidden_effects'])
        for op in ('result','follow'):
            v=self.call(op,occurrence=occurrence);self.assertTrue(v['pure']);self.assertFalse(v['required_capture'])
        counts=self.f.f.store.consumer().snapshot_counts()
        found=self.call('lookup',original_request_key='root-launch');self.assertEqual(found['occurrence'],occurrence)
        self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        self.f.config['roles']['worker_normal']['model']='changed';(self.f.run/'run.yaml').write_text(json.dumps(self.f.config))
        repeat=self.launch();self.assertEqual(repeat['outcome'],'retained');self.assertEqual(len(self.f.f.provider.calls),calls)
        with self.assertRaises(ValueError):self.call('launch',focus='Changed intent')
        # Actual provider execution is synthetic in this test; capture goes through maintained owner parsing.
        result=self.f.f.app.start(schedule_id=due['schedule_id']);self.assertEqual(result['outcome'],'succeeded',result)
        consumed=self.call('consume',occurrence=occurrence);self.assertTrue(consumed['required_capture'],consumed)
        again=self.call('consume',occurrence=occurrence);self.assertEqual(consumed,again)
        self.assertEqual(consumed['external_parent']['result_destination']['assignment_ref'],self.root.ref.to_dict())
    def test_unauthorized_file_authoring_grant_claims_and_restarted_grants_fail(self):
        r=self.request('launch',focus='Inspect installed docs')
        with self.assertRaises(PermissionError):self.s(r)
        author=OwnerAuthoringIngress(actor=self.f.server.owner.owner_actor,owner_actor=self.f.server.owner.owner_actor,directory=self.f.root/'author')
        with self.assertRaises(PermissionError):author.publish({'schema':author.schema,'request':r})
        for field in ('principal','actor','model','profile','assignment_ref','generation','pool_id','parent','caller_native_session_id'):
            with self.subTest(field=field),self.assertRaises(PermissionError):self.ingress.publish({'schema':self.ingress.schema,'request':{**r,field:'forged'}})
        self.ingress.publish({'schema':self.ingress.schema,'request':r})
        restart=OwnerExecutionIngress(actor=self.f.server.owner.owner_actor,owner_actor=self.f.server.owner.owner_actor,directory=self.ingress.directory)
        with self.assertRaises(PermissionError):restart.authorize(r)
    def test_stale_scope_allowance_occupied_capacity_and_foreign_result_fail_before_effects(self):
        calls=len(self.f.f.provider.calls);counts=self.f.f.store.consumer().snapshot_counts()
        baseline=copy.deepcopy(self.s.external_execution_policy)
        for field,value in [('generation',2),('task_ref',{**baseline['task_ref'],'revision':'rev-999'}),('worker_turn_allowance',1),('model','foreign'),('native_adapter','foreign'),('capacity_units',2),('max_depth',2)]:
            self.s.external_execution_policy={**baseline,field:value}
            with self.subTest(field=field),self.assertRaises(PermissionError):self.launch()
        self.s.external_execution_policy=baseline
        self.f.ingress.live_occurrence=lambda _:True
        with self.assertRaises(PermissionError):self.launch()
        self.f.ingress.live_occurrence=lambda _:False
        self.assertEqual(len(self.f.f.provider.calls),calls);self.assertEqual(self.f.f.store.consumer().snapshot_counts(),counts)
        with self.assertRaises(PermissionError):self.call('result',occurrence=handle(self.f.parent.to_dict()))
        response=self.launch();self.assertEqual(response['outcome'],'admitted',response)
        with self.assertRaises(PermissionError):self.launch(request_key='second-root-launch')
    def test_nested_classification_never_grants_new_execution_or_consumption(self):
        self.assertTrue(_starts_work(self.request('launch',focus='read')))
        self.assertEqual(_nested_capability(self.request('launch',focus='read')),'held')
        self.assertEqual(_nested_capability(self.request('consume',occurrence={})),'held')
        self.assertEqual(_nested_capability(self.request('result',occurrence={})),'admitted')

if __name__=='__main__':unittest.main()

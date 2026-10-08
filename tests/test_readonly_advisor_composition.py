"""Real owner/gateway/context fixture; provider only is substituted."""
import unittest
from pathlib import Path
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.agents.herzchen_adapter import HerzchenAdapterError
from otto.portfolio.advisor_execution import AdvisorExecution
from tests.test_execution_application import ExecutionApplicationTests
class ReadonlyAdvisorCompositionTests(unittest.TestCase):
    def setUp(self):
        self.f = ExecutionApplicationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
    def request(self):
        f=self.f
        advisor,guide,mandate=f.role_handles("project_advisor", "advisor", None)
        limits=LimitService(f.store)
        pool=limits.create_pool(ResourceRef("execution-owner", "limit", "scoped-readonly"), capacity_units=1,
            cumulative_allowance_units=1,logical_request_key="scoped-readonly-pool",actor=f.actor)
        integration=AdvisorExecution(execution=f.app,allowance=limits,allowance_ref=pool.ref.to_dict())
        request=dict(project_ref=f.project.ref.to_dict(),task_ref=f.task.ref.to_dict(),assignment_ref=advisor.ref.to_dict(),
            generation=1,mandate_ref=mandate,context_refs=(guide,mandate),request_key="scoped-readonly-advice",
            instruction="Inspect current project read-only.",model="gpt-test",reasoning="high",profile="read-only")
        return integration,limits,pool,request
    def test_readonly_advisor_omits_paired_caller_hooks_but_preserves_authorized_context(self):
        f=self.f;adapter=f.app.runtime.adapter;options=[];original=f.provider.binding
        def binding(**kw): options.append(kw);return original(**kw)
        adapter.binding_factory=binding;adapter.native_caller_socket=str(Path(f.temporary.name)/"manager.sock")
        def managed_observer(*a,**kw): raise AssertionError("manager/worker registration entered advisor")
        adapter.native_process_observer=managed_observer
        integration,limits,pool,request=self.request();result=integration.prepare_and_start(**request)
        self.assertEqual(result["outcome"],"succeeded",result)
        self.assertTrue(result["result"]["context_digest_verified"])
        self.assertTrue(options)
        self.assertTrue(all(x.get("native_caller_socket") is None and x.get("native_process_observer") is None for x in options))
        self.assertTrue(any(callable(x.get("recipient_authorizer")) for x in options))
        self.assertEqual(len(f.provider.calls),1)
        current=limits.get_pool(pool.ref);self.assertEqual((current.cumulative_used_units,current.held_units),(1,0))
        self.assertIs(adapter.native_process_observer,managed_observer) # configuration is not globally mutated
    def test_incomplete_caller_hook_pair_fails_before_initializer_and_allowance_reservation(self):
        f=self.f;adapter=f.app.runtime.adapter;adapter.native_caller_socket=str(Path(f.temporary.name)/"manager.sock")
        adapter.native_process_observer=None;options=[];original=f.provider.binding
        def binding(**kw):options.append(kw);return original(**kw)
        adapter.binding_factory=binding
        integration,limits,pool,request=self.request()
        with self.assertRaisesRegex(HerzchenAdapterError,"process observer"):
            integration.prepare_and_start(**request)
        self.assertEqual(options,[]);self.assertEqual(f.provider.calls,[])
        current=limits.get_pool(pool.ref);self.assertEqual((current.cumulative_used_units,current.held_units),(0,0))
    def test_binding_configuration_failure_is_detected_before_initializer_or_reservation(self):
        f=self.f;adapter=f.app.runtime.adapter
        def unsupported(**kw):raise HerzchenAdapterError("unsupported adapter hook")
        adapter.binding_factory=unsupported
        integration,limits,pool,request=self.request()
        with self.assertRaisesRegex(HerzchenAdapterError,"unsupported adapter hook"):
            integration.prepare_and_start(**request)
        self.assertEqual(f.provider.calls,[])
        current=limits.get_pool(pool.ref);self.assertEqual((current.cumulative_used_units,current.held_units),(0,0))
    def test_unrelated_worker_and_independent_observer_are_preserved(self):
        adapter=self.f.app.runtime.adapter;observer=lambda *a,**k:None;authorize=lambda *a:{}
        adapter.native_caller_socket=str(Path(self.f.temporary.name)/"manager.sock");adapter.native_process_observer=observer
        worker=adapter.bind_owner_authorization(authorize,role="worker",profile="workspace-write")
        self.assertEqual(worker.native_caller_socket,adapter.native_caller_socket);self.assertIs(worker.native_process_observer,observer)
        with self.assertRaisesRegex(HerzchenAdapterError,"workspace-write"):
            adapter.validate_owner_host_composition(role="worker",profile="read-only")
        adapter.native_caller_socket=None
        advisor=adapter.bind_owner_authorization(authorize,role="project_advisor",profile="read-only")
        self.assertIs(advisor.native_process_observer,observer)

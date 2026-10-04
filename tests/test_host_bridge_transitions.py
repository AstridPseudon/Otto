"""Existing retained schedule, real temporary owner Store, supported bridge contracts."""
from unittest.mock import patch
import unittest

from otto.host_bridge import DeterministicHostExecutor, host_trigger_capabilities
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.lifecycle import PortfolioLifecycleIntegration
from tests import test_execution_application as existing


class HostBridgeTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.ExecutionApplicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        integration, *_rest = self.fixture.advisor_fixture()
        self.attention = integration.loop.ports.attention
        self.schedule = "existing-advisor-followup"
        value = self.fixture.port.read_due(self.schedule)
        self.settings = {"id": "existing-automation", "kind": "heartbeat", "name": "Existing",
            "prompt": "Owner admission only", "rrule": "existing-cadence", "status": "ACTIVE",
            "targetThreadId": "owner-native-thread"}
        value["target"]["automation"] = dict(self.settings)
        self.fixture.port.save_due(self.schedule, value, request_id="fixture-existing-automation",
                                   expected_version=value["version"])
        self.updates = []
        self.response_lost = False
        self.executor = self.make_executor()

    def make_executor(self):
        def update(request):
            self.updates.append(dict(request))
            self.settings.update({key: request[key] for key in self.settings})
            return {"id": request["id"]}
        def read(effect, response):
            if self.response_lost:
                raise RuntimeError("persisted readback unavailable")
            return dict(self.settings)
        def ack(effect, observed):
            record = self.attention._read(effect.schedule_id)
            return self.attention.acknowledge_host(effect.schedule_id, request_id=effect.request_id,
                expected_version=record.version, actor="manager", project_ref=effect.project_ref,
                manager_ref=effect.manager_ref, generation=effect.generation, observed=observed)
        return DeterministicHostExecutor(update, read, ack)

    def call(self, key="ordinary-pause", **kwargs):
        return ExecutionHost.reconcile_trigger(attention=self.attention, executor=self.executor,
            schedule_id=self.schedule, request_id=key, actor=kwargs.pop("actor", "manager"),
            desired_state=kwargs.pop("desired_state", "paused"), **kwargs)

    def test_no_direct_port_still_has_bridge_and_pause_resume_are_independent_of_firing(self):
        self.assertIsNone(self.attention.host_port)
        capability = host_trigger_capabilities(attention=self.attention,
            record=self.attention._read(self.schedule), executor=self.executor, persisted_readback_available=True)
        self.assertFalse(capability["direct_owner_port"]["supplied"])
        self.assertTrue(capability["external_effect_bridge"]["executor_in_this_process"])
        self.assertFalse(capability["scheduled_callback"]["observed"])
        pause = self.call()
        self.assertEqual(pause["outcome"], "reconciled")
        self.assertTrue(pause["external_host_suspended"])
        self.assertEqual(self.settings["status"], "PAUSED")
        resumed = self.call("ordinary-resume", desired_state="active")
        self.assertEqual(resumed["outcome"], "reconciled")
        self.assertEqual(self.settings["status"], "ACTIVE")
        self.assertFalse(resumed["observed_scheduled_callback"])
        self.assertEqual(len(self.fixture.provider.calls), 0)

    def test_stop_persists_owner_state_and_pauses_external_through_same_bridge_once(self):
        result = self.call("ordinary-stop", owner_transition="stop")
        self.assertEqual(result["outcome"], "reconciled")
        self.assertEqual(result["owner_transition"]["outcome"], "stopped")
        self.assertEqual(self.attention._read(self.schedule).stop_state, "stopped")
        self.assertEqual(self.settings["status"], "PAUSED")
        self.executor = self.make_executor()
        replay = self.call("ordinary-stop", owner_transition="stop")
        self.assertEqual(replay["outcome"], "reconciled")
        self.assertEqual(len(self.updates), 1)
        active = self.call("unsafe-resume", desired_state="active")
        self.assertEqual(active["error"]["code"], "schedule_stopped")
        self.assertEqual(len(self.updates), 1)

    def test_recurring_completion_keeps_external_cadence(self):
        value = self.fixture.port.read_due(self.schedule)
        value["interval_seconds"] = 60
        self.fixture.port.save_due(self.schedule, value, request_id="fixture-existing-recurring",
                                   expected_version=value["version"])
        claim = self.attention.check(self.schedule, due_reason="fixture-retained-cadence")
        result = self.call(claim["request_id"], owner_transition="complete", completion={"outcome": "returned"})
        self.assertEqual(result["outcome"], "returned")
        self.assertFalse(result["external_host_suspended"])
        self.assertEqual(self.attention._read(self.schedule).stop_state, "active")
        self.assertEqual(self.settings["status"], "ACTIVE")
        self.assertEqual(len(self.updates), 0)

    def test_terminal_completion_pauses_external_automation(self):
        claim = self.attention.check(self.schedule, due_reason="fixture-retained-completion")
        result = self.call(claim["request_id"], owner_transition="complete", completion={"outcome": "returned"})
        self.assertEqual(result["outcome"], "reconciled")
        self.assertEqual(self.attention._read(self.schedule).stop_state, "completed")
        self.assertEqual(self.settings["status"], "PAUSED")
        self.assertEqual(len(self.updates), 1)
        self.assertEqual(len(self.fixture.provider.calls), 0)

    def test_low_level_owner_stop_does_not_suspend_external_automation(self):
        stopped = self.attention.stop(self.schedule, request_id="owner-state-only")
        self.assertEqual(stopped["outcome"], "stopped")
        self.assertEqual(self.settings["status"], "ACTIVE")
        self.assertEqual(len(self.updates), 0)

    def test_unknown_completion_does_not_become_host_success_or_retry(self):
        claim = self.attention.check(self.schedule, due_reason="fixture-unknown")
        result = self.call(claim["request_id"], owner_transition="complete", completion={"outcome": "unknown"})
        self.assertEqual(result["outcome"], "reconcile")
        self.assertFalse(result["external_host_suspended"])
        self.assertEqual(self.attention._read(self.schedule).completion_state, "unknown")
        self.assertEqual(len(self.updates), 0)
        self.assertEqual(len(self.fixture.provider.calls), 0)

    def test_failed_completion_does_not_pause_or_launch(self):
        claim = self.attention.check(self.schedule, due_reason="fixture-failed")
        result = self.call(claim["request_id"], owner_transition="complete", completion={"outcome": "failed"})
        self.assertEqual(result["outcome"], "completion-failed")
        self.assertFalse(result["external_host_suspended"])
        self.assertEqual(len(self.updates), 0)
        self.assertEqual(len(self.fixture.provider.calls), 0)

    def test_scope_and_cas_reject_before_owner_or_external_mutation(self):
        before = self.attention._read(self.schedule).to_dict()
        for kwargs in ({"actor": "foreign"}, {"generation": 99}, {"expected_version": 99},
                       {"project_ref": "foreign"}):
            with self.subTest(kwargs=kwargs):
                result = self.call(owner_transition="stop", **kwargs)
                self.assertEqual(result["outcome"], "rejected")
                self.assertEqual(self.attention._read(self.schedule).to_dict(), before)
        self.assertEqual(len(self.updates), 0)

    def test_lost_readback_recovers_same_effect_without_another_update(self):
        self.response_lost = True
        result = self.call("lost-pause", owner_transition="stop")
        self.assertEqual(result["outcome"], "response_lost")
        self.assertFalse(result["external_host_suspended"])
        self.response_lost = False
        self.executor = self.make_executor()
        recovered = self.call("lost-pause", owner_transition="stop")
        self.assertEqual(recovered["outcome"], "reconciled")
        self.assertTrue(recovered["external_host_suspended"])
        self.assertEqual(len(self.updates), 1)

    def test_existing_portfolio_caller_routes_its_scope_through_execution_host(self):
        caller = object.__new__(PortfolioLifecycleIntegration)
        caller.attention = self.attention
        caller._executor = self.executor
        caller._lifecycle_owner = "manager"
        caller._generation = self.attention._read(self.schedule).generation
        with patch.object(ExecutionHost, "reconcile_trigger", wraps=ExecutionHost.reconcile_trigger) as bridged:
            result = caller._run_schedule(self.schedule, request_id="portfolio-pause", desired_state="paused")
        self.assertEqual(result["outcome"], "reconciled")
        self.assertTrue(result["readback_exact"])
        self.assertEqual(bridged.call_count, 1)
        self.assertEqual(bridged.call_args.kwargs["expected_version"], result["prepared"]["effect"]["owner_version"])
        self.assertFalse(result["observed_scheduled_callback"])


if __name__ == "__main__":
    unittest.main()

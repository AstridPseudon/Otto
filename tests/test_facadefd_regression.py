"""Integrated descriptor and process-boundary regressions for owner facades."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from herzchen.contracts import ResourceRef
from herzchen.command_ports import owner_local_engine
from herzchen.kernel.limits import LimitService
from otto.portfolio.manager_assessment_command import manager_assessment_from_command
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from tests import test_local_assessment_composition as assessment_fixture


def _fd_count():
    for path in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(path):
            return len(os.listdir(path))
    raise unittest.SkipTest("process descriptor census is unavailable")


class FacadeFDRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = assessment_fixture.LocalAssessmentCompositionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture.f
        # The real owner budget reader consumes the pool persisted by the normal
        # owner pool API, and the assessment reader uses the same bound run state.
        self.fixture.request("PA01")
        self.policy = LocalAssessmentPolicy.from_run_config(self.fixture.config, state=self.fixture.state)
        f.owner.create_manager_assessment_pool(
            project_ref=self.fixture.state["project_ref"],
            task_ref=self.fixture.state["task_refs"]["PA01"],
            manager_assignment_ref=self.fixture.state["assignment_ref"],
            manager_actor="manager", manager_generation=1,
            logical_request_key="facadefd-pool", assessment_policy=self.policy)
        self.service = SimpleNamespace(server=SimpleNamespace(
            state={**self.fixture.state, "authority": f.actor.authority,
                   "assessment_policy": self.fixture.config}, store=f.store))

    def _assessment_coverage(self):
        f, fx = self.fixture.f, self.fixture
        request = fx.request("PA01", operation="coverage", arguments={}, key="facadefd-coverage")
        return manager_assessment_from_command(f.owner, state=fx.state, request=request)

    def test_200_real_owner_handoff_budget_reads_keep_descriptor_delta_bounded(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService

        service = object.__new__(ManagerJourneyService)
        service.server = self.service.server
        self.assertEqual(service._budget()["state"], "known")
        before = _fd_count()
        for _ in range(200):
            self.assertEqual(service._budget()["state"], "known")
        after = _fd_count()
        self.assertLessEqual(after - before, 3, f"200 owner budget reads: fd before={before}, after={after}")

    def test_200_real_owner_assessments_keep_descriptor_delta_bounded(self):
        self.assertEqual(self._assessment_coverage()["outcome"], "read")
        before = _fd_count()
        for _ in range(200):
            self.assertEqual(self._assessment_coverage()["outcome"], "read")
        after = _fd_count()
        self.assertLessEqual(after - before, 3, f"200 owner assessments: fd before={before}, after={after}")

    def test_200_routed_owner_facade_operations_keep_descriptor_delta_bounded(self):
        from otto.hostctl import config as host_config
        from otto.hostctl import lanes
        from otto.hostctl.owner import HostSession, create_store, join_host
        from otto.hostctl.service import OwnerService

        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            home = root / "home"
            config = host_config.new_installation(home, store_path=str(root / "owner.sqlite"),
                authority="facadefd-host", owner_actor="owner", operator_actor="operator",
                credential_ref="facadefd-credential", python=sys.executable)
            config = create_store(config)
            entry = host_config.host_entry("codex", principal="codex-principal", launcher=None,
                qualified_versions=[], model_profile="workspace-write")
            config["hosts"]["codex"] = join_host(config, entry)
            host_config.write(home, config)
            service = OwnerService(config)
            with HostSession(config) as session:
                service.store = session.store
                service._service_session = session
                service.started_at = "test"
                request = {"schema": lanes.REQUEST_SCHEMA, "command": "projects", "sub": None, "args": {}}
                lane = root / "request-lane"
                first = service._host_command("codex", request, "fd-regression", lane)
                self.assertEqual(first["outcome"], "read")
                before = _fd_count()
                for _ in range(200):
                    result = service._host_command("codex", request, "fd-regression", lane)
                    self.assertEqual(result["outcome"], "read")
                after = _fd_count()
                self.assertLessEqual(after - before, 3,
                    f"200 routed host projects reads: fd before={before}, after={after}")

    def test_cross_process_consumer_uses_live_owner_facade_socket(self):
        f = self.fixture.f
        limits = LimitService(f.store)
        pool_ref = self.policy.pool_ref
        transport = limits.consumer_transport()
        self.addCleanup(lambda: __import__("herzchen.command_ports", fromlist=["close_consumer_facade"])
                        .close_consumer_facade(transport))
        script = r'''import json,sys
from herzchen.command_ports import SerializedFacadeTransport,connect_consumer_facade
from herzchen.contracts import ResourceRef
t=SerializedFacadeTransport.from_dict(json.loads(sys.argv[1]))
c=connect_consumer_facade(t)
p=c.get_pool(ResourceRef.from_dict(json.loads(sys.argv[2])))
print(json.dumps({"capacity_units":p.capacity_units,"cumulative_allowance_units":p.cumulative_allowance_units}))
'''
        child_env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[1] / "src")
        child_env["PYTHONPATH"] = source_root + os.pathsep + child_env.get("PYTHONPATH", "")
        completed = subprocess.run([sys.executable, "-c", script, json.dumps(transport.to_dict()),
                                    json.dumps(pool_ref.to_dict())], check=False, capture_output=True,
                                   text=True, timeout=15, env=child_env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["capacity_units"], self.fixture.config["capacity_units"])
        self.assertEqual(result["cumulative_allowance_units"], self.fixture.config["cumulative_allowance_units"])

    def test_evidence_read_grant_is_bound_to_manager_and_exact_task(self):
        f, fx = self.fixture.f, self.fixture
        commands = f.owner.manager_assessment(project_ref=fx.state["project_ref"],
            task_ref=fx.state["task_refs"]["PA01"], manager_assignment_ref=fx.state["assignment_ref"],
            manager_actor="manager", manager_generation=1, assessment_policy=self.policy)
        module = owner_local_engine(commands._assessment._assessment)
        issuer = module._evidence_read_grant_issuer
        evidence = ResourceRef(f.actor.authority, "dat.content.document", "evidence-pin", "rev-1")
        task = ResourceRef.from_dict(fx.state["task_refs"]["PA01"])
        grant = issuer(evidence, task)
        self.assertEqual(grant.principal, f.owner.owner_actor)
        self.assertEqual(grant.requester.actor, "manager")
        self.assertEqual(grant.parent, task)
        self.assertEqual(grant.evidence, evidence)
        with self.assertRaises(PermissionError):
            issuer(evidence, ResourceRef.from_dict(fx.state["task_refs"]["PA06"]))
        with self.assertRaises(PermissionError):
            issuer(ResourceRef("foreign-authority", evidence.kind, evidence.id, evidence.revision), task)


if __name__ == "__main__":
    unittest.main()

"""Capacity follows processes; custody doesn't.

A hold whose process group is provably gone (pgid plus start time) stops
costing capacity but keeps its custody fence. A reused pid or pgid stays held.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.execution_host import ExecutionHost
from tests import test_worker_custody


def spawn_group(command=("sleep", "60")):
    # Own session, so the leader's pid is also its pgid (as the adapters spawn).
    return subprocess.Popen(list(command), start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class CapacityHoldTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_worker_custody.WorkerCustodyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.f.app
        self.schedule = self.fixture.schedule
        self.directory = Path(self.fixture.f.temporary.name) / "bounded-ipc"

    def host(self):
        return ExecutionHost(directory=self.directory, handler=lambda request: None,
                             bounded_transports=True)

    def hold(self, host):
        host.restore_execution(self.app, self.app._read(self.schedule))
        self.assertIn(self.schedule, host._capacity_holds)

    def group(self, command=("sleep", "60")):
        process = spawn_group(command)
        self.addCleanup(self.reap, process)
        return process

    @staticmethod
    def reap(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()

    def kill_group(self, process):
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()

    def test_dead_pgid_frees_capacity_keeps_fence(self):
        host = self.host()
        before = len(host.capacity_holds())
        self.hold(host)
        self.assertEqual(len(host.capacity_holds()), before + 1)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), before + 1, "a live group keeps its slot")

        self.kill_group(process)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        self.assertEqual(len(host.capacity_holds()), before)
        # The fence is custody: process exit does not prove absence of a provider effect.
        self.assertIn(self.schedule, host._capacity_holds)
        self.assertEqual(host.prepare_root_direction_adoption()["outcome"], "held")

        # Only an exact custody disposition releases the fence, and it takes the record with it.
        self.fixture.release()
        host.restore_execution(self.app, self.app._read(self.schedule))
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertEqual(len(host.capacity_holds()), before)
        self.assertEqual(host._process_groups, {})

    def test_restart_with_dead_hold_lists_fence_and_returns_capacity(self):
        first = self.host()
        before = len(first.capacity_holds())
        self.hold(first)
        process = self.group()
        first.record_process_group(self.schedule, process.pid)
        self.kill_group(process)

        restarted = self.host()
        self.hold(restarted)
        self.assertIn(self.schedule, restarted._capacity_holds, "the restart lists the fence")
        self.assertEqual(len(restarted.capacity_holds()), before,
                         "capacity is back to the pre-hold number")
        self.assertEqual(restarted.prepare_root_direction_adoption()["outcome"], "held")

    def test_reused_pid_stays_held(self):
        host = self.host()
        self.hold(host)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        # The pid is live again, but its start time is not the one recorded.
        record = host._process_groups[self.schedule]
        record["birth"] = [value + 1 for value in record["birth"]]
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)

    def test_reused_pid_after_group_death_stays_held(self):
        host = self.host()
        self.hold(host)
        host._process_groups[self.schedule] = {"pid": os.getpid(), "pgid": 2 ** 22 + 7,
            "birth": [0, 0]}  # our own pid is alive with another start time; the pgid is empty
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)

    def test_leader_gone_but_group_member_alive_stays_held(self):
        host = self.host()
        self.hold(host)
        process = subprocess.Popen(["sh", "-c", "sleep 60 & echo $! ; wait"], start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(self.reap, process)
        self.addCleanup(process.stdout.close)
        process.stdout.readline()  # the member exists before the leader dies
        host.record_process_group(self.schedule, process.pid)
        os.kill(process.pid, signal.SIGKILL)
        process.wait()
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)

    def test_hold_without_recorded_process_stays_held(self):
        host = self.host()
        self.hold(host)
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)

    def test_unreadable_or_malformed_record_stays_held(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "capacity-process-groups.json").write_text("{not json")
        host = self.host()
        self.hold(host)
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)
        host._process_groups[self.schedule] = {"pid": 1, "pgid": 0, "birth": "x"}
        self.assertEqual(host.reconcile_dead_holds(), [])
        self.assertEqual(len(host.capacity_holds()), 1)

    def test_record_requires_a_live_known_process(self):
        host = self.host()
        process = self.group()
        with self.assertRaises(RuntimeError):
            host.record_process_group(self.schedule, process.pid)  # no running job or hold
        self.hold(host)
        self.kill_group(process)
        with self.assertRaises(PermissionError):
            host.record_process_group(self.schedule, process.pid)  # already gone: nothing to bind

    def test_record_survives_in_the_host_directory_only(self):
        host = self.host()
        self.hold(host)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        saved = json.loads((self.directory / "capacity-process-groups.json").read_text())
        self.assertEqual(saved[self.schedule]["pgid"], process.pid)
        self.assertEqual(saved[self.schedule]["pid"], process.pid)

    def test_manager_recovery_releases_killed_unknown_worker_fence(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService

        f = self.fixture.f
        host = self.host()
        due = f.app._read(self.schedule)
        before = f.port.read_due(self.schedule)
        attempt_before = before["host_evidence"]["gateway_attempt"]
        host.restore_execution(f.app, due)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        self.kill_group(process)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        self.assertIn(self.schedule, host._capacity_holds,
                      "a killed worker keeps its owner custody fence")
        self.assertNotIn(self.schedule, host.capacity_holds(),
                         "a proven-dead process returns its capacity slot")

        scope = host._capacity_holds[self.schedule]
        follow_on = {**scope, "schedule_id": "follow-on-worker",
                     "assignment": ("execution-owner", "follow-on-assignment", 1),
                     "session": "follow-on-session"}
        self.assertFalse(host._eligible(follow_on),
                         "the unresolved worker fences another execution in its own project")
        other_project = {**follow_on, "project": "project-b",
                         "workspace": str(self.directory / "project-b")}
        self.assertTrue(host._eligible(other_project),
                        "the dead worker fence does not block another project's worker")

        manager_ref = {"authority": f.project.ref.authority, "kind": "wrk.assignment",
                       "id": "manager-for-capacity-recovery"}
        state = {"project_ref": f.project.ref.to_dict(), "manager": "manager",
                 "assignment_ref": manager_ref, "manager_generation": 1,
                 "schedule_id": self.schedule, "workers": {"J01": {"schedule_id": self.schedule}},
                 "requested_model": "gpt-test", "requested_reasoning": "high"}
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, due_port=f.port,
                                 store=f.store, state=state, _execution=lambda **_options: f.app)
        service = ManagerJourneyService(server=server, host=host,
            run_path=self.directory, workspace=Path(f.temporary.name))
        service._execution = lambda **_options: f.app
        service.commands._authorize = lambda: f.actor

        recovered = service._execution_control({"command": "execution-control",
            "operation": "recover", "schedule_id": self.schedule})

        self.assertIn(recovered.get("outcome"), {"released", "replayed"}, recovered)
        after = f.port.read_due(self.schedule)
        self.assertEqual(after["stop_state"], "stopped")
        self.assertEqual(after["completion_state"], "unknown")
        self.assertEqual(after["host_evidence"]["gateway_attempt"], attempt_before)
        self.assertIn("worker_custody_release", after["host_evidence"])
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertTrue(host._eligible(follow_on),
                        "manager disposition clears the same-project fence for follow-on work")
        self.assertEqual(f.provider.calls, [])
        replay = service._execution_control({"command": "execution-control",
            "operation": "recover", "schedule_id": self.schedule})
        self.assertEqual(replay["outcome"], "replayed")
        self.assertEqual(f.port.read_due(self.schedule), after)
        reports = f.app.assignments.list_observations(
            ResourceRef.from_dict(after["assignment_ref"]), kind="report")
        self.assertEqual(len(reports), 1, "recovery replay must not write another disposition")

        project_b = {"authority": "execution-owner", "kind": "work.project", "id": "project-b"}
        assignment_b = {"authority": "execution-owner", "kind": "wrk.assignment", "id": "manager-b"}
        state_b = {"project_ref": project_b, "manager": "manager-b",
                   "assignment_ref": assignment_b, "manager_generation": 1}
        second_server = SimpleNamespace(owner=f.owner, due_port=f.port, store=f.store, state=state_b)
        second_service = SimpleNamespace(host=host, server=second_server,
            workspace=self.directory / "project-b", run_path=self.directory / "project-b")
        from otto.portfolio.project_services import ProjectServices
        projects = ProjectServices({"project-a": service})
        projects.add_view("project-b", second_service)
        self.assertIn("project-b", projects.services)


if __name__ == "__main__":
    unittest.main()

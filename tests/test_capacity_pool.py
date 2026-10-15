"""One capacity pool for turns and heavy work (D3).

Units: a turn weighs one unit. Six shared turn units serve workers and managers,
two manager-reserve units serve managers only, and three heavy-headroom units
serve checks and other heavy work only. The host accounts them on kernel
``limits`` reservations (in the owner Store when one is supplied).
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from herzchen.kernel import Store
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import OwnerCompletion


class Turns:
    """Fake occurrences: each admitted turn stays running until released."""

    def __init__(self, host, root):
        self.host, self.root, self.completions = host, Path(root), {}
        self.dues = {}

    def due(self, name, role, project):
        return SimpleNamespace(schedule_id=name, project_ref=project, role=role, profile="read-only",
            target={}, host_evidence={}, assignment_ref={"authority": "pool", "id": name}, generation=1,
            stop_state="completed", completion_state="succeeded")

    def submit(self, name, role="worker", project=None):
        due = self.due(name, role, project or "project-" + name)
        self.dues[name] = due
        app = SimpleNamespace(
            runtime=SimpleNamespace(adapter=SimpleNamespace(owner_transport_only=True, worktree=str(self.root))),
            _read=lambda schedule: self.dues[schedule])
        completion = OwnerCompletion()
        self.completions[name] = completion
        self.host._owned(lambda: self.host.admit_execution(app, due, lambda: completion))

    def pump(self):
        self.host._owned(self.host._start_ready_executions)

    def finish(self, name):
        self.host._owned(lambda: self.completions[name].resolve("done"))
        self.pump()

    def running(self):
        return sorted(key for key, job in self.host._executions.items() if job["running"])

    def waiting(self):
        return sorted(key for key, job in self.host._executions.items() if not job["running"])


def spawn_group():
    return subprocess.Popen(["sleep", "60"], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PoolBehavior:
    """The pool contract; run once without a Store and once on a real one."""

    def make_host(self, directory):
        raise NotImplementedError

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="otto-pool-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.host = self.make_host(self.root / "ipc")
        self.turns = Turns(self.host, self.root)
        self.spawned = []
        self.addCleanup(self.reap_all)

    def reap_all(self):
        for process in self.spawned:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()

    def group(self):
        process = spawn_group()
        self.spawned.append(process)
        return process

    def fill_turns(self, workers=6, managers=2):
        for index in range(workers):
            self.turns.submit("worker-%d" % index, "worker")
        for index in range(managers):
            self.turns.submit("manager-%d" % index, "manager")
        self.turns.pump()

    def test_six_run_seventh_waits(self):
        for index in range(7):
            self.turns.submit("worker-%d" % index, "worker")
        self.turns.pump()
        self.assertEqual(len(self.turns.running()), 6)
        self.assertEqual(self.turns.waiting(), ["worker-6"])
        self.turns.finish("worker-0")
        self.assertEqual(self.turns.waiting(), [])
        self.assertIn("worker-6", self.turns.running())

    def test_manager_reserve(self):
        for index in range(8):
            self.turns.submit("worker-%d" % index, "worker")
        self.turns.pump()
        self.assertEqual(len(self.turns.running()), 6, "workers never take the manager reserve")
        for index in range(3):
            self.turns.submit("manager-%d" % index, "manager")
        self.turns.pump()
        running = self.turns.running()
        self.assertEqual([name for name in running if name.startswith("manager")],
                         ["manager-0", "manager-1"], "managers get a slot with every worker turn taken")
        self.assertEqual(self.turns.waiting(), ["manager-2", "worker-6", "worker-7"])

    def test_checks_run_while_turns_full(self):
        self.fill_turns()
        self.assertEqual(len(self.turns.running()), 8)
        pool = self.host.capacity
        check = pool.queue_heavy("check-a", 2, pid=os.getpid())
        self.assertTrue(pool.claim_heavy(check), "a check runs with every turn unit taken")
        second = pool.queue_heavy("check-b", 1, pid=os.getpid())
        self.assertTrue(pool.claim_heavy(second))
        third = pool.queue_heavy("check-c", 1, pid=os.getpid())
        self.assertFalse(pool.claim_heavy(third), "headroom is finite: the third check waits")
        pool.release_heavy(check)
        self.assertTrue(pool.claim_heavy(third))
        self.assertEqual(len(self.turns.running()), 8, "checks never evict turns")

    def test_heavy_work_does_not_take_turn_units(self):
        pool = self.host.capacity
        tickets = [pool.queue_heavy("check-%d" % index, 1, pid=os.getpid()) for index in range(3)]
        self.assertTrue(all(pool.claim_heavy(ticket) for ticket in tickets))
        self.fill_turns()
        self.assertEqual(len(self.turns.running()), 8, "full heavy headroom leaves every turn unit free")

    def test_heavy_weight_is_clamped_to_headroom(self):
        pool = self.host.capacity
        ticket = pool.queue_heavy("render", 99, pid=os.getpid())
        self.assertTrue(pool.claim_heavy(ticket), "an oversize request still gets the whole headroom")
        self.assertEqual(pool.snapshot()["heavy"]["used"], 3)

    def test_dead_waiter_frees_queue(self):
        pool = self.host.capacity
        holder = pool.queue_heavy("holder", 3, pid=os.getpid())
        self.assertTrue(pool.claim_heavy(holder))
        dying = self.group()
        dead = pool.queue_heavy("dead-waiter", 1, pid=dying.pid)
        alive = pool.queue_heavy("live-waiter", 1, pid=os.getpid())
        pool.release_heavy(holder)
        self.assertFalse(pool.claim_heavy(alive), "arrival order holds while the earlier waiter lives")
        os.killpg(dying.pid, signal.SIGKILL)
        dying.wait()
        self.assertTrue(pool.claim_heavy(alive), "a dead waiter no longer blocks the queue behind it")
        self.assertNotIn(dead, pool.snapshot()["heavy"]["waiting"])

    def test_dead_heavy_holder_frees_headroom(self):
        pool = self.host.capacity
        dying = self.group()
        lease = pool.queue_heavy("doomed", 3, pid=dying.pid)
        self.assertTrue(pool.claim_heavy(lease))
        waiting = pool.queue_heavy("next", 1, pid=os.getpid())
        self.assertFalse(pool.claim_heavy(waiting))
        os.killpg(dying.pid, signal.SIGKILL)
        dying.wait()
        self.assertEqual(self.host.reconcile_dead_holds(), [])
        self.assertTrue(pool.claim_heavy(waiting))

    def test_dead_hold_frees_waiting_turn(self):
        scopes = {}
        for index in range(6):
            name = "held-%d" % index
            scopes[name] = {"schedule_id": name, "project": "p-" + name, "role": "worker",
                            "session": "s-" + name, "assignment": ("pool", name, 1),
                            "workspace": str(self.root), "writer": False}
            self.host._capacity_holds[name] = scopes[name]
        self.turns.submit("worker-late", "worker")
        self.turns.pump()
        self.assertEqual(self.turns.running(), [], "six live holds fill the shared turn units")
        process = self.group()
        self.host.record_process_group("held-0", process.pid)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        self.assertEqual(self.host.reconcile_dead_holds(), ["held-0"])
        self.turns.pump()
        self.assertEqual(self.turns.running(), ["worker-late"], "a provably dead hold stops costing a slot")
        self.assertIn("held-0", self.host._capacity_holds, "the custody fence stays")

    def test_start_reconciles_dead_holds(self):
        name = "held-restart"
        self.host._capacity_holds[name] = {"schedule_id": name, "project": "p", "role": "worker",
            "session": "s", "assignment": ("pool", name, 1), "workspace": str(self.root), "writer": False}
        process = self.group()
        self.host.record_process_group(name, process.pid)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        self.assertEqual(len(self.host.capacity_holds()), 1)
        self.host.start()
        self.addCleanup(self.host.close)
        self.assertEqual(self.host.capacity_holds(), {}, "restart reconciles holds whose group is gone")
        self.assertIn(name, self.host._capacity_holds)

    def test_pin_native_process_records_the_group(self):
        name = "pinned"
        session = "native-session-1"
        self.host._capacity_holds.clear()
        self.turns.submit(name, "worker")
        self.turns.pump()
        self.assertEqual(self.turns.running(), [name])
        self.host._owned(lambda: self.host.bind_native_session(name, session))
        self.host.pin_native_process(name, session)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--resume", session],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.spawned.append(child)
        deadline = time.monotonic() + 10
        while name not in self.host._process_groups and time.monotonic() < deadline:
            self.host._owned(self.host._pin_native_groups)
            time.sleep(0.05)
        self.assertEqual(self.host._process_groups[name]["pgid"], child.pid)

    def test_pin_never_takes_a_shared_group(self):
        name = "shared-group"
        self.turns.submit(name, "worker")
        self.turns.pump()
        session = "native-session-2"
        self.host._owned(lambda: self.host.bind_native_session(name, session))
        self.host.pin_native_process(name, session)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--resume", session],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # our own group
        self.addCleanup(lambda: (child.kill(), child.wait()))
        for _ in range(5):
            self.host._owned(self.host._pin_native_groups)
            time.sleep(0.05)
        self.assertNotIn(name, self.host._process_groups, "only a group the native process leads is pinned")


class MemoryPoolTests(PoolBehavior, unittest.TestCase):
    def make_host(self, directory):
        return ExecutionHost(directory=directory, handler=lambda request: None, bounded_transports=True)


class StorePoolTests(PoolBehavior, unittest.TestCase):
    def make_host(self, directory):
        self.store = Store.create(self.root / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        return ExecutionHost(directory=directory, handler=lambda request: None, bounded_transports=True,
                             capacity_store=self.store)

    def test_reservations_live_in_the_store(self):
        self.fill_turns(workers=2, managers=1)
        snapshot = self.host.capacity.snapshot()
        self.assertEqual(snapshot["pool"]["held_units"], 3)
        self.turns.finish("worker-0")
        snapshot = self.host.capacity.snapshot()
        self.assertEqual(snapshot["pool"]["held_units"], 2, "a finished turn settles its reservation")
        self.assertEqual(snapshot["pool"]["cumulative_used_units"], 1)

    def test_restart_adopts_and_sweeps_reservations(self):
        self.fill_turns(workers=2, managers=0)
        again = ExecutionHost(directory=self.root / "ipc", handler=lambda request: None,
                              bounded_transports=True, capacity_store=self.store)
        # Nothing restored them as holds, so the old life's reservations are orphans.
        again.reconcile_dead_holds()
        self.assertEqual(again.capacity.snapshot()["pool"]["held_units"], 0)


class OwnerWiringTests(unittest.TestCase):
    def test_binding_a_native_session_pins_its_process(self):
        from unittest.mock import patch
        from tests import test_bounded_project_host as fixture
        journey = fixture.BoundedProjectHostTests()
        journey.setUp()
        self.addCleanup(journey.doCleanups)
        calls, original = [], ExecutionHost.pin_native_process

        def spy(host, schedule_id, session):
            calls.append((schedule_id, session))
            return original(host, schedule_id, session)

        with patch.object(ExecutionHost, "pin_native_process", spy):
            start = journey.send("A", {"command": "start-manager"})
            journey.wait(lambda: journey.native.has_started("manager-A"))
            journey.native.release("manager-A")
            self.assertEqual(journey.response(start)["outcome"], "succeeded")
        self.assertEqual([schedule for schedule, _ in calls], [journey.states["A"]["schedule_id"]])
        self.assertTrue(calls[0][1])


class ManagerCapIsGone(unittest.TestCase):
    def test_constructor_has_no_manager_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TypeError):
                ExecutionHost(directory=directory, handler=lambda request: None, manager_turn_limit=3)


if __name__ == "__main__":
    unittest.main()

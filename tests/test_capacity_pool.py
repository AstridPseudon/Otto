"""One capacity pool for turns and heavy work (D3).

Units: a turn weighs one unit. Six shared turn units serve workers and managers,
two manager-reserve units serve managers only, and three heavy-headroom units
serve checks and other heavy work only. The host accounts them on kernel
``limits`` reservations (in the owner Store when one is supplied).
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from dataclasses import fields
from types import SimpleNamespace
import threading
import unittest

from herzchen.domains.work import WorkGraph
from herzchen.fleet.capacity import CapacityPolicy
from herzchen.kernel import Store
from otto.agents.owner_runtime import _pin_process_group
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import OwnerCompletion
from tests import test_execution_application


def admitted_worker_fixture(test_case):
    fixture = test_execution_application.ExecutionApplicationTests()
    fixture.setUp()
    test_case.addCleanup(fixture.doCleanups)
    return fixture


def admitted_worker_due(fixture, name, project):
    task = WorkGraph(fixture.store, actor=fixture.actor).create_task(
        fixture.project.ref, title="Capacity task " + name, logical_request_key="task-" + name)
    fixture.task = task
    request = fixture.request()
    request["request_key"] = "worker-" + name
    prepared = fixture.app.assign_worker(**request)
    if prepared["outcome"] != "committed":
        raise AssertionError(prepared)
    return fixture.app._read(prepared["schedule_id"])


class Turns:
    """Fake occurrences: each admitted turn stays running until released."""

    def __init__(self, host, root, fixture):
        self.host, self.root, self.completions = host, Path(root), {}
        self.dues = {}
        self.admission_fixture = fixture
        app = fixture.app
        self.app = SimpleNamespace(
            runtime=app.runtime, portfolio=app.portfolio, binding=app.binding,
            actor=app.actor, _current=app._current,
            _read=lambda schedule: self.dues[schedule])

    def due(self, name, role, project):
        if role == "worker":
            # Keep the capacity occurrence synthetic, while borrowing its task,
            # exact assignment, admission stamp, and dependency graph from the
            # real owner fixture. The prelaunch gate can therefore run in full.
            admitted_due = admitted_worker_due(self.admission_fixture, name, project)
            target = dict(admitted_due.target)
            target["requested_profile"] = "read-only"
            values = {item.name: getattr(admitted_due, item.name) for item in fields(admitted_due)}
            values.update(schedule_id=name, role=role, project_ref=project,
                profile="read-only", target=target,
                host_evidence={"gateway_attempt": {"physical_session_id": "session-" + name}},
                stop_state="completed", completion_state="succeeded")
            return SimpleNamespace(**values)
        return SimpleNamespace(schedule_id=name, project_ref=project, role=role, profile="read-only",
            target={}, host_evidence={}, assignment_ref={"authority": "pool", "id": name}, generation=1,
            stop_state="completed", completion_state="succeeded")

    def submit(self, name, role="worker", project=None):
        due = self.due(name, role, project or "project-" + name)
        self.dues[name] = due
        app = self.app
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
        self.admission_fixture = admitted_worker_fixture(self)
        self.turns = Turns(self.host, self.root, self.admission_fixture)
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

    def test_worker_floor_caps_managers(self):
        for index in range(10):
            self.turns.submit("manager-%d" % index, "manager")
        self.turns.pump()
        self.assertEqual(len(self.turns.running()), 6, "managers stop at turn + reserve - worker floor")
        for index in range(2):
            self.turns.submit("worker-%d" % index, "worker")
        self.turns.pump()
        self.assertEqual([name for name in self.turns.running() if name.startswith("worker")],
                         ["worker-0", "worker-1"], "the worker floor is still open to workers")
        self.assertEqual(len(self.turns.running()), 8)

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
        self.assertEqual(again.capacity.snapshot()["turns"]["reserved"], 2, "the Store names both turns")
        # Nothing restored them as holds, so the old life's reservations are orphans.
        again.reconcile_dead_holds()
        self.assertEqual(again.capacity.snapshot()["pool"]["held_units"], 0)
        self.assertEqual(list((self.root / "ipc").glob("capacity-reservations.json")), [],
                         "the Store, not an index file, carries the reservations")

    def test_live_heavy_lease_survives_restart(self):
        pool = self.host.capacity
        lease = pool.queue_heavy("render", 2, pid=os.getpid())
        self.assertTrue(pool.claim_heavy(lease))
        again = ExecutionHost(directory=self.root / "ipc", handler=lambda request: None,
                              bounded_transports=True, capacity_store=self.store)
        self.assertEqual(again.capacity.snapshot()["heavy"]["used"], 2, "the restarted pool adopts the lease")
        self.assertEqual(again.reconcile_dead_holds(), [])
        self.assertEqual(again.capacity.snapshot()["heavy"]["used"], 2, "a live owner keeps its lease")

    def test_dead_heavy_lease_is_released_after_restart(self):
        dying = self.group()
        lease = self.host.capacity.queue_heavy("doomed", 3, pid=dying.pid)
        self.assertTrue(self.host.capacity.claim_heavy(lease))
        os.killpg(dying.pid, signal.SIGKILL)
        dying.wait()
        again = ExecutionHost(directory=self.root / "ipc", handler=lambda request: None,
                              bounded_transports=True, capacity_store=self.store)
        self.assertEqual(again.capacity.snapshot()["heavy"]["used"], 3, "adopted before the sweep")
        again.reconcile_dead_holds()
        self.assertEqual(again.capacity.snapshot()["heavy"]["used"], 0)
        self.assertEqual(again.capacity.snapshot()["pool"]["held_units"], 0)


class CapacityPolicyTests(unittest.TestCase):
    def test_default_tiers(self):
        policy = CapacityPolicy()
        self.assertEqual((policy.total_units, policy.worker_units, policy.manager_units), (11, 6, 6))

    def test_manager_admission_stops_at_its_units(self):
        policy = CapacityPolicy()
        self.assertTrue(policy.admits_turn("manager", 0, 5))
        self.assertFalse(policy.admits_turn("manager", 0, 6), "managers never pass turn + reserve - floor")
        self.assertFalse(policy.admits_turn("manager", 6, 2), "the whole pool is full for managers too")
        self.assertTrue(policy.admits_turn("manager", 5, 2), "a manager fills the last shared unit")

    def test_worker_admission_respects_the_floor(self):
        policy = CapacityPolicy()
        self.assertTrue(policy.admits_turn("worker", 5, 0))
        self.assertFalse(policy.admits_turn("worker", 6, 0))
        self.assertTrue(policy.admits_turn("worker", 1, 6), "managers beyond the reserve leave the floor open")
        self.assertFalse(policy.admits_turn("worker", 2, 6), "the floor is worker-only: 2 + 4 + 1 > 6")
        self.assertTrue(policy.admits_turn("worker", 0, 2), "the reserve alone costs workers nothing")

    def test_role_other_than_manager_counts_as_worker(self):
        policy = CapacityPolicy()
        self.assertEqual(policy.admits_turn("reviewer", 5, 0), policy.admits_turn("worker", 5, 0))
        self.assertEqual(policy.admits_turn("reviewer", 2, 6), policy.admits_turn("worker", 2, 6))

    def test_zero_reserve_and_zero_floor_are_valid(self):
        policy = CapacityPolicy(turn_units=4, manager_reserve=0, heavy_headroom=1, worker_floor=0)
        self.assertEqual(policy.manager_units, 4)
        self.assertTrue(policy.admits_turn("worker", 3, 0))
        self.assertFalse(policy.admits_turn("worker", 3, 1))

    def test_worker_floor_cannot_exceed_turn_units(self):
        with self.assertRaises(ValueError):
            CapacityPolicy(turn_units=2, manager_reserve=1, heavy_headroom=1, worker_floor=3)

    def test_invalid_units_are_rejected(self):
        for bad in ({"turn_units": 0}, {"heavy_headroom": 0}, {"manager_reserve": -1},
                    {"worker_floor": -1}, {"turn_units": True}, {"worker_floor": 1.0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                CapacityPolicy(**bad)


class ManagerCapIsGone(unittest.TestCase):
    def test_constructor_has_no_manager_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TypeError):
                ExecutionHost(directory=directory, handler=lambda request: None, manager_turn_limit=3)


class WorkerPinTests(unittest.TestCase):
    """The separate pin-only hook records a worker turn's own process group.

    The caller-socket observer is never involved: a worker is not a managed caller.
    """

    def make_host(self, directory):
        return ExecutionHost(directory=directory, handler=lambda request: None, bounded_transports=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="otto-pin-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.host = self.make_host(self.root / "ipc")
        self.admission_fixture = admitted_worker_fixture(self)
        self.turns = Turns(self.host, self.root, self.admission_fixture)
        self.spawned = []
        self.addCleanup(PoolBehavior.reap_all, self)

    def group(self):
        process = spawn_group()
        self.spawned.append(process)
        return process

    def running_turn(self, name):
        self.turns.submit(name, "worker")
        self.turns.pump()
        self.assertIn(name, self.turns.running())

    def test_owner_pin_hook_records_the_group(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        _pin_process_group(adapter, schedule)
        self.assertTrue(callable(adapter.process_pin), "the owner installs the pin-only hook")
        process = self.group()
        self.assertIsNone(self.host._owned(lambda: adapter.process_pin(process)))
        self.assertEqual(self.host._process_groups[schedule]["pgid"], process.pid)
        self.assertFalse(hasattr(adapter, "native_process_observer"), "the caller-socket observer is never touched")

    def test_recorded_group_is_force_stopped_by_owner_cleanup(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        _pin_process_group(adapter, schedule)
        process = self.group()
        self.host._owned(lambda: adapter.process_pin(process))
        self.assertEqual(self.host._terminate_recorded_process_groups(), {schedule: True})
        process.wait(timeout=5)
        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)

    def test_live_group_cannot_be_replaced_by_a_new_pin(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        _pin_process_group(adapter, schedule)
        first = self.group()
        second = self.group()
        self.host._owned(lambda: adapter.process_pin(first))
        with self.assertRaisesRegex(RuntimeError, "previous process group"):
            self.host._owned(lambda: adapter.process_pin(second))
        self.assertEqual(self.host._process_groups[schedule]["pid"], first.pid)
        saved = json.loads((self.host.directory / "capacity-process-groups.json").read_text())
        self.assertEqual(saved[schedule]["pid"], first.pid)

    def test_pin_failure_aborts_registration(self):
        schedule = "pin-failure-worker"
        self.running_turn(schedule)
        exited = subprocess.Popen(["true"])
        exited.wait()
        adapter = SimpleNamespace()
        _pin_process_group(adapter, schedule)
        with self.assertRaises(PermissionError):
            self.host._owned(lambda: adapter.process_pin(exited))
        self.assertNotIn(schedule, self.host._process_groups, "an exited pid pins nothing")

        live = self.group()
        unknown = SimpleNamespace()
        _pin_process_group(unknown, "no-such-occurrence")
        with self.assertRaises(RuntimeError):
            self.host._owned(lambda: unknown.process_pin(live))
        self.assertNotIn("no-such-occurrence", self.host._process_groups, "an unknown occurrence pins nothing")
        with self.assertRaises(RuntimeError):
            adapter.process_pin(live)
        self.assertNotIn(schedule, self.host._process_groups)

    def test_dead_worker_group_frees_its_reservation(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        _pin_process_group(adapter, schedule)
        process = self.group()
        self.host._owned(lambda: adapter.process_pin(process))
        # The running turn becomes a retained hold, as an unproven disposition makes it.
        self.host._executions.pop(schedule)
        self.host._capacity_holds[schedule] = {"schedule_id": schedule, "project": "project-w", "role": "worker",
            "session": "s-w", "assignment": ("pool", schedule, 1), "workspace": str(self.root), "writer": False}
        self.host.capacity.ensure_turn(schedule, uncertain=True)
        self.assertEqual(self.host.capacity.snapshot()["pool"]["held_units"], 1)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        self.assertEqual(self.host.reconcile_dead_holds(), [schedule])
        self.assertEqual(self.host.capacity.snapshot()["pool"]["held_units"], 0)
        self.assertEqual(self.host.capacity_holds(), {}, "the dead group no longer costs a slot")
        self.assertIn(schedule, self.host._capacity_holds, "the custody fence stays")

    def test_pin_from_the_transport_thread_reaches_the_owner(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        process = self.group()
        seen = {}

        def transport_operation():
            seen["transport"] = threading.get_ident()
            adapter.process_pin(process)

        def owner_work():
            seen["owner"] = threading.get_ident()
            _pin_process_group(adapter, schedule)  # the owner context exists at install time
            ExecutionHost.external_call(transport_operation)

        self.host._owned(owner_work)
        self.assertNotEqual(seen["transport"], seen["owner"], "the adapter pins from its transport thread")
        self.assertEqual(self.host._process_groups[schedule]["pgid"], process.pid)

    def test_pin_from_a_foreign_thread_outside_a_transport_wait_fails(self):
        schedule = "w"
        self.running_turn(schedule)
        adapter = SimpleNamespace()
        self.host._owned(lambda: _pin_process_group(adapter, schedule))
        process = self.group()
        errors = []

        def foreign():
            try:
                adapter.process_pin(process)
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=foreign)
        thread.start()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertNotIn(schedule, self.host._process_groups, "and pins nothing")

    def test_claude_worker_turn_is_pinned(self):
        # Bound copies keep the hook; the composition helper feeds the pin on every work process.
        import sys
        from otto.agents.claude_adapter import ClaudeWorkerAdapter, _compose_on_process
        from otto.agents.claude_cli import LauncherPin, VERSION, file_digest
        executable = str(Path(sys.executable).resolve())
        pin = LauncherPin(executable, executable, file_digest(Path(executable)), VERSION)
        adapter = ClaudeWorkerAdapter(owner="w", source=str(self.root), worktree=str(self.root),
            launcher_pin=pin, state_root=str(self.root), requested_model="gpt-test", transport=SimpleNamespace())
        self.assertIsNone(adapter.process_pin, "the hook is absent until the owner installs it")
        self.assertIsNone(adapter.native_process_observer)
        marker = lambda process: None
        adapter.process_pin = marker
        bound = adapter.bind_owner_authorization(lambda *args: {}, verifier=lambda *args: {},
                                                 role="worker", profile="workspace-write")
        self.assertIs(bound.process_pin, marker, "the bound copy keeps the pin hook")
        self.running_turn("w")
        _pin_process_group(bound, "w")
        self.assertIsNone(bound.native_process_observer, "a plain worker has no caller-socket observer")
        process = self.group()
        on_process = _compose_on_process(None, {"status": "authorized"}, bound.process_pin)
        cleanup = self.host._owned(lambda: on_process(process))
        self.assertTrue(callable(cleanup), "claude_cli requires a callable cleanup")
        self.assertIsNone(cleanup())
        self.assertEqual(self.host._process_groups["w"]["pgid"], process.pid, "the worker group is recorded")

    def test_claude_composition_order_and_absence(self):
        from otto.agents.claude_adapter import _compose_on_process
        events = []
        sentinel = lambda: events.append("released")
        process = SimpleNamespace(pid=1)

        def observer(seen, authorization):
            events.append(("observer", seen is process, authorization))
            return sentinel

        def pin(seen):
            events.append(("pin", seen is process))

        composed = _compose_on_process(observer, {"status": "authorized"}, pin)
        self.assertIs(composed(process), sentinel, "a manager returns the observer's cleanup")
        self.assertEqual(events, [("observer", True, {"status": "authorized"}), ("pin", True)],
                         "the caller-socket observer runs first, then the pin")
        self.assertIsNone(_compose_on_process(None, {}, None), "no observer and no pin means no callback")
        worker = _compose_on_process(None, {}, pin)
        self.assertTrue(callable(worker(process)), "a worker without an observer gets a no-op cleanup")
        self.assertIs(_compose_on_process(observer, {}, None)(process), sentinel,
                      "pin absent leaves the observer's cleanup unchanged")

    def test_codex_worker_turn_is_pinned(self):
        from unittest.mock import Mock, patch
        import herzchen.adapters.host as codex_host
        from herzchen.contracts import HostRequest, HostOperation, HostIdentity, ResourceRef
        for operation in (HostOperation.INVOKE, HostOperation.RESUME):
            with self.subTest(operation=operation.name):
                path = self.root / ("native-%s.jsonl" % operation.name)
                path.write_bytes((json.dumps({"type": "session_meta", "payload": {"id": "issued-session"}}) + "\n").encode())
                pin = Mock(name="process_pin")
                binding = codex_host.CodexCliBinding(
                    worktree=str(self.root), launcher="/fixture/codex", model="fixture", reasoning="high",
                    prompt="Exact current intent", process_pin=pin,
                    trusted_thread_reader=Mock(return_value={"thread": {"id": "issued-session", "path": str(path)}}))
                process = Mock(pid=4321, stdout=None, returncode=0)
                process.communicate.return_value = ("", "")
                with patch.object(codex_host.subprocess, "Popen", return_value=process) as popen, \
                        patch.object(codex_host, "_communicate_after_native_start", return_value=("", "", 0, None)):
                    binding.execute(HostRequest(operation, HostIdentity("fixture-worker", "issued-session"),
                                                ResourceRef("fixture", "work.task", "task", "rev-1"), "read-only"))
                self.assertEqual(popen.call_count, 1, "one native process per turn")
                pin.assert_called_once_with(process)

    def test_codex_without_pin_is_unchanged(self):
        from unittest.mock import Mock, patch
        import herzchen.adapters.host as codex_host
        from herzchen.contracts import HostRequest, HostOperation, HostIdentity, ResourceRef
        path = self.root / "native-none.jsonl"
        path.write_bytes((json.dumps({"type": "session_meta", "payload": {"id": "issued-session"}}) + "\n").encode())
        binding = codex_host.CodexCliBinding(
            worktree=str(self.root), launcher="/fixture/codex", model="fixture", reasoning="high",
            prompt="Exact current intent",
            trusted_thread_reader=Mock(return_value={"thread": {"id": "issued-session", "path": str(path)}}))
        self.assertIsNone(binding._process_pin)
        process = Mock(pid=4322, stdout=None, returncode=0)
        process.communicate.return_value = ("", "")
        with patch.object(codex_host.subprocess, "Popen", return_value=process) as popen, \
                patch.object(codex_host, "_communicate_after_native_start", return_value=("", "", 0, None)):
            binding.execute(HostRequest(HostOperation.RESUME, HostIdentity("fixture-worker", "issued-session"),
                                        ResourceRef("fixture", "work.task", "task", "rev-1"), "read-only"))
        self.assertEqual(popen.call_count, 1)


class StoreWorkerPinTests(WorkerPinTests):
    """The same pin contract on a real owner Store ledger."""

    def make_host(self, directory):
        self.store = Store.create(self.root / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        return ExecutionHost(directory=directory, handler=lambda request: None, bounded_transports=True,
                             capacity_store=self.store)


if __name__ == "__main__":
    unittest.main()

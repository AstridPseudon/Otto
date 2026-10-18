"""Capacity follows processes; custody doesn't.

A hold whose process group is provably gone (pgid plus start time) stops
costing capacity but keeps its custody fence. A reused pid or pgid stays held.
"""
import json
import os
from copy import deepcopy
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.execution_host import ExecutionHost
from tests import test_worker_custody


CLAUDE_DONE_PROCESS = r'''
import json, os, socket, sys
frame = json.loads(sys.stdin.readline())
prompt = frame['message']['content'][0]['text']
session = frame.get('session_id') or 'failed-worker-session'
def emit(value):
    print(json.dumps(value), flush=True)
def done():
    payload = {'op': 'call', 'token': os.environ['OTTO_DONE_TOKEN'],
               'tool': 'done', 'args': {'summary': 'Worker submitted before native terminal.'}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.connect(os.environ['OTTO_DONE_SOCKET'])
        channel.sendall((json.dumps(payload) + '\n').encode())
        reply = json.loads(channel.makefile().readline())
    with open(os.environ['OTTO_DONE_REPLY'], 'w') as out:
        json.dump(reply, out)
    if not reply.get('ok') or not reply.get('submitted'):
        raise RuntimeError('real owner worker-done refused: ' + repr(reply))
    return reply
emit({'type': 'system', 'subtype': 'init', 'session_id': session,
      'cwd': os.getcwd(), 'model': 'claude-haiku-5-5', 'permissionMode': 'dontAsk',
      'tools': ['Edit', 'Glob', 'Grep', 'Read', 'Write', 'mcp__otto__done'],
      'mcp_servers': [{'name': 'otto'}], 'plugins': [], 'skills': [], 'slash_commands': []})
emit({'type': 'user', 'uuid': 'input-work', 'session_id': session,
      'message': {'role': 'user', 'content': [{'type': 'text', 'text': prompt}]}})
if os.environ['OTTO_DONE_ORDER'] == 'before':
    emit({'type': 'assistant', 'uuid': 'assistant-done', 'session_id': session,
          'message': {'role': 'assistant', 'model': 'claude-haiku-5-5',
                      'content': [{'type': 'tool_use', 'id': 'done-1',
                                   'name': 'mcp__otto__done', 'input': {'summary': 'submitted'}}]}})
    reply = done()
    emit({'type': 'user', 'uuid': 'done-result', 'session_id': session,
          'message': {'role': 'user', 'content': [{'type': 'tool_result',
                      'tool_use_id': 'done-1', 'is_error': False, 'content': json.dumps(reply)}]}})
emit({'type': 'result', 'subtype': 'error_max_turns', 'is_error': True,
      'session_id': session, 'uuid': 'terminal-error', 'result': 'turn limit reached',
      'usage': {'input_tokens': 10, 'output_tokens': 4}})
if os.environ['OTTO_DONE_ORDER'] == 'after':
    done()
'''


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
        # Group disappearance can trail leader reaping by a scheduler tick.
        # Wait for it with no deadline: only a hang fails a test.
        while True:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)

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
        from otto.hostctl.project_service import ProjectOwnerService
        config = {"home": str(self.directory), "owner": {"actor": "owner"},
                  "store": {"authority": "capacity-hold-status", "domain_descriptor_digest": "digest"},
                  "hosts": {}, "max_active_manager_turns": 3}
        status = ProjectOwnerService(config,
            router=SimpleNamespace(host=host, store=object(), services={}))._status()
        action = next(row for row in status["native_capacity"]["hold_actions"]
                      if row["schedule_id"] == self.schedule)
        self.assertIn("complete-task", action["settling_command"])
        self.assertEqual(action["project"], self.app._resources(self.app._read(self.schedule)).target["project_ref"]["id"])

        # Only an exact custody disposition releases the fence, and it takes the record with it.
        self.fixture.release()
        host.restore_execution(self.app, self.app._read(self.schedule))
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertEqual(len(host.capacity_holds()), before)
        self.assertEqual(host._process_groups, {})

    def test_hold_in_another_project_does_not_block_root_direction_adoption(self):
        host = self.host()
        host._capacity_holds["project-A-worker"] = {
            "role": "worker", "project": "project-A", "schedule_id": "project-A-worker",
        }

        result = host.prepare_root_direction_adoption(project_ids={"project-B"})

        self.assertEqual(result["outcome"], "quiescent")

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

    def test_manager_recovery_releases_killed_unknown_worker_fence_capacity_case(self):
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

    def test_manager_recovery_settles_general_gone_unknown_worker(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        from otto.portfolio.execution import _digest

        f = self.fixture.f
        host = self.host()
        due = f.app._read(self.schedule)
        # Keep the canonical outcome UNKNOWN, but make this a general unknown
        # attempt rather than the narrowly qualified capacity failure.
        evidence = dict(due.host_evidence)
        attempt = dict(evidence["gateway_attempt"])
        result = dict(attempt["result"])
        result["error"] = {"code": "unclassified_unknown"}
        attempt["result"] = result
        evidence["gateway_attempt"] = attempt
        f.port.save_due(self.schedule, replace(due, host_evidence=evidence).to_dict(),
                        request_id="general-unknown-fixture", expected_version=due.version)
        due = f.app._read(self.schedule)
        before = f.port.read_due(self.schedule)
        attempt_before = before["host_evidence"]["gateway_attempt"]
        with self.assertRaises((ValueError, PermissionError)):
            f.app.inspect_capacity_failed_worker(schedule_id=self.schedule)
        host.restore_execution(f.app, due)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        self.assertIn(self.schedule, host._capacity_holds,
                      "a killed worker keeps its owner custody fence")
        self.assertIn(self.schedule, host.capacity_holds(), "live recorded group still occupies capacity")

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

        pins = {"expected_due_sha256": _digest(due.to_dict()),
                "expected_unknown_result_sha256": _digest(result)}
        base_request = {"command": "execution-control", "operation": "recover",
                        "schedule_id": self.schedule, "request_key": "gone-unknown-v1",
                        **pins, "reason": "Worker process was killed; settle its unknown attempt."}
        with self.assertRaisesRegex(ValueError, "reason"):
            service._execution_control({key: value for key, value in base_request.items() if key != "reason"})
        stale = service._execution_control({**base_request,
            "expected_due_sha256": "0" * 64})
        self.assertEqual(stale.get("outcome"), "refused", stale)
        self.assertTrue("stale" in stale.get("cause", "") or "pin" in stale.get("cause", ""), stale)
        live = service._execution_control(base_request)
        self.assertEqual(live.get("outcome"), "refused", live)
        self.assertIn("process_group_alive", live.get("cause", ""), live)
        self.assertEqual(f.port.read_due(self.schedule), before,
                         "live group refusal leaves the UNKNOWN occurrence untouched")

        self.kill_group(process)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        self.assertIn(self.schedule, host._capacity_holds,
                      "a killed worker keeps its owner custody fence until manager recovery")
        self.assertNotIn(self.schedule, host.capacity_holds(),
                         "a proven-dead process returns its capacity slot")
        scope = host._capacity_holds[self.schedule]
        follow_on = {**scope, "schedule_id": "follow-on-worker",
                     "assignment": ("execution-owner", "follow-on-assignment", 1),
                     "session": "follow-on-session"}
        self.assertFalse(host._eligible(follow_on), "unresolved worker fences its project")
        other_project = {**follow_on, "project": "project-b",
                         "workspace": str(self.directory / "project-b")}
        self.assertTrue(host._eligible(other_project), "fence does not block another project")

        recovered = service._execution_control(base_request)

        self.assertEqual(recovered.get("outcome"), "settled", recovered)
        after = f.port.read_due(self.schedule)
        self.assertEqual(after["stop_state"], "stopped")
        self.assertEqual(after["completion_state"], "unknown")
        self.assertIsNone(after["in_flight_request"])
        self.assertEqual(after["host_evidence"]["gateway_attempt"], attempt_before)
        self.assertIn("gone_unknown_worker_disposition", after["host_evidence"])
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertTrue(host._eligible(follow_on),
                        "manager disposition clears the same-project fence for follow-on work")
        self.assertEqual(f.provider.calls, [])
        replay = service._execution_control(base_request)
        self.assertEqual(replay["outcome"], "replayed")
        self.assertEqual(f.port.read_due(self.schedule), after)
        reports = f.app.assignments.list_observations(
            ResourceRef.from_dict(after["assignment_ref"]), kind="report")
        self.assertEqual(len(reports), 1, "recovery replay must not write another disposition")

        fresh_request = {**f.request(), "request_key": "post-recovery-launch"}
        fresh = f.app.assign_worker(**fresh_request)
        dispatched = f.app.assignments.dispatch(ResourceRef.from_dict(fresh["assignment_ref"]),
            expected_generation=fresh["generation"], logical_request_key="post-recovery-dispatch",
            actor=f.actor)
        self.assertEqual(dispatched.status, "dispatched")
        host.start()
        self.addCleanup(host.close)
        with host._command_lock:
            launched = host._owned(lambda: f.app.start(schedule_id=fresh["schedule_id"]))
        self.assertTrue(hasattr(launched, "then"), "fresh start enters the bounded host admission path")
        finished = threading.Event()
        launch_result = {}
        launched.then(lambda value: (launch_result.update(value or {}), finished.set()),
                      lambda error: (launch_result.update(error=str(error)), finished.set()))
        self.assertTrue(finished.wait(10), "fresh same-project owner execution did not finish")
        self.assertEqual(launch_result.get("outcome"), "succeeded", launch_result)
        self.assertEqual(len(f.provider.calls), 1, "fresh same-project dispatch reaches the provider")

    def test_manager_settles_gone_failed_worker_before_next_launch(self):
        from otto.portfolio.execution import _digest

        f = self.fixture.f
        due = f.app._read(self.schedule)
        evidence = deepcopy(due.host_evidence)
        result = evidence["gateway_attempt"]["result"]
        result["outcome"] = "failed"
        result["delivery_state"] = "failed"
        result["error"] = {"code": "claude_native_failure", "message": "error_max_turns"}
        f.port.save_due(self.schedule, replace(due, host_evidence=evidence).to_dict(),
                        request_id="failed-native-result", expected_version=due.version)
        due = f.app._read(self.schedule)
        original_attempt = deepcopy(due.host_evidence["gateway_attempt"])
        host = self.host()
        host.restore_execution(f.app, due)
        process = self.group()
        host.record_process_group(self.schedule, process.pid)

        request = dict(schedule_id=self.schedule, request_key="settle-gone-failed-worker",
            expected_due_sha256=_digest(due.to_dict()), expected_result_sha256=_digest(result),
            reason="The native worker ended with error_max_turns.")
        before = f.port.read_due(self.schedule)
        live = host.recover_gone_worker(f.app, **request)
        self.assertEqual(live["outcome"], "refused", live)
        self.assertEqual(live["cause"], "process_group_alive")
        self.assertEqual(f.port.read_due(self.schedule), before)

        self.kill_group(process)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        scope = host._capacity_holds[self.schedule]
        follow_on = {**scope, "schedule_id": "follow-on-worker",
                     "assignment": ("execution-owner", "next-assignment", 1),
                     "session": "next-session"}
        self.assertFalse(host._eligible(follow_on))
        self.assertTrue(host._eligible({**follow_on, "project": "project-b",
            "workspace": str(self.directory / "project-b")}))

        calls = len(f.provider.calls)
        settled = host.recover_gone_worker(f.app, **request)
        self.assertEqual(settled["outcome"], "settled", settled)
        after = f.port.read_due(self.schedule)
        self.assertEqual(after["stop_state"], "stopped")
        self.assertEqual(after["completion_state"], "failed")
        self.assertIsNone(after["in_flight_request"])
        self.assertEqual(after["host_evidence"]["gateway_attempt"], original_attempt)
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertTrue(host._eligible(follow_on))
        self.assertEqual(len(f.provider.calls), calls)
        self.assertEqual(host.recover_gone_worker(f.app, **request)["outcome"], "replayed")
        self.assertEqual(f.port.read_due(self.schedule), after)
        reports = f.app.assignments.list_observations(
            ResourceRef.from_dict(after["assignment_ref"]), kind="report")
        self.assertEqual(len(reports), 1)

        fresh = f.app.assign_worker(**{**f.request(), "request_key": "worker-after-failed-fence"})
        f.app.assignments.dispatch(ResourceRef.from_dict(fresh["assignment_ref"]),
            expected_generation=fresh["generation"],
            logical_request_key="dispatch-after-failed-fence", actor=f.actor)
        host.start()
        self.addCleanup(host.close)
        with host._command_lock:
            launched = host._owned(lambda: f.app.start(schedule_id=fresh["schedule_id"]))
        finished = threading.Event()
        answer = {}
        launched.then(lambda value: (answer.update(value or {}), finished.set()),
                      lambda error: (answer.update(error=str(error)), finished.set()))
        self.assertTrue(finished.wait(10), "fresh worker did not finish")
        self.assertEqual(answer["outcome"], "succeeded", answer)
        self.assertEqual(len(f.provider.calls), calls + 1)

    def test_failed_manager_recovery_exposes_pins_and_verifies_restart(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        from otto.portfolio.execution import _digest

        f = self.fixture.f
        due = f.app._read(self.schedule)
        evidence = deepcopy(due.host_evidence)
        result = evidence["gateway_attempt"]["result"]
        result.update(outcome="failed", delivery_state="failed",
                      error={"code": "claude_native_failure", "message": "error_max_turns"})
        f.port.save_due(self.schedule, replace(due, host_evidence=evidence).to_dict(),
                        request_id="failed-manager-fixture", expected_version=due.version)
        host = self.host()
        host.restore_execution(f.app, f.app._read(self.schedule))
        process = self.group()
        host.record_process_group(self.schedule, process.pid)
        state = {"project_ref": f.project.ref.to_dict(), "manager": "manager",
                 "schedule_id": self.schedule, "workers": {"J01": {"schedule_id": self.schedule}},
                 "requested_model": "gpt-test", "requested_reasoning": "high"}
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, due_port=f.port,
                                 store=f.store, state=state, _execution=lambda **_options: f.app)
        service = ManagerJourneyService(server=server, host=host,
            run_path=self.directory, workspace=Path(f.temporary.name))
        service._execution = lambda **_options: f.app
        service.commands._authorize = lambda: f.actor
        control = {"command": "execution-control", "schedule_id": self.schedule}
        read = service._execution_control({**control, "operation": "read",
            "request_key": None, "expected_due_sha256": None,
            "expected_result_sha256": None, "expected_unknown_result_sha256": None,
            "reason": None})
        recovery = read["recovery"]
        self.assertEqual(recovery["state"], "held_failed")
        pins = recovery["manager_gone_group_recovery"]
        self.assertEqual(pins["expected_result_sha256"], _digest(result))
        before_startup = f.port.read_due(self.schedule)
        startup = service._execution_control({"command": "execution-control", "operation": "startup"})
        worker_row = next(row for row in startup["occurrences"]
                          if row["schedule_id"] == self.schedule)
        self.assertEqual(worker_row["before"]["state"], "held_failed")
        self.assertEqual(worker_row["after"]["state"], "held_failed")
        self.assertEqual(f.port.read_due(self.schedule), before_startup)
        self.assertEqual(f.provider.calls, [])
        request = {**control, **pins, "operation": "recover",
                   "request_key": "manager-failed-v1", "reason": "Native turn exhausted."}
        request.pop("requires")
        request.pop("provider_called")
        request.pop("retry")
        from otto.hostctl.manager_client import build_parser
        parsed = vars(build_parser().parse_args(["execution-control", "--operation", "recover",
            "--schedule-id", self.schedule, "--request-key", request["request_key"],
            "--expected-due-sha256", request["expected_due_sha256"],
            "--expected-result-sha256", request["expected_result_sha256"],
            "--reason", request["reason"]]))
        self.assertEqual(parsed["expected_result_sha256"], request["expected_result_sha256"])
        self.assertEqual(service._execution_control(request)["cause"], "process_group_alive")
        self.assertEqual(service._execution_control({**request,
            "expected_result_sha256": "0" * 64})["cause"], "stale_pins")
        self.kill_group(process)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        settled = service._execution_control(request)
        self.assertEqual(settled["outcome"], "settled", settled)
        self.assertTrue(settled["historical_result_preserved"])
        self.assertFalse(settled["provider_called"])
        self.assertFalse(settled["retry"])
        self.assertEqual(service._execution_control(request)["outcome"], "replayed")
        after = f.app._read(self.schedule)
        restarted = self.host()
        restarted.restore_execution(f.app, after)
        self.assertNotIn(self.schedule, restarted._capacity_holds)

        changed = deepcopy(after.host_evidence)
        changed["gateway_attempt"]["result"]["error"]["message"] = "changed"
        f.port.save_due(self.schedule, replace(after, host_evidence=changed).to_dict(),
                        request_id="tamper-failed-result", expected_version=after.version)
        restarted.restore_execution(f.app, f.app._read(self.schedule))
        self.assertIn(self.schedule, restarted._capacity_holds)

    def _claude_done_order(self, order):
        from herzchen.fleet.tools import (DONE, FeedbackLedger, ToolFacade,
                                          ToolSpec, TokenBook, FacadeServer)
        from herzchen.fleet.tools.facade import LandingOwnerPort
        from herzchen.fleet.tools.pins import sole_server_grant
        from otto.agents.claude_cli import (ClaudeCliTransport, LauncherPin,
            VERSION, WORKER_TOOLS, file_digest)
        from otto.portfolio.execution import _digest
        from tests.test_claude_manager_admission import SyntheticScope
        from tests.test_landing import _Runner, _criterion, _project, _run, _service

        project_root = Path(self.fixture.f.temporary.name).resolve() / ("claude-" + order)
        project_root.mkdir()
        line, base, fleet = _project(project_root)
        landing, _ = _service(fleet, _Runner())
        context = lambda assignment: {"service": landing, "lab_name": "one", "task_id": "task-1",
            "assignment_id": assignment, "candidate": "candidate@1", "criterion": _criterion(),
            "parent_obligation": "obligation@1", "actor": "owner"}
        book = TokenBook()
        token = book.issue("worker-assignment", "worker")
        facade = ToolFacade((ToolSpec("done", DONE, "worker-done", args=("summary",)),),
                            {"worker": ("done",)}, LandingOwnerPort(context),
                            book, FeedbackLedger())
        socket_dir = tempfile.TemporaryDirectory(prefix="otto-done-", dir="/tmp")
        self.addCleanup(socket_dir.cleanup)
        socket_path = str(Path(socket_dir.name) / "s")
        server = FacadeServer(facade, socket_path)
        server.start()
        self.addCleanup(server.stop)
        reply_path = project_root / "done-reply.json"
        grant = sole_server_grant(server="otto", tools=("done",), command=sys.executable,
            token=token, token_env="OTTO_DONE_TOKEN", token_env_prefix="OTTO_")
        executable = str(Path(sys.executable).resolve())
        pin = LauncherPin(executable, executable, file_digest(Path(executable)), VERSION)
        state_root = project_root / "state"
        state_root.mkdir()
        processes = []
        def factory(_command, **kwargs):
            process = subprocess.Popen([sys.executable, "-c", CLAUDE_DONE_PROCESS], **kwargs)
            processes.append(process)
            return process
        transport = ClaudeCliTransport(pin,
            SyntheticScope(str(fleet.labs["one"].path), str(state_root), subprocesses=False),
            model="claude-haiku-5-5", reasoning="medium", timeout_seconds=20,
            process_factory=factory, tools=WORKER_TOOLS, mcp=grant,
            extra_env={"OTTO_DONE_SOCKET": socket_path, "OTTO_DONE_TOKEN": token,
                       "OTTO_DONE_REPLY": str(reply_path), "OTTO_DONE_ORDER": order})
        f = self.fixture.f
        host = self.host()
        host.restore_execution(f.app, f.app._read(self.schedule))
        def record(process):
            host.record_process_group(self.schedule, process.pid)
            return lambda: None
        result = transport.run("Finish the worker result.", session="failed-worker-session",
                               on_process=record)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["result"]["subtype"], "error_max_turns")
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].poll(), 0)
        self.assertEqual(host.reconcile_dead_holds(), [self.schedule])
        self.assertTrue(json.loads(reply_path.read_text())["submitted"])
        self.assertNotEqual(_run(line, "rev-parse", "refs/heads/main"), base,
                            "real worker-done must have landed before recovery")
        due = f.app._read(self.schedule)
        evidence = deepcopy(due.host_evidence)
        failed = evidence["gateway_attempt"]["result"]
        failed.update(outcome="failed", delivery_state="failed",
                      error={"code": "claude_native_failure", "message": "error_max_turns"},
                      native_failure=result["result"])
        f.port.save_due(self.schedule, replace(due, host_evidence=evidence).to_dict(),
                        request_id="claude-" + order + "-failed-result", expected_version=due.version)
        due = f.app._read(self.schedule)
        original_attempt = deepcopy(due.host_evidence["gateway_attempt"])
        host.restore_execution(f.app, due)
        request = {"schedule_id": self.schedule, "request_key": "claude-" + order + "-settlement",
                   "expected_due_sha256": _digest(due.to_dict()),
                   "expected_result_sha256": _digest(failed),
                   "reason": "Native error_max_turns after owner landing."}
        settled = host.recover_gone_worker(f.app, **request)
        self.assertEqual(settled["outcome"], "settled", settled)
        after = f.port.read_due(self.schedule)
        self.assertEqual(after["host_evidence"]["gateway_attempt"], original_attempt)
        self.assertEqual(after["completion_state"], "failed")
        self.assertNotIn(self.schedule, host._capacity_holds)
        self.assertEqual(f.provider.calls, [])

    def test_claude_error_then_landed_worker_done(self):
        self._claude_done_order("after")

    def test_claude_landed_worker_done_then_error(self):
        self._claude_done_order("before")



if __name__ == "__main__":
    unittest.main()

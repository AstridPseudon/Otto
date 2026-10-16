"""D02 owner faults and custody checks. Synthetic provider evidence is explicit."""
from __future__ import annotations
from dataclasses import replace
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.identity_context import HostCallerBinding, HostIngress
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.occurrence_reads import handle, lookup, result_view
from otto.agents.trusted_selection import TrustedAdapter, TrustedAdapterSelection
from otto.portfolio.tests import test_role_context as fixtures


class WorkerOccurrenceTests(unittest.TestCase):
    def setUp(self):
        self.roles = fixtures.RoleContextTests(); self.roles.setUp(); self.addCleanup(self.roles.doCleanups)
        self.f = self.roles.f
        manager, schedule, _ = self.roles.role()
        self.manager = manager
        self.assertEqual(self.f.app.start(schedule_id=schedule)["outcome"], "succeeded")
        self.parent_request = dict(self.f.request(), request_key="coordinating-parent")
        self.parent_request["instruction_contract"]["delegation"] = {"max_depth": 1, "result_consumption": "yield"}
        self.parent_request["instruction_contract"]["allowed_operations"].append("canonical_child_commands")
        self.parent_request["instruction_contract"]["authority"]["permitted_effects"].append("canonical_child_commands")
        parent = self.f.app.assign_and_start(**self.parent_request)
        self.assertEqual(parent["outcome"], "succeeded", parent)
        self.parent = self.f.app._read(parent["schedule_id"])
        self.root = Path(self.f.temporary.name).resolve()
        self.run = self.root / "run"; self.run.mkdir()
        self.config = {"roles": {"worker_normal": {"model": "gpt-test", "reasoning": "high"},
                                 "worker_xhard": {"model": "gpt-test", "reasoning": "high"}},
                       "worker_operation_profiles": {"D02": "coordinating_implementation"}}
        (self.run / "run.yaml").write_text(json.dumps(self.config))
        state = {"owner": "manager", "manager": "manager", "assignment_ref": manager.ref.to_dict(),
            "manager_generation": 1, "project_ref": self.f.project.ref.to_dict(),
            "task_refs": {"D02": self.f.task.ref.to_dict()}, "criterion_refs": {},
            "requested_model": "gpt-test", "requested_reasoning": "high", "schedule_id": schedule,
            "workers": {"D02": {**parent, "principal": "worker", "model": "gpt-test", "reasoning": "high"}}}
        self.server = SimpleNamespace(state=state, owner=self.f.owner, portfolio=self.f.app.portfolio,
            due_port=self.f.port, binding=self.f.binding, _save_state=lambda: None,
            _execution=lambda **options: self.f.app)
        self.bindings = {}
        self.ingress = SimpleNamespace(live_occurrence=lambda schedule: False)
        class Ingress:
            def __call__(inner, ingress): return self.bindings[ingress.handle]
            def live_occurrence(inner, schedule): return self.ingress.live_occurrence(schedule)
        self.host = ExecutionHost(directory=self.root / "ipc", handler=lambda request: None,
            caller_binding_reader=Ingress(), caller_context_resolver=self.f.app.caller_context, owner_file_compatibility=True)
        self.host.directory.mkdir()
        self.service = ManagerJourneyService(server=self.server, host=self.host, run_path=self.run,
            workspace=self.root, delegation_policy={"coordinators": [{"assignment_ref": self.parent.assignment_ref, "generation": 1,
                "native_adapter": self.parent.target["native_adapter"]}], "max_depth": 1,
                "capacity_units": 1, "cumulative_allowance_units": 5})
        self.host.handler = self.service
        # This is a synthetic live-admission owner fault fixture. A completed
        # provider transcript is not labeled authentic local process custody.
        self.live = replace(self.parent, stop_state="active", completion_state="none", delivery_state="ready")
        self.f.port.save_due(self.parent.schedule_id, self.live.to_dict(), request_id="parent-live", expected_version=self.parent.version)
        self.bindings["parent"] = self.binding(self.live)
        self.request = {"command": "run-worker", "task": "D02", "route": "normal", "principal": "leaf",
                        "request_key": "bounded-child", "focus": "Investigate one bounded source seam and return evidence."}

    def binding(self, due):
        auth = due.host_evidence["gateway_attempt"]["delivery_authorization"]
        return HostCallerBinding(self.f.binding.authenticated_actor(due.recipient),
            ResourceRef.from_dict(due.assignment_ref), due.generation, self.f.app.native_adapter_identity(),
            auth["physical_session_id"], due.schedule_id)

    def launch(self):
        return self.host._dispatch(self.request, ingress=HostIngress("synthetic-owner-caller", "parent"))

    def owner(self, command, schedule):
        return self.host._dispatch({"command": command, "schedule_id": schedule},
            ingress=HostIngress("file-ipc", self.host.directory / "owned-request"))

    def yield_parent(self):
        current = self.f.app._read(self.parent.schedule_id)
        self.f.port.save_due(current.schedule_id, self.parent.to_dict(), request_id="parent-yielded",
                             expected_version=current.version)

    def test_inert_child_separate_assignment_history_lookup_and_parent_consumption(self):
        slot = copy.deepcopy(self.server.state["workers"])
        calls = len(self.f.provider.calls)
        response = self.launch()
        self.assertEqual(response["outcome"], "prepared", response)
        occurrence = response["occurrence"]
        self.assertEqual(self.server.state["workers"], slot)
        self.assertEqual(len(self.f.provider.calls), calls)
        child = self.f.app._read(occurrence["schedule_id"])
        self.assertNotEqual(child.assignment_ref, self.parent.assignment_ref)
        assignment = self.f.app.assignments.get(ResourceRef.from_dict(child.assignment_ref))
        self.assertEqual(assignment.payload["parent"], child.target["parent"])
        from otto.portfolio.owner_readers import mandate_reader
        mandate = mandate_reader(self.f.app.portfolio.operations, child.target["project_ref"], child.target["mandate_ref"])({key: child.target["mandate_ref"][key] for key in ("authority", "kind", "id")})
        self.assertNotIn("delegation", mandate["payload"]["instruction_contract"], "children remain finite leaves under coordinating task defaults")
        self.assertEqual(self.owner("start-retained-child", child.schedule_id)["outcome"], "pending")
        self.assertEqual(len(self.f.provider.calls), calls)
        counts = self.f.store.consumer().snapshot_counts()
        read = {"command": "lookup-occurrence", "scope": child.target["launch_request"]["scope"],
                "request_key": self.request["request_key"], "request_input": self.request}
        first = self.host._dispatch(read, ingress=HostIngress("synthetic-owner-caller", "parent"))
        self.config["roles"]["worker_normal"]["model"] = "changed-default"
        (self.run / "run.yaml").write_text(json.dumps(self.config))
        self.server.state["workers"]["D02"] = {"assignment_ref": {"id": "replacement"}}
        second = self.host._dispatch(read, ingress=HostIngress("synthetic-owner-caller", "parent"))
        self.assertEqual(first, second)
        self.assertEqual(first["selection"]["model"], "gpt-test")
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        changed = copy.deepcopy(read); changed["request_input"]["focus"] = "changed"
        self.assertEqual(self.host._dispatch(changed, ingress=HostIngress("synthetic-owner-caller", "parent"))["outcome"], "conflict")
        self.server.state["workers"] = slot
        self.yield_parent()
        self.ingress.live_occurrence = lambda schedule: schedule == self.parent.schedule_id
        self.assertEqual(self.owner("start-retained-child", child.schedule_id)["outcome"], "pending")
        self.assertEqual(len(self.f.provider.calls), calls)
        self.ingress.live_occurrence = lambda schedule: False
        launched = self.owner("start-retained-child", child.schedule_id)
        self.assertEqual(launched["outcome"], "succeeded", launched)
        self.assertEqual(len(self.f.provider.calls), calls + 1)
        captured = self.f.port.read_due(child.schedule_id)
        without_capture = copy.deepcopy(captured)
        without_capture["host_evidence"].pop("captured_result_summary")
        self.assertFalse(result_view(without_capture)["required_capture"], "native terminality is not canonical publication")
        self.assertIsNone(result_view(without_capture)["conclusion"])
        self.service.delegation_policy["cumulative_allowance_units"] = len(self.f.port.list_due({"project_ref": self.f.project.id, "role": "worker"}))
        blocked = self.owner("parent-child-result", child.schedule_id)
        self.assertEqual(blocked["outcome"], "error", blocked)
        self.assertEqual(len(self.f.provider.calls), calls + 1, "continuation requires remaining allowance")
        self.service.delegation_policy["cumulative_allowance_units"] = 5
        callback = self.owner("parent-child-result", child.schedule_id)
        self.assertEqual(callback["outcome"], "succeeded", callback)
        continued = self.f.app._read(callback["schedule_id"])
        self.bindings["continued"] = self.binding(continued)
        consume = {"command": "consume-result", "occurrence": occurrence}
        result = self.host._dispatch(consume, ingress=HostIngress("synthetic-owner-caller", "continued"))
        self.assertEqual(result["parent_delivery"]["state"], "consumed", result)
        self.assertIn("tests pass", result["conclusion"])
        records = self.f.app.assignments.list_observations(ResourceRef.from_dict(self.parent.assignment_ref), kind="report")
        self.assertEqual(len(records), 1)
        repeat = self.host._dispatch(consume, ingress=HostIngress("synthetic-owner-caller", "continued"))
        self.assertEqual(result, repeat)
        self.assertEqual(len(self.f.provider.calls), calls + 2)
        self.assertEqual(self.server.state["workers"], slot)
        for command in ("review-task", "finish-task", "execution-control", "task-list-author"):
            denied = self.host._dispatch({"command": command}, ingress=HostIngress("synthetic-owner-caller", "continued"))
            self.assertEqual(denied["outcome"], "error", denied)
            self.assertFalse(denied["effects_started"])

    def test_claims_policy_scope_generation_and_leaf_fail_before_useful_effect(self):
        calls = len(self.f.provider.calls)
        for request in (dict(self.request, caller_principal="manager"), dict(self.request, caller_generation=2),
                        dict(self.request, caller_native_session_id="foreign"), dict(self.request, task="foreign"),
                        dict(self.request, caller_context={"principal": "manager"})):
            response = self.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "parent"))
            self.assertEqual(response["outcome"], "error", response)
            self.assertFalse(response["effects_started"])
        self.service.delegation_policy["max_depth"] = 2
        self.assertEqual(self.launch()["outcome"], "error")
        self.service.delegation_policy["max_depth"] = 1
        self.service.delegation_policy["cumulative_allowance_units"] = 1
        self.assertEqual(self.launch()["outcome"], "error")
        self.assertEqual(len(self.f.provider.calls), calls)

    def test_historical_lookup_and_result_are_pure_and_foreign_parent_denied(self):
        response = self.launch(); self.assertEqual(response["outcome"], "prepared", response)
        occurrence = response["occurrence"]
        counts = self.f.store.consumer().snapshot_counts()
        request = {"command": "read-result", "occurrence": occurrence}
        before = self.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "parent"))
        self.assertTrue(before["pure"]); self.assertFalse(before["required_capture"])
        self.assertEqual(self.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "parent")), before)
        self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
        self.bindings["foreign"] = replace(self.bindings["parent"], generation=2)
        denied = self.host._dispatch(request, ingress=HostIngress("synthetic-owner-caller", "foreign"))
        self.assertEqual(denied["outcome"], "error")
        self.assertFalse(denied["effects_started"])

    def test_retained_parent_and_selection_cannot_be_rewritten_and_replacement_fences_launch(self):
        from otto.attention import InputChangedError, InMemoryDueRecordPort
        response = self.launch()
        self.assertEqual(response["outcome"], "prepared", response)
        child = self.f.port.read_due(response["schedule_id"])
        for field in ("parent", "launch_request"):
            changed = copy.deepcopy(child)
            changed["target"][field] = None
            with self.assertRaises(InputChangedError):
                self.f.port.save_due(child["schedule_id"], changed, request_id="rewrite-" + field, expected_version=child["version"])
            memory = InMemoryDueRecordPort()
            saved = memory.save_due(child["schedule_id"], child, request_id="create", expected_version=0)
            with self.assertRaises(InputChangedError):
                memory.save_due(child["schedule_id"], changed, request_id="rewrite", expected_version=saved["version"])
        self.yield_parent()
        self.server.state["workers"]["D02"] = {"assignment_ref": {"id": "replacement"}}
        calls = len(self.f.provider.calls)
        denied = self.owner("start-retained-child", child["schedule_id"])
        self.assertEqual(denied["outcome"], "error", denied)
        self.assertEqual(len(self.f.provider.calls), calls)

    def test_lost_socket_reply_resolves_original_intent_without_resending(self):
        """Real transport loss; synthetic owner binding is explicitly scoped.

        Kernel caller custody is qualified independently by the Popen test.
        Here the fault is placed at the response boundary after preparation.
        """
        import socket
        import threading
        from otto.portfolio.caller_client import call_connection
        client, owner = socket.socketpair()
        client.settimeout(5); owner.settimeout(5)
        self.addCleanup(client.close); self.addCleanup(owner.close)
        self.bindings[owner] = self.bindings["parent"]
        lost = []
        thread = threading.Thread(target=lambda: lost.append(call_connection(client, self.request)))
        thread.start()
        try:
            raw = b""
            while not raw.endswith(b"\n"): raw += owner.recv(262144)
            prepared = self.host._dispatch(json.loads(raw), ingress=HostIngress("unix-socket", owner))
            self.assertEqual(prepared["outcome"], "prepared", prepared)
            owner.shutdown(socket.SHUT_RDWR); owner.close()  # drop the reply, not the intent
            thread.join(5); self.assertFalse(thread.is_alive())
            self.assertEqual(lost[0]["outcome"], "unknown")
            self.assertEqual(lost[0]["error"]["kind"], "transport")
            self.assertFalse(lost[0]["retry"])
            child = self.f.port.read_due(prepared["schedule_id"])
            counts = self.f.store.consumer().snapshot_counts()
            calls = len(self.f.provider.calls)
            found = self.host._dispatch({"command": "lookup-occurrence", "scope": child["target"]["launch_request"]["scope"],
                "request_key": self.request["request_key"], "request_input": self.request},
                ingress=HostIngress("synthetic-owner-caller", "parent"))
            self.assertEqual(found["outcome"], "found", found)
            self.assertEqual(found["occurrence"], prepared["occurrence"])
            self.assertEqual(found["handles"]["outer_command"], lost[0]["outer_command"])
            self.assertEqual(found["handles"]["start"], prepared["start"])
            self.assertEqual(self.f.store.consumer().snapshot_counts(), counts)
            self.assertEqual(len(self.f.provider.calls), calls)
        finally:
            owner.close(); client.close(); thread.join(5)


class TrustedSelectionTests(unittest.TestCase):
    def test_finite_choices_defaults_override_provenance_and_no_fallback(self):
        calls = []
        selected = TrustedAdapter("qualified", lambda **kw: calls.append(kw) or SimpleNamespace(native_adapter_identity=lambda: "qualified"),
            frozenset({"one", "two"}), frozenset({"workspace-write"}), {"launcher_sha256": "pinned", "schema": "native-v1"})
        choices = TrustedAdapterSelection({"codex": selected})
        value = choices.resolve(role={"model": "one"}, defaults={"adapter": "codex", "reasoning": "high"})
        self.assertEqual(value["provenance"], {"adapter": "user_default", "model": "project_role", "reasoning": "user_default"})
        self.assertEqual(calls, [], "selection/preparation is inert")
        choices.compose(value, principal="worker")
        self.assertEqual(len(calls), 1)
        self.assertEqual(choices.resolve(role={"model": "one"}, override={"model": "two"}, defaults={"adapter": "codex", "reasoning": "high"})["model"], "two")
        for role in ({"adapter": "untrusted", "model": "one", "reasoning": "high"},
                     {"adapter": "codex", "model": "missing", "reasoning": "high"}):
            with self.assertRaises(ValueError): choices.resolve(role=role)
        self.assertEqual(len(calls), 1)


class NativeWorkerProcessTests(unittest.TestCase):
    """Authentic local process/kernel ingress; provider transcript is a fixture.

    Anonymous sockets are passed using SCM_RIGHTS. The command socket is
    created by the child so the actual kernel peer audit token belongs to the
    Popen process, never the owner that created the bootstrap socket pair.
    This exercises the production ingress without a named-socket listener.
    """
    def test_capacity_one_real_parent_distinct_leaf_then_authenticated_consumption(self):
        import array
        import os
        import socket
        import subprocess
        import sys
        from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress, managed_caller_binding, socket_peer_pid
        from tests import test_execution_application as provider_fixture
        from otto.portfolio.occurrence_reads import digest
        fixture = WorkerOccurrenceTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        f, service, host, server = fixture.f, fixture.service, fixture.host, fixture.server
        fixture.yield_parent()
        request = dict(fixture.parent_request, request_key="real-process-parent")
        parent = f.app.assign_worker(**request)
        self.assertEqual(parent["outcome"], "committed", parent)
        server.state["workers"]["D02"] = {**parent, "principal": "worker", "model": "gpt-test", "reasoning": "high"}
        service.delegation_policy['coordinators'] = [{'assignment_ref':parent['assignment_ref'],'generation':1,'native_adapter':f.app.native_adapter_identity()}]
        original_slot = copy.deepcopy(server.state["workers"])
        ingress = NativeProcessCallerIngress(lambda authorization: managed_caller_binding(server, authorization))
        host.caller_binding_reader = ingress
        receipts, replies, pids = [], [], []
        current_leaf = {}
        program = r'''
import array,json,os,socket,sys
control=socket.socket(fileno=int(sys.argv[1]))
control.recv(1)
a,b=socket.socketpair()
control.sendmsg([b'x'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[a.fileno()]))])
a.close();control.close()
config=json.loads(sys.stdin.readline())
if config['kind']=='leaf':
    open(config['artifact'],'w').write('Useful distinct leaf process artifact.\n')
    payload={'command':'whoami'}
else:payload=config['request']
from otto.portfolio.caller_client import call_connection
reply=call_connection(b,payload)
print(json.dumps({'pid':os.getpid(),'kind':config['kind'],'reply':reply}),flush=True)
b.close()
'''
        def factory(**options):
            original = provider_fixture.ProviderBinding(f.provider, options)
            class Binding:
                def supports(inner, operation): return original.supports(operation)
                def execute(inner, native_request):
                    if not options.get("delivered_brief"):
                        return original.execute(native_request)  # inert initializer
                    authorization = options["recipient_authorizer"](native_request)
                    turn = "provider-turn-" + str(len(f.provider.calls) + 1)
                    if options.get("native_start_callback"):
                        options["native_start_callback"](turn, provider_fixture.NOW.isoformat())
                    key = authorization["logical_request_key"]
                    kind = "consume" if key.startswith("parent-result:") else "leaf" if authorization["principal"] == "leaf" else "parent"
                    control, child_control = socket.socketpair()
                    process = subprocess.Popen([sys.executable, "-c", program, str(child_control.fileno())],
                        pass_fds=(child_control.fileno(),), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True)
                    child_control.close(); pids.append(process.pid)
                    cleanup = lambda: None
                    try:
                        control.sendall(b'g')
                        raw, ancillary, flags, address = control.recvmsg(1, socket.CMSG_SPACE(4))
                        descriptors = array.array('i'); descriptors.frombytes(ancillary[0][2][:4])
                        command_socket = socket.socket(fileno=descriptors[0]); command_socket.settimeout(5)
                        with self.assertRaises(PermissionError):
                            ingress(HostIngress("unix-socket", command_socket))
                        cleanup = ingress.observe(process, authorization)
                        if kind == "parent":
                            payload = fixture.request
                        elif kind == "consume":
                            payload = {"command": "consume-result", "occurrence": current_leaf["occurrence"]}
                        else: payload = None
                        process.stdin.write(json.dumps({'kind':kind,'request':payload,'artifact':str(fixture.root / 'leaf.txt')})+'\n'); process.stdin.flush()
                        with command_socket:
                            command = json.loads(command_socket.recv(262144))
                            peer = socket_peer_pid(command_socket)
                            self.assertEqual(peer, process.pid)
                            before = len(f.provider.calls)
                            forged = host._dispatch({**command, "caller_principal": "manager"},
                                ingress=HostIngress("unix-socket", command_socket))
                            self.assertEqual(forged['outcome'], 'error', forged)
                            self.assertFalse(forged['effects_started'])
                            reply = host._dispatch(command, ingress=HostIngress("unix-socket", command_socket))
                            self.assertNotEqual(reply.get('outcome'), 'error', reply)
                            self.assertEqual(len(f.provider.calls), before, "IPC preparation/consumption never launches while parent holds capacity")
                            command_socket.sendall(json.dumps(reply).encode())
                            command_socket.shutdown(socket.SHUT_WR)
                        output = json.loads(process.stdout.readline())
                        self.assertEqual(output['reply'], reply)
                        process.wait(timeout=5); self.assertEqual(process.returncode, 0, process.stderr.read())
                        replies.append(reply)
                        receipts.append({"kind":kind,"pid":process.pid,"kernel_peer_pid":peer,
                            "assignment_ref":authorization['assignment_ref'],"generation":authorization['generation'],
                            "schedule_key":key,"session_id":authorization['physical_session_id'],
                            "brief_sha256":authorization['brief_sha256'],"command_sha256":digest(command),
                            "reply_sha256":digest(reply),"exit_status":process.returncode,
                            "unregistered_peer_rejected":True,
                            "synthetic_borrowed_manager_claim_rejected":forged['effects_started'] is False})
                        if kind == 'parent': current_leaf.update(reply)
                    finally:
                        cleanup(); control.close()
                        if process.poll() is None:
                            process.stdin.close(); process.wait(timeout=5)
                        for stream in (process.stdin,process.stdout,process.stderr):
                            if not stream.closed:stream.close()
                    # Structured host evidence comes from the established fake
                    # provider parser fixture; actual IPC receipts stay separate.
                    original.options = {**options,"recipient_authorizer":lambda request:authorization}
                    return original.execute(native_request)
            return Binding()
        f.app.runtime.adapter.binding_factory = factory
        started = f.app.start(schedule_id=parent['schedule_id'])
        self.assertEqual(started['outcome'], 'succeeded', started)
        self.assertEqual(current_leaf['outcome'], 'prepared', current_leaf)
        self.assertNotEqual(current_leaf['outer_command']['request_id'], current_leaf['start'])
        self.assertNotEqual(current_leaf['start'], current_leaf['schedule_id'])
        self.assertFalse(ingress.live_occurrence(parent['schedule_id']))
        self.assertEqual(server.state['workers'], original_slot)
        child = fixture.owner('start-retained-child', current_leaf['schedule_id'])
        self.assertEqual(child['outcome'], 'succeeded', child)
        self.assertEqual((fixture.root/'leaf.txt').read_text(), 'Useful distinct leaf process artifact.\n')
        parent_return = fixture.owner('parent-child-result', current_leaf['schedule_id'])
        self.assertEqual(parent_return['outcome'], 'succeeded', parent_return)
        self.assertEqual(replies[-1]['parent_delivery']['state'], 'consumed', replies[-1])
        self.assertEqual([r['kind'] for r in receipts], ['parent','leaf','consume'])
        self.assertEqual(len(set(pids)), 3)
        self.assertEqual(receipts[0]['assignment_ref'],receipts[2]['assignment_ref'])
        self.assertNotEqual(receipts[0]['assignment_ref'],receipts[1]['assignment_ref'])
        self.assertEqual(server.state['workers'], original_slot)
        self.assertFalse(any(ingress.live_occurrence(r['schedule_id']) for r in f.port.list_due({'project_ref':f.project.id})))
        self.assertEqual(len(f.app.assignments.list_observations(ResourceRef.from_dict(parent['assignment_ref']),kind='report')),1)
        print(json.dumps({'schema':'otto.d02.local-ipc-proof.v1','capacity_units':1,'receipts':receipts,
            'allowance_units':service.delegation_policy['cumulative_allowance_units'],
            'worker_turn_intents':len(f.port.list_due({'project_ref':f.project.id,'role':'worker'})),
            'handles':{'parent_schedule':parent['schedule_id'],'child_occurrence':current_leaf['occurrence'],
                'outer_command':current_leaf['outer_command'],'start':current_leaf['start'],
                'callback':child['parent_return']['retained_handle'],
                'parent_continuation':parent_return['schedule_id'],
                'result_ref':replies[-1]['result_ref'],
                'consumption_ref':replies[-1]['parent_delivery']['report_ref']},
            'parent_slot_preserved':True,'parent_consumed':True,'provider_evidence':'synthetic native parser fixture; OS custody and useful leaf artifact are authentic'},sort_keys=True))


if __name__ == "__main__": unittest.main()

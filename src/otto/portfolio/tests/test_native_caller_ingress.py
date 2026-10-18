"""Real OS caller authentication with canonical owner/provider fixture records."""
from tests.execution_helpers import start_worker
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from dataclasses import replace

from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.identity_context import HostIngress
from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress, process_identity
from otto.portfolio.tests import test_caller_context as caller_context


@unittest.skipUnless(sys.platform == "darwin", "macOS version-qualified kernel peer audit token required")
class NativeCallerIngressTests(unittest.TestCase):
    def setUp(self):
        self.c = caller_context.CallerContextTests(); self.c.setUp(); self.addCleanup(self.c.doCleanups)
        self.bindings = {role: self.c.caller(role) for role in ("manager", "orchestrator")}
        self.root = Path(self.c.f.temporary.name)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.root / "caller.sock")); self.socket.listen(4); self.socket.settimeout(5)
        self.addCleanup(self.socket.close)
        self.ingress = NativeProcessCallerIngress(lambda auth: self.bindings[auth["principal"]])
        self.host = ExecutionHost(directory=self.root / "commands", handler=lambda value: {"outcome": "unexpected"},
            caller_binding_reader=self.ingress, caller_context_resolver=self.c.f.app.caller_context,
            owner_file_compatibility=True)

    def launch(self, payload, role=None):
        code = ("import socket,sys;sys.stdin.readline();s=socket.socket(socket.AF_UNIX);"
                "s.connect(sys.argv[1]);s.sendall(sys.argv[2].encode()+b'\\n');"
                "print(s.recv(262144).decode(),flush=True);sys.stdin.readline()")
        process = subprocess.Popen([sys.executable, "-c", code, str(self.root / "caller.sock"), json.dumps(payload)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.addCleanup(lambda: process.wait(timeout=5))
        for stream in (process.stdin, process.stdout, process.stderr): self.addCleanup(stream.close)
        cleanup = None
        if role:
            cleanup = self.ingress.observe(process, {"status": "authorized", "principal": role,
                "physical_session_id": self.bindings[role].native_session_id})
            self.addCleanup(cleanup)
        process.stdin.write("go\n"); process.stdin.flush()
        connection, _ = self.socket.accept()
        with connection:
            request = json.loads(connection.recv(262144))
            reply = self.host._dispatch(request, ingress=HostIngress("unix-socket", connection))
            connection.sendall(json.dumps(reply).encode())
        self.assertEqual(json.loads(process.stdout.readline()), reply)
        process.stdin.write("exit\n"); process.stdin.flush(); process.wait(timeout=5)
        return reply, process, cleanup

    def test_same_payload_two_real_peers_and_unregistered_same_uid_spoof(self):
        payload = {"command": "effective-context"}
        first, _, _ = self.launch(payload, "manager")
        second, _, _ = self.launch(payload, "orchestrator")
        self.assertEqual(first["caller_context"]["principal"], "manager", first)
        self.assertEqual(second["caller_context"]["principal"], "orchestrator", second)
        denied, _, _ = self.launch(dict(payload, caller_principal="manager"))
        self.assertEqual(denied["outcome"], "error", denied)
        self.assertFalse(denied["effects_started"])
        spoof, _, _ = self.launch(dict(payload, caller_principal="manager"), "orchestrator")
        self.assertEqual(spoof["outcome"], "error", spoof)

    def test_cleanup_pid_reuse_reparent_and_json_file_cannot_bind(self):
        identity = process_identity(os.getpid())
        root = replace(identity, pid=123, parent=os.getpid(), birth=(1,))
        peer = replace(identity, pid=124, parent=123, birth=(2,))
        owner = replace(identity, parent=1)
        rows = {123: root, 124: peer, os.getpid(): owner}
        process = type("Process", (), {"pid": 123, "poll": lambda self: None})()
        ingress = NativeProcessCallerIngress(lambda auth: self.bindings["manager"], peer_reader=lambda handle: 124,
            process_reader=lambda pid: rows[pid])
        cleanup = ingress.observe(process, {"status": "authorized", "physical_session_id": "native"})
        self.assertEqual(ingress(HostIngress("unix-socket", object())), self.bindings["manager"])
        rows[123] = replace(root, birth=(3,))
        with self.assertRaises(PermissionError): ingress(HostIngress("unix-socket", object()))
        rows[123] = root; rows[124] = replace(peer, parent=os.getpid())
        with self.assertRaises(PermissionError): ingress(HostIngress("unix-socket", object()))
        rows[124] = peer; cleanup()
        with self.assertRaises(PermissionError): ingress(HostIngress("unix-socket", object()))
        with self.assertRaises(PermissionError): ingress(HostIngress("file-ipc", Path("request-aa.json")))
        legacy = self.host._dispatch({"command": "whoami"}, ingress=HostIngress("file-ipc", Path("request-aa.json")))
        self.assertEqual(legacy["outcome"], "held")

    def test_identity_read_uses_existing_native_wait_owner_pump(self):
        # The operation joins the same owner queue as status; it must not wait
        # on the native command lock while that caller waits for its answer.
        self.host._call_bound = lambda request, ingress: {"outcome": "read"}
        result = {}
        with self.host._lock: self.host._external_waiting = 1
        thread = threading.Thread(target=lambda: result.update(self.host._dispatch({"command": "whoami"})))
        thread.start()
        operation, completed, value = self.host._owner_calls.get(timeout=2)
        value["value"] = operation(); completed.set(); thread.join(timeout=2)
        with self.host._lock: self.host._external_waiting = 0
        self.assertFalse(thread.is_alive()); self.assertEqual(result, {"outcome": "read"})

    def test_concurrent_native_preparation_binds_on_owner_before_child_input(self):
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        from otto.agents.claude_adapter import ClaudeWorkerAdapter
        from otto.portfolio.native_caller_ingress import managed_caller_binding

        due = self.c.f.port.read_due(self.bindings["manager"].schedule_id)
        authorization = due["host_evidence"]["gateway_attempt"]["delivery_authorization"]
        server = SimpleNamespace(state={"schedule_id": due["schedule_id"], "workers": {}},
            due_port=self.c.f.port, binding=self.c.f.binding)
        owner_thread = threading.get_ident()
        events = []
        bindings_created = []
        registered_bindings = {}
        event_lock = threading.Lock()

        def factory(retained):
            # This assertion fails on the old worker-thread observer path,
            # regardless of dictionary interleaving or child scheduling.
            self.assertEqual(threading.get_ident(), owner_thread)
            binding = managed_caller_binding(server, retained)
            with event_lock:
                bindings_created.append(binding)
                events.append(("binding", id(binding)))
            return binding

        ingress = NativeProcessCallerIngress(factory)
        host = ExecutionHost(directory=self.root / "prepared-commands", handler=lambda request: request,
            bounded_transports=True)
        host.directory.mkdir()
        barrier = threading.Barrier(2)
        adapter = ClaudeWorkerAdapter(owner="manager", source=str(self.root), worktree=str(self.root),
            launcher_pin=SimpleNamespace(realpath=sys.executable), state_root=str(self.root),
            requested_model="gpt-test", roles=("manager",), transport=object(), manager_transport=object(),
            native_caller_socket=str(self.root / "caller.sock"), native_process_observer=ingress.observe)
        stand_in = ("import json,sys; line=sys.stdin.readline(); "
                    "print(json.dumps({'received':line.strip()}),flush=True)")

        def run_workers(bound):
            def worker(index):
                barrier.wait(timeout=5)
                prepare = getattr(bound, "_native_process_prepare", None)
                callback = (prepare(dict(authorization)) if callable(prepare) else
                    lambda process: bound.native_process_observer(process, dict(authorization)))
                with event_lock: events.append(("transport", index))
                process = subprocess.Popen([sys.executable, "-c", stand_in],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    cleanup = callback(process)
                    try:
                        self.assertTrue(ingress.live_occurrence(due["schedule_id"]))
                        self.assertEqual(ingress._live[process.pid][2], self.bindings["manager"])
                        with event_lock:
                            registered_bindings[index] = id(ingress._live[process.pid][2])
                            events.append(("input", index))
                        output, errors = process.communicate("useful\n", timeout=5)
                        self.assertEqual(process.returncode, 0, errors)
                        self.assertEqual(json.loads(output), {"received": "useful"})
                    finally:
                        cleanup()
                finally:
                    if process.poll() is None: process.kill(); process.wait(timeout=5)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream and not stream.closed: stream.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, index) for index in range(2)]
                for future in futures: future.result(timeout=10)

        def owner_operation():
            bound = adapter.bind_owner_authorization(lambda *args: {}, verifier=lambda *args: {},
                role="manager", profile="workspace-write")
            return ExecutionHost.external_call(lambda: run_workers(bound))

        host._owned(owner_operation)
        self.assertEqual([kind for kind, _ in events].count("binding"), 2)
        self.assertEqual([kind for kind, _ in events].count("input"), 2)
        self.assertEqual(len(set(registered_bindings.values())), 2)
        for index in range(2):
            self.assertLess(events.index(("binding", registered_bindings[index])),
                events.index(("transport", index)))
            self.assertLess(events.index(("transport", index)), events.index(("input", index)))
        self.assertFalse(ingress.live_occurrence(due["schedule_id"]))

    def test_report_continuation_launch_binding_uses_exact_callback_before_locator_refresh(self):
        from types import SimpleNamespace
        from otto.portfolio.native_caller_ingress import managed_caller_binding
        original = self.bindings["manager"]
        assignment = self.c.f.app.assignments.get(original.assignment_ref)
        self.c.f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": self.c.f.project.ref.to_dict(),
             "task_alias": "task", "continue_requested": True, "next_action": "Inspect installed caller context.",
             "logical_request_key": "future-binding-proof", "recorded_at": "2026-10-07T00:00:00+00:00"},
            expected_generation=1, logical_request_key="future-binding-report", actor=self.c.f.actor)
        continued = self.c.f.app.continue_manager(schedule_id=original.schedule_id, report_key="future-binding-proof")
        self.assertEqual(continued["outcome"], "succeeded", continued)
        due = self.c.f.port.read_due(continued["schedule_id"])
        authorization = due["host_evidence"]["gateway_attempt"]["delivery_authorization"]
        server = SimpleNamespace(state={"schedule_id": original.schedule_id, "workers": {}},
            due_port=self.c.f.port, binding=self.c.f.binding)
        binding = managed_caller_binding(server, authorization)
        self.assertEqual(binding.schedule_id, continued["schedule_id"])
        self.assertEqual(self.c.f.app.caller_context(binding)["principal"], "manager")

    def test_worker_result_callback_binding_precedes_locator_refresh_without_inventory(self):
        from types import SimpleNamespace
        from otto.portfolio.native_caller_ingress import managed_caller_binding
        from otto.portfolio.execution_operations import manager_worker_result_schedule_id
        from unittest.mock import patch
        manager = self.bindings["manager"]
        worker = start_worker(self.c.f.app, self.c.f.request())
        self.assertEqual(worker["outcome"], "succeeded", worker)
        continued = self.c.f.app.continue_manager_from_worker(
            manager_schedule_id=manager.schedule_id, worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(continued["outcome"], "succeeded", continued)
        due = self.c.f.port.read_due(continued["schedule_id"])
        authorization = due["host_evidence"]["gateway_attempt"]["delivery_authorization"]
        self.assertEqual(manager_worker_result_schedule_id(authorization["logical_request_key"]), due["schedule_id"])
        server = SimpleNamespace(state={"schedule_id": manager.schedule_id, "workers": {}},
            due_port=self.c.f.port, binding=self.c.f.binding)
        with patch.object(type(self.c.f.port), "list_due", side_effect=AssertionError("global inventory")):
            binding = managed_caller_binding(server, authorization)
            self.assertEqual(binding.schedule_id, due["schedule_id"])
            with self.assertRaisesRegex(PermissionError, "unique exact managed"):
                managed_caller_binding(server, dict(authorization, generation=2))
        self.assertEqual(self.c.f.app.caller_context(binding)["principal"], "manager")

    def test_distinct_callback_pins_current_adapter_without_rewriting_legacy_anchor(self):
        from otto.portfolio.execution_operations import build_manager_callback_due
        prior = self.c.f.app._read(self.bindings["manager"].schedule_id)
        legacy = replace(prior, target={key: value for key, value in prior.target.items() if key != "native_adapter"})
        before = legacy.to_dict()
        callback = build_manager_callback_due(legacy, schedule_id="future-context", request_key="future-context",
            assignment_ref=legacy.assignment_ref, guide_ref=legacy.context_refs[0],
            mandate_ref=legacy.target["mandate_ref"], due_at=legacy.due_at,
            timeout_seconds=legacy.timeout_seconds, native_adapter="current-owner-route")
        self.assertEqual(callback.target["native_adapter"], "current-owner-route")
        self.assertEqual(legacy.to_dict(), before)
        self.assertEqual(callback.target["native_binding"]["schedule_id"], legacy.schedule_id)

    def test_explicit_host_adapter_identity_survives_import_and_script_modules(self):
        original = self.c.f.app.runtime.adapter
        first = type("Pinned", (), {"__module__": "operating_service", "adapter_identity": "owner-pinned-route-v1"})()
        second = type("Pinned", (), {"__module__": "__main__", "adapter_identity": "owner-pinned-route-v1"})()
        for adapter in (first, second):
            self.c.f.app.runtime.adapter = adapter
            self.assertEqual(self.c.f.app.native_adapter_identity(), "owner-pinned-route-v1")
        self.c.f.app.runtime.adapter = original

    def test_scoped_socket_profile_is_host_selected_and_omits_legacy_override(self):
        from herzchen.adapters.host import CodexCliBinding, native_caller_permission_overrides
        from herzchen.contracts import HostRequest, HostIdentity, HostOperation
        from unittest.mock import patch
        path=str(self.root / "exact.sock")
        values=native_caller_permission_overrides(str(self.root), (), path, "otto-native-caller")
        self.assertIn('features.network_proxy=true',values)
        self.assertIn('permissions.otto-native-caller.network.mode="limited"',values)
        self.assertIn('permissions.otto-native-caller.network.domains={}',values)
        self.assertEqual([v for v in values if '.network.unix_sockets=' in v],
            ['permissions.otto-native-caller.network.unix_sockets={'+json.dumps(path)+'="allow"}'])
        for invalid in ('relative.sock','/tmp/../socket','/tmp/'+'x'*104):
            with self.assertRaises(ValueError):native_caller_permission_overrides(str(self.root),(),invalid,"otto-native-caller")
        with self.assertRaises(ValueError):CodexCliBinding(str(self.root),native_caller_socket=path,native_caller_profile="otto-native-caller")
        adapter=CodexCliBinding(str(self.root),native_caller_socket=path,native_caller_profile="otto-native-caller",
            native_process_observer=lambda *a:lambda:None,recipient_authorizer=lambda request:{})
        with patch('herzchen.adapters.host.subprocess.Popen',side_effect=OSError('test boundary')) as popen:
            adapter.execute(HostRequest(HostOperation.RESUME,HostIdentity('fixture','native'),self.c.f.task.ref,'workspace-write'))
            argv=popen.call_args.args[0]
            self.assertNotIn('-s',argv)
            self.assertNotIn('--add-dir',argv)
            self.assertIn('default_permissions="otto-native-caller"',argv)
        denied=CodexCliBinding(str(self.root),native_caller_socket=path,native_caller_profile="otto-native-caller",
            native_process_observer=lambda *a:lambda:None)
        with patch('herzchen.adapters.host.subprocess.Popen') as popen:
            denied.execute(HostRequest(HostOperation.RESUME,HostIdentity('fixture','native'),self.c.f.task.ref,'workspace-write'))
            popen.assert_not_called()
        from otto.agents.herzchen_adapter import HerzchenCodexAdapter
        adapter=HerzchenCodexAdapter(owner='fixture',source=str(self.root),worktree=str(self.root),launcher=sys.executable,
            native_caller_socket=path,native_process_observer=lambda *a:lambda:None)
        bound=adapter.bind_owner_authorization(lambda *a:{})
        self.assertEqual(bound.native_caller_socket,path)

    def test_host_spawn_observer_is_resume_only_and_cleans_exact_process(self):
        from herzchen.adapters.host import CodexCliBinding
        from herzchen.contracts import HostRequest, HostIdentity, HostOperation
        seen = []
        def observer(process, authorization):
            # Python is a local inert stand-in executable, not a native model.
            # This tests the actual Popen boundary, not provider authentication.
            self.assertEqual(process_identity(process.pid).parent, os.getpid())
            seen.append(("spawn", process.pid))
            return lambda: seen.append(("release", process.pid))
        for operation in (HostOperation.INVOKE, HostOperation.RESUME):
            adapter = CodexCliBinding(str(self.root), launcher=sys.executable,
                native_process_observer=observer)
            identity = HostIdentity("fixture", "retained-session" if operation == HostOperation.RESUME else None)
            adapter.execute(HostRequest(operation, identity, self.c.f.task.ref, "read-only"))
        self.assertEqual([kind for kind, _ in seen], ["spawn", "release"])
        self.assertEqual(seen[0][1], seen[1][1])


if __name__ == "__main__": unittest.main()

"""Real OS caller authentication with canonical owner/provider fixture records."""
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
from .test_caller_context import CallerContextTests


@unittest.skipUnless(sys.platform == "darwin", "macOS version-qualified kernel peer audit token required")
class NativeCallerIngressTests(unittest.TestCase):
    def setUp(self):
        self.c = CallerContextTests(); self.c.setUp(); self.addCleanup(self.c.doCleanups)
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

"""Socket result custody fixtures: no live owner, provider or desktop bridge."""
import json
import socket
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from herzchen.contracts import AuthenticatedActor, ResourceRef
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.identity_context import HostCallerBinding, HostIngress
from otto.portfolio.manager_journey_client import read_command_status
from otto.portfolio.owner_completion import OwnerCompletion


class AuthenticatedSocketReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binding = HostCallerBinding(AuthenticatedActor("fixture", "manager", "private-credential"),
            ResourceRef("fixture", "wrk.assignment", "assignment", "rev-1"),
            1, "fixture-adapter", "native", "schedule")
        self.project = {"authority": "fixture", "kind": "wrk.project", "id": "project", "revision": "rev-1"}
        self.calls = []
        self.context = {"principal": "manager", "generation": 1,
            "assignment_ref": self.binding.assignment_ref.to_dict(),
            "project_ref": self.project, "native_session": {"id": "native"}}
        self.report = {"authority": "fixture", "kind": "wrk.report", "id": "outcome", "revision": "rev-1"}
        self.host = self.make_host()

    def make_host(self, handler=None):
        return ExecutionHost(directory=self.root,
            handler=handler or (lambda req: self.calls.append(req) or {
                "outcome": "recorded", "issue_id": "issue", "state": "resolved",
                "report_ref": self.report, "applied_response_ref": self.report}),
            caller_binding_reader=lambda ingress: self.binding,
            caller_context_resolver=lambda binding: self.context,
            caller_authorizer=lambda context, request: True)

    def request(self, token="a" * 32, **extra):
        return {"command": "resolve-help", "request_key": "original", "transport_request_id": token, **extra}

    def dispatch(self, host=None, **extra):
        return (host or self.host)._dispatch(self.request(**extra), ingress=HostIngress("unix-socket", object()))

    def scope(self):
        return {"principal": "manager", "generation": 1,
            "assignment_identity": {k: self.binding.assignment_ref.to_dict()[k] for k in ("authority", "kind", "id")},
            "project_identity": {k: self.project[k] for k in ("authority", "kind", "id")}}

    def test_exact_result_recovery_and_changed_input_or_foreign_caller_denied(self):
        result = self.dispatch()
        self.assertTrue(result["outer_command"]["retained"])
        status = read_command_status(self.root, "a" * 32, expected_socket_scope=self.scope())
        self.assertTrue(status["terminal"])
        for key in ("issue_id", "state", "report_ref", "applied_response_ref"):
            self.assertEqual(status["summary"][key], result[key])
        replay = self.dispatch(host=self.make_host())
        self.assertTrue(replay["outer_command"]["recovered"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.dispatch(request_key="changed")["outcome"], "error")
        self.binding = replace(self.binding, actor=AuthenticatedActor("fixture", "foreign", "credential"))
        self.assertEqual(self.dispatch()["outcome"], "error")
        with self.assertRaises(PermissionError):
            read_command_status(self.root, "a" * 32, expected_socket_scope={**self.scope(), "principal": "foreign"})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list(self.root.glob("request-*.json")), [])
        self.assertNotIn("private-credential", (self.root / ("socket-intent-" + "a" * 32 + ".json")).read_text())

    def test_actual_disconnected_client_late_commit_is_retained_before_send(self):
        admitted, release = threading.Event(), threading.Event()
        def effect(request):
            self.calls.append(request)
            admitted.set()
            self.assertTrue(release.wait(2))
            self.host._commands_stop.set()
            return {"outcome": "recorded", "issue_id": "late", "state": "resolved", "report_ref": self.report}
        self.host = self.make_host(effect)
        client, server = socket.socketpair()
        self.host._socket = SimpleNamespace(accept=lambda: (server, None))
        thread = threading.Thread(target=self.host._serve_socket)
        thread.start()
        client.settimeout(.01)
        client.sendall(json.dumps(self.request()).encode() + b"\n")
        self.assertTrue(admitted.wait(2))
        with self.assertRaises(socket.timeout):
            client.recv(1)
        pending = read_command_status(self.root, "a" * 32)
        self.assertFalse(pending["terminal"])
        self.assertNotIn("provider_called", pending)
        client.close()
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        status = read_command_status(self.root, "a" * 32)
        self.assertEqual(status["summary"]["issue_id"], "late")
        self.assertEqual(len(self.calls), 1)
        self.dispatch(host=self.make_host())
        self.assertEqual(len(self.calls), 1)

    def test_restart_pending_is_unknown_without_reexecution(self):
        completion = OwnerCompletion()
        self.host = self.make_host(lambda request: self.calls.append(request) or completion)
        result = self.dispatch()
        self.assertIsInstance(result, OwnerCompletion)
        restarted = self.dispatch(host=self.make_host())
        self.assertFalse(restarted["terminal"])
        self.assertFalse(restarted["retry"])
        self.assertNotIn("provider_called", restarted)
        self.assertEqual(len(self.calls), 1)
        completion.resolve({"outcome": "recorded", "issue_id": "original"})
        self.assertTrue(read_command_status(self.root, "a" * 32)["terminal"])

    def test_async_error_retained_without_no_effect_claim(self):
        completion = OwnerCompletion()
        self.host = self.make_host(lambda request: completion)
        self.dispatch()
        completion.resolve(error=RuntimeError("after effect"))
        status = read_command_status(self.root, "a" * 32)
        self.assertEqual(status["outcome"], "unknown")
        self.assertNotIn("provider_called", status["summary"])

    def test_authentication_rejection_and_file_collision_never_claim_retention(self):
        self.host.caller_authorizer = lambda context, request: False
        denied = self.dispatch()
        self.assertFalse(denied["outer_command"]["retained"])
        self.assertEqual(list(self.root.iterdir()), [])
        self.host.caller_authorizer = lambda context, request: True
        (self.root / ("request-" + "a" * 32 + ".json")).write_text("{}")
        self.assertEqual(self.dispatch()["outcome"], "error")
        self.assertEqual(self.calls, [])
        for token in ("bad", "../" + "a" * 32):
            self.assertEqual(self.dispatch(token=token)["outcome"], "error")

    def test_context_projection_is_not_a_command_admission_or_denial(self):
        from otto.portfolio.tests.test_caller_context import CallerContextTests
        fixture = CallerContextTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        binding = fixture.caller()
        context = fixture.f.app.caller_context(binding)
        self.assertTrue(context["read_only"])
        self.assertEqual(context["manager_worker_route"]["prepare_command"], "run-worker")
        self.assertIn("grants none", context["manager_worker_route"]["authorization"])
        self.assertEqual(len(fixture.f.provider.calls), 1)


if __name__ == "__main__":
    unittest.main()

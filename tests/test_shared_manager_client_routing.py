import unittest
from types import SimpleNamespace
from unittest.mock import patch
from otto.hostctl.manager_client import run_launched
from otto.hostctl.serve import HostOwnerService
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from otto.portfolio.manager_journey_client import requires_native_caller
from otto.portfolio.manager_journey_service import ManagerJourneyService

class SharedManagerClientRouting(unittest.TestCase):
    def test_ordinary_mutations_require_current_native_binding(self):
        for command in ('report','review-task','finish-task','finish-project','commit','manager-continue','resolve-help'):
            self.assertTrue(requires_native_caller(command), command)

    def test_owner_grants_cannot_inherit_native_identity(self):
        for command in ('start-manager','respond-help','owner-execution','owner-context','document-authoring','project-authoring','command-status'):
            self.assertFalse(requires_native_caller(command), command)

    def test_launched_status_uses_socket_and_owner_commands_stay_local(self):
        with patch('otto.portfolio.caller_client.call', return_value={'outcome': 'pending'}) as call:
            result = run_launched(['command-status', '--request-id', 'a' * 32],
                                  {'OTTO_CALLER_SOCKET': '/tmp/caller.sock'})
        self.assertEqual(result['outcome'], 'pending')
        call.assert_called_once_with('/tmp/caller.sock',
            {'command': 'command-status', 'request_id': 'a' * 32})
        with self.assertRaises(PermissionError):
            run_launched(['start-manager', '--schedule-id', 'foreign'],
                         {'OTTO_CALLER_SOCKET': '/tmp/caller.sock', 'OTTO_MANAGER_IPC': '/tmp/manager-ipc'})
        with self.assertRaises(PermissionError):
            run_launched(['manager-continue', '--report-key', 'foreign', '--operation', 'dispatch'],
                         {'OTTO_CALLER_SOCKET': '/tmp/caller.sock'})
        with self.assertRaises(PermissionError):
            run_launched(['command-status', '--request-id', 'a' * 32],
                         {'OTTO_MANAGER_IPC': '/tmp/manager-ipc'})

    def test_manager_launch_grants_no_shared_file_write_root(self):
        service = SimpleNamespace(paths={'ipc': '/tmp/owner-ipc', 'socket': '/tmp/caller.sock'}, run_id='A')
        launch = HostOwnerService.manager_launch(service)
        self.assertEqual(launch['write_roots'], ())
        self.assertEqual(launch['env']['OTTO_CALLER_SOCKET'], '/tmp/caller.sock')
        self.assertNotIn('OTTO_MANAGER_IPC', launch['env'])

    def test_setup_read_preview_are_native_and_mutations_stay_owner_only(self):
        self.assertTrue(requires_native_caller('operating-setup'))
        service = object.__new__(ManagerJourneyService)
        state = {'manager': 'm', 'assignment_ref': {'id': 'a'}, 'manager_generation': 1}
        service.server = SimpleNamespace(state=state)
        service.host = SimpleNamespace(bounded_transports=True)
        calls = []
        service.commands = SimpleNamespace(_authorize=lambda: calls.append('current-authority'))
        context = {'role': 'manager', 'principal': 'm', 'assignment_ref': {'id': 'a'}, 'generation': 1}
        for operation in ('read', 'preview'):
            service.authorize_caller(context, {'command': 'operating-setup', 'operation': operation})
        self.assertEqual(calls, ['current-authority', 'current-authority'])
        for operation in ('prepare', 'apply', 'update', 'activate', 'unknown'):
            with self.assertRaises(PermissionError):
                service.authorize_caller(context, {'command': 'operating-setup', 'operation': operation})
        with self.assertRaises(PermissionError):
            service.authorize_caller({**context, 'principal': 'foreign'}, {'command': 'operating-setup', 'operation': 'read'})

    def test_parser_launched_client_and_authenticated_service_forward_only_route_fields(self):
        import argparse
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command", required=True)
        add_manager_journey_parsers(commands)
        retry_args = vars(parser.parse_args(["route", "--operation", "retry", "--schedule-id", "due-1"]))
        self.assertEqual(retry_args, {"command": "route", "operation": "retry", "schedule_id": "due-1"})
        read_args = vars(parser.parse_args(["execution-control", "--operation", "read", "--schedule-id", "due-1"]))
        self.assertEqual(read_args, {"command": "execution-control", "operation": "read", "schedule_id": "due-1"})

        state = {"manager": "manager", "project_ref": {"id": "project"},
                 "assignment_ref": {"id": "assignment"}, "manager_generation": 3}
        service = object.__new__(ManagerJourneyService)
        service.server = SimpleNamespace(state=state)
        service.commands = SimpleNamespace(_authorize=lambda: None, _key=lambda request: request["request_key"])
        context = {"role": "manager", "principal": "manager", "project_ref": state["project_ref"],
                   "assignment_ref": state["assignment_ref"], "generation": 3}
        worker_calls, control_calls = [], []
        service._submit_worker = lambda request: worker_calls.append(request) or {"outcome": "admitted"}
        service._execution_control = lambda request: control_calls.append(request) or {"outcome": "read"}

        def launched(argv):
            with patch("otto.portfolio.caller_client.call",
                       side_effect=lambda _socket, request: service.dispatch_bound(context, request)):
                return run_launched(argv, {"OTTO_MANAGER_IPC": "/tmp/manager-ipc",
                                           "OTTO_CALLER_SOCKET": "/tmp/caller.sock"})

        result = launched(["route", "--operation", "reroute", "--task", "J1", "--principal", "worker",
                           "--route", "normal", "--focus", "Inspect this task"])
        self.assertEqual(result["outcome"], "admitted")
        self.assertEqual(set(worker_calls[-1]), {"command", "request_key", "task", "principal", "route", "focus"})
        self.assertEqual(worker_calls[-1]["task"], "J1")
        result = launched(["route", "--operation", "retry", "--schedule-id", "due-1"])
        self.assertEqual(result["outcome"], "read")
        self.assertEqual(control_calls[-1], {"command": "execution-control", "operation": "resume",
                                             "schedule_id": "due-1"})

        for args in (["route", "--operation", "reroute"], ["route", "--operation", "retry"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                launched(args)
        for extra in ({"irrelevant": None}, {"project_ref": {"id": "foreign"}}):
            request = {"command": "route", "operation": "retry", "request_key": "route-key",
                       "schedule_id": "due-1", **extra}
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                service.dispatch_bound(context, request)

    def test_execution_control_client_keeps_absence_distinct_and_preserves_refusals(self):
        state = {"manager": "manager", "project_ref": {"id": "project"},
                 "assignment_ref": {"id": "assignment"}, "manager_generation": 3,
                 "schedule_id": "due-1", "workers": {}}
        service = object.__new__(ManagerJourneyService)
        raw_due = {"schedule_id": "due-1", "project_ref": state["project_ref"],
                   "recipient": "manager", "requested_model": "test", "requested_reasoning": "high",
                   "role": "worker", "target": {}, "host_evidence": {}}
        app = SimpleNamespace(_read=lambda _schedule: SimpleNamespace(role="worker", host_evidence={}))
        service.server = SimpleNamespace(state=state,
            due_port=SimpleNamespace(read_due=lambda _schedule: raw_due))
        service.commands = SimpleNamespace(_authorize=lambda: None, _key=lambda request: request["request_key"])
        service._execution = lambda **_options: app
        service.host = SimpleNamespace(recover_capacity_failed_worker=lambda *_args, **_kwargs: None,
            recover_gone_worker=lambda *_args, **_kwargs: {"outcome": "succeeded"})
        service._startup_recovery = lambda _app, _known, *, execute: {
            "admission": "ready", "occurrences": [{"result": {"outcome": "succeeded"}}]}
        context = {"role": "manager", "principal": "manager", "project_ref": state["project_ref"],
                   "assignment_ref": state["assignment_ref"], "generation": 3}
        received = []
        execution_control = service._execution_control
        service._execution_control = lambda request: (received.append(dict(request)), execution_control(request))[1]

        def launched(argv):
            with patch("otto.portfolio.caller_client.call",
                       side_effect=lambda _socket, request: service.dispatch_bound(context, request)):
                return run_launched(argv, {"OTTO_MANAGER_IPC": "/tmp/manager-ipc",
                                           "OTTO_CALLER_SOCKET": "/tmp/caller.sock"})

        for operation in ("read", "recover"):
            argv = ["execution-control", "--operation", operation, "--schedule-id", "due-1"]
            if operation == "recover":
                argv += ["--request-key", "recover-1", "--expected-due-sha256", "a" * 64,
                         "--expected-unknown-result-sha256", "b" * 64, "--reason", "Inspect retained failure"]
            self.assertIn(launched(argv)["outcome"], {"read", "succeeded"})
            self.assertEqual(received[-1]["operation"], operation)
            expected = {"command", "operation", "schedule_id"}
            if operation == "recover":
                expected |= {"request_key", "expected_due_sha256", "expected_unknown_result_sha256", "reason"}
            self.assertEqual(set(received[-1]), expected)

        # Canon keeps a direct native resume owner-only. The manager's retry
        # command remains the authenticated route into that exact resume.
        self.assertEqual(launched(["route", "--operation", "retry", "--schedule-id", "due-1"])["outcome"],
                         "succeeded")
        self.assertEqual(received[-1], {"command": "execution-control", "operation": "resume",
                                        "schedule_id": "due-1"})

        control = ManagerJourneyService._execution_control

        # A supplied null still denotes a malformed recovery request; it is
        # not collapsed into the ordinary exact-schedule read/resume form.
        with self.assertRaises(ValueError):
            control(service, {"command": "execution-control", "operation": "read",
                              "schedule_id": "due-1", "reason": None})
        with self.assertRaises(ValueError):
            control(service, {"command": "execution-control", "operation": "recover",
                              "schedule_id": "due-1", "request_key": None})
        with self.assertRaises(ValueError):
            control(service, {"command": "execution-control", "operation": "read",
                              "schedule_id": "due-1", "project_ref": {"id": "foreign"}})

if __name__ == '__main__': unittest.main()

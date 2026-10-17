import unittest
from types import SimpleNamespace
from unittest.mock import patch
from otto.hostctl.manager_client import run_launched
from otto.hostctl.serve import HostOwnerService
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

if __name__ == '__main__': unittest.main()

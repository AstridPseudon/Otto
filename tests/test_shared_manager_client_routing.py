import unittest
from types import SimpleNamespace
from otto.portfolio.manager_journey_client import requires_native_caller
from otto.portfolio.manager_journey_service import ManagerJourneyService

class SharedManagerClientRouting(unittest.TestCase):
    def test_ordinary_mutations_require_current_native_binding(self):
        for command in ('report','review-task','finish-task','finish-project','commit','manager-continue','resolve-help'):
            self.assertTrue(requires_native_caller(command), command)

    def test_owner_grants_cannot_inherit_native_identity(self):
        for command in ('start-manager','respond-help','owner-execution','owner-context','document-authoring','project-authoring','command-status'):
            self.assertFalse(requires_native_caller(command), command)

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

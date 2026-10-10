import unittest
from otto.portfolio.manager_journey_client import requires_native_caller

class SharedManagerClientRouting(unittest.TestCase):
    def test_ordinary_mutations_require_current_native_binding(self):
        for command in ('report','review-task','finish-task','finish-project','commit','manager-continue','resolve-help'):
            self.assertTrue(requires_native_caller(command), command)

    def test_owner_grants_cannot_inherit_native_identity(self):
        for command in ('start-manager','respond-help','owner-execution','owner-context','document-authoring','project-authoring','command-status'):
            self.assertFalse(requires_native_caller(command), command)

if __name__ == '__main__': unittest.main()

import unittest

from herzchen.command_ports import decode_wire
from herzchen.contracts import AuthenticatedActor, ContractError


class AuthenticatedActorDecodeTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "authority": "test-authority",
            "actor": "test-actor",
            "credential_ref": "credential-1",
        }

    def test_from_dict_requires_literal_true_authentication(self):
        for value in (None, "false", 1):
            with self.subTest(authenticated=value):
                record = dict(self.base)
                if value is not None:
                    record["authenticated"] = value
                with self.assertRaises(ContractError):
                    AuthenticatedActor.from_dict(record)

        actor = AuthenticatedActor.from_dict(
            {**self.base, "authenticated": True})
        self.assertIs(actor.authenticated, True)

    def test_tagged_wire_decode_rejects_non_boolean_authentication(self):
        wire = {
            "$herzchen": "dataclass",
            "type": "herzchen.contracts.model:AuthenticatedActor",
            "fields": {
                "authority": "test-authority",
                "actor": "test-actor",
                "credential_ref": "credential-1",
                "authenticated": 1,
            },
        }
        with self.assertRaises(ContractError):
            decode_wire(wire)


if __name__ == "__main__":
    unittest.main()

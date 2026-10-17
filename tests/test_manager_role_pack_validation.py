"""Manager role-pack fields needed by effective-context must fail closed."""
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from otto.portfolio.role_context import RoleContextError, _role_pack


class ManagerRolePackValidationTests(unittest.TestCase):
    def _pack(self, *, omit_actions=False, omit_help=False):
        guidance = {"runbook": "Use the runbook."}
        if not omit_help:
            guidance["help"] = "Ask for help when blocked."
        manager = {
            "responsibility": "Coordinate project work.",
            "guidance": guidance,
            "tool_entrypoint": "otto manager",
        }
        if not omit_actions:
            manager["manager_actions"] = []
        content = {
            "schema": "otto.role-pack.v1",
            "adapter_role_guidance": "Follow the selected adapter.",
            "roles": {"manager": manager},
            "base_manager_brief": {
                "schema": "otto.base-manager-brief.v1",
                "mandate": "Coordinate safely.",
                "constraints": ["Use adopted instructions."],
            },
        }
        resource = SimpleNamespace(path="roles.json", kind="role_guidance",
                                   content=json.dumps(content).encode(), source_digest="digest")
        pack = SimpleNamespace(
            pack_id="otto-roles", version="1.0.0",
            source=SimpleNamespace(source_revision="revision", source_inventory_identity="inventory"),
            resources=(resource,),
        )
        pin = {"pack_id": pack.pack_id, "pack_version": pack.version,
               "source_revision": pack.source.source_revision,
               "source_inventory_identity": pack.source.source_inventory_identity,
               "resource_path": resource.path, "resource_digest": resource.source_digest}
        return pack, {"content": {"role_pack": pin}}

    def test_manager_requires_explicit_actions_even_when_empty_is_valid(self):
        pack, configuration = self._pack(omit_actions=True)
        with mock.patch("herzchen.packs.authoring.read_managed_pack", return_value=pack):
            with self.assertRaises(RoleContextError) as refused:
                _role_pack(configuration, "manager")
        self.assertTrue(refused.exception.next_action)

    def test_manager_requires_nonblank_help_guidance(self):
        pack, configuration = self._pack(omit_help=True)
        with mock.patch("herzchen.packs.authoring.read_managed_pack", return_value=pack):
            with self.assertRaises(RoleContextError) as refused:
                _role_pack(configuration, "manager")
        self.assertTrue(refused.exception.next_action)


if __name__ == "__main__":
    unittest.main()

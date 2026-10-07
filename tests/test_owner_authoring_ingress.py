"""Trusted owner input joined to real finite authoring; no provider substitute needed."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from otto.portfolio.fixtures import project_authoring
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress


class OwnerAuthoringIngressTests(unittest.TestCase):
    def setUp(self):
        self.f = project_authoring.ProjectAuthoringProof()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.directory = self.f.root / 'owner-ipc'
        self.ingress = OwnerAuthoringIngress(actor=self.f.owner.owner_actor,
            owner_actor=self.f.owner.owner_actor, directory=self.directory)
        server = SimpleNamespace(owner=self.f.owner, portfolio=self.f.portfolio, state={},
                                 due_port=None, _execution=lambda **kw: None)
        self.service = ManagerJourneyService(server=server, host=None, run_path=self.f.root,
            workspace=self.f.root, authoring_authorizer=self.ingress.authorize)
        self.request = {'command': 'project-authoring', 'operation': 'create',
                        'request_key': 'owner-created', 'edit': {'title': 'Bounded sibling'}}

    def test_independent_grant_required_then_real_authoring_and_exact_replay(self):
        with self.assertRaises(PermissionError):
            self.service(self.request)
        receipt = self.ingress.publish({'schema': self.ingress.schema, 'request': self.request})
        retained = json.loads(Path(receipt['request_path']).read_text())
        created = self.service(retained)
        self.assertEqual(created['outcome'], 'created', created)
        self.assertFalse(created['executable'])
        self.assertEqual(self.service(retained)['project_ref'], created['project_ref'])
        self.assertRegex(receipt['request_id'], '^[0-9a-f]{64}$')
        changed = {**self.request, 'request_key': 'different'}
        with self.assertRaises(PermissionError):
            self.service(changed)
        # A restart cannot infer owner authority from an old request file.
        restarted = OwnerAuthoringIngress(actor=self.f.owner.owner_actor,
            owner_actor=self.f.owner.owner_actor, directory=self.directory)
        with self.assertRaises(PermissionError):
            restarted.authorize(retained)

    def test_exact_current_actor_scope_is_read_without_releasing_or_leaking_tokens(self):
        ref=self.f.create()
        opened=self.f.open(ref)
        request={"command":"project-authoring","operation":"current-scope"}
        receipt=self.ingress.publish({"schema":self.ingress.schema,"request":request})
        observed=self.service(json.loads(Path(receipt["request_path"]).read_text()))
        self.assertEqual(observed["state"],"occupied",observed)
        self.assertEqual(observed["session_id"],opened["session_id"])
        self.assertEqual(observed["target_ref"]["id"],ref["id"])
        self.assertNotIn("token",observed)
        self.assertNotIn("fence",observed)
        self.assertEqual(self.f.owner.authoring.read_current_actor(
            self.f.owner.binding.authenticated_actor("foreign"))["state"],"available")
        self.assertEqual(self.service(request),observed)
        self.assertEqual(self.f.finish(opened)["outcome"],"finished")
        self.assertEqual(self.service(request)["state"],"available")

    def test_actor_operation_override_and_foreign_grant_rejected(self):
        for patch in ({'actor': 'owner'}, {'command': 'execution-control'}, {'command': 'manager-replace'}):
            with self.subTest(patch=patch), self.assertRaises(PermissionError):
                self.ingress.publish({'schema': self.ingress.schema, 'request': {**self.request, **patch}})
        with self.assertRaises(PermissionError):
            self.ingress.publish({'schema': self.ingress.schema, 'request': self.request, 'actor': 'owner'})
        self.assertFalse(self.directory.exists())


if __name__ == '__main__':
    unittest.main()

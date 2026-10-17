"""A pending project may hold inert tasks; they never dispatch.

Real owner Store: a draft accepts pending-lifecycle tasks through the typed
ProjectSheet route, refuses any task that could run, and the direction sync
path authors no task.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import tempfile
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.kernel.store import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio, PortfolioError
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.orchestrator_client import OrchestratorAdmissions, ScopedOrchestratorClient
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.tests import test_portfolio_direction as direction_fixture


def _task(alias, **extra):
    return {"alias": alias, "title": "Plan " + alias, "instructions": "Do " + alias,
            "acceptance": "Done " + alias, "lifecycle": "pending", **extra}


class PendingInertTaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="a1-inert-tasks-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.sqlite"
        domains = tuple((*contributions(include_assignment_resources=True),
                         authoring_contribution(), content_contribution()))
        self.store = Store.create(self.path, authority="a1-inert-tasks-test")
        self.store.register_domain_handler(domains)
        self.addCleanup(self.store.close)
        binding = HerzchenBindingConfig("a1-inert-tasks-test", "fixture-credential")
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner",
                                             operator_actor="fixture-operator")
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())
        created = self.portfolio.create_draft(actor="owner", request_id="inert-create",
                                              title="A plan", brief="The plan brief")
        self.assertEqual(created["outcome"], "created", created)
        self.project_ref = created["project_ref"]

    def _record(self):
        return self.owner.graph.current(ResourceRef.from_dict(self.project_ref))

    def test_draft_edit_accepts_pending_task_without_activation_or_dispatch(self):
        edited = self.portfolio.edit_pending(self.project_ref, {"tasks": [_task("P01")]},
                                             actor="owner", request_id="inert-edit")
        self.assertIn(edited["outcome"], {"edited", "authored"}, edited)
        self.assertFalse(edited.get("dispatch", False))
        self.assertFalse(edited.get("launch", False))
        record = self._record()
        self.assertEqual(record.lifecycle.value, "pending")
        self.assertEqual(len(record.payload["tasks"]), 1)
        task = self.owner.graph.current(ResourceRef.from_dict(record.payload["tasks"][0]))
        self.assertEqual(task.lifecycle.value, "pending")

    def test_draft_edit_refuses_task_that_could_run_before_any_write(self):
        counts = self.store.consumer().snapshot_counts()
        for index, extra in enumerate(({"lifecycle": "active"}, {"lifecycle": "completed"}, {"withdraw": True})):
            with self.assertRaisesRegex(PortfolioError, "inert"):
                self.portfolio.edit_pending(self.project_ref, {"tasks": [_task("P02", **extra)]},
                                            actor="owner", request_id="refused-%d" % index)
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_typed_task_route_refuses_runnable_task_on_pending_project(self):
        counts = self.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(PortfolioError, "inert"):
            self.portfolio.author_task_list(self.project_ref, [_task("P03", lifecycle="active")],
                                            actor="owner", request_id="typed-active")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_typed_task_route_keeps_pending_task_inert(self):
        result = self.portfolio.author_task_list(self.project_ref, [_task("P04")],
                                                 actor="owner", request_id="typed-pending")
        self.assertEqual(result["outcome"], "authored", result)
        self.assertFalse(result["dispatch"])
        self.assertFalse(result["launch"])
        record = self._record()
        self.assertEqual(record.lifecycle.value, "pending")
        task = self.owner.graph.current(ResourceRef.from_dict(record.payload["tasks"][0]))
        self.assertEqual(task.lifecycle.value, "pending")


class DirectionSyncFenceTests(unittest.TestCase):
    """Same-root direction sync authors no task and launches nothing."""

    def setUp(self):
        self.fixture = direction_fixture.PortfolioDirectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        original = ResponsibilityAssignments.assign

        def assign(assignment_port, *args, **kw):
            if kw.get("role") == "orchestrator":
                kw.setdefault("session", {"host": "codex", "native_id": "own-root-chat"})
            return original(assignment_port, *args, **kw)

        with patch.object(ResponsibilityAssignments, "assign", assign):
            self.root, self.subject, self.oldpin, self.project = self.fixture.setup_portfolio()
        self.owner = PortfolioOwnerBootstrap(self.fixture.store, binding=self.fixture.binding, owner_actor="owner",
                                             portfolio_ref=self.root.scope, main_assignment_ref=self.root.ref,
                                             expected_main_principal="owner")
        state = {"orchestrator_assignment_ref": self.root.ref.to_dict(),
                 "root_help_binding": {"assignment_ref": self.root.ref.to_dict(), "generation": 1}}
        server = SimpleNamespace(owner=self.owner, state=state, _execution=None, portfolio=None,
                                 due_port=None, _save_state=lambda: None)
        service = ManagerJourneyService(server=server, host=None, run_path=self.fixture.path.parent,
                                        workspace=self.fixture.path.parent)
        binding = OrchestratorAdmissions(self.owner, main_assignment_ref=self.root.ref.to_dict(), generation=1).admit_current_root(
            actor=self.owner.owner_actor, conversation_ref=self.root.session,
            operations=["whoami", "direction-read", "direction-draft", "direction-update"], request_key="own-policy")
        self.client = ScopedOrchestratorClient(owner=self.owner, binding=binding,
                                               handlers={op: service.root_direction_client for op in binding["operations"]})

    def _direction(self):
        return self.client.call({"operation": "direction-read", "request_key": "read"})["assignment_direction"]

    @staticmethod
    def _content(instructions="Pending plan"):
        return {"schema": "herzchen.instructions.v1", "name": "DIRECTION", "entrypoint": "ORCHESTRATOR.md",
                "instructions": instructions, "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest(),
                "export_manifest_digest": "fixture", "required": True, "supporting_refs": []}

    @staticmethod
    def _task():
        return {"alias": "INJ01", "title": "Injected", "instructions": "Do it", "acceptance": "Done", "lifecycle": "pending"}

    def test_direction_update_refuses_task_bearing_content_before_effect(self):
        direction = self._direction()
        counts = self.fixture.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(ValueError, "task"):
            self.client.call({"operation": "direction-update", "request_key": "inject-update",
                              "request": {"content": {**self._content(), "tasks": [self._task()]},
                                          "expected_direction_ref": direction["latest_ref"],
                                          "expected_binding_ref": direction["binding_ref"]}})
        self.assertEqual(self.fixture.store.consumer().snapshot_counts(), counts)

    def test_direction_draft_refuses_task_bearing_content_before_effect(self):
        direction = self._direction()
        counts = self.fixture.store.consumer().snapshot_counts()
        with self.assertRaisesRegex(ValueError, "task"):
            self.client.call({"operation": "direction-draft", "request_key": "inject-draft",
                              "request": {"content": {**self._content(), "tasks": [self._task()]},
                                          "expected_revision": direction["latest_ref"]["revision"]}})
        self.assertEqual(self.fixture.store.consumer().snapshot_counts(), counts)

    def test_direction_update_launches_nothing_and_authors_no_task(self):
        direction = self._direction()
        result = self.client.call({"operation": "direction-update", "request_key": "plan-only",
                                   "request": {"content": self._content(), "expected_direction_ref": direction["latest_ref"],
                                               "expected_binding_ref": direction["binding_ref"]}})
        self.assertEqual(result["outcome"], "synchronized")
        self.assertFalse(result["dispatch"])
        self.assertFalse(result["launch"])
        self.assertFalse(result["tasks_created"])
        self.assertEqual(self.owner.graph.current(self.project.ref).payload["tasks"], [])


if __name__ == "__main__":
    unittest.main()

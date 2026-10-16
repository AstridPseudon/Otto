"""A portfolio may explicitly transfer a project to another own root."""
import tempfile
import unittest
from pathlib import Path

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.domains.work.model import WorkValidationError
from herzchen.kernel import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class ScopedRootSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler((*contributions(), domain_contribution(),
                                            authoring_contribution(), packet_contribution()))
        self.binding = HerzchenBindingConfig("owner", "owner-credential")
        self.portfolio = ResourceRef("owner", "wrk.portfolio", "portfolio")
        seed = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner")
        self.default_root = seed.assignments.assign(
            self.portfolio, role="orchestrator", principal="owner-root",
            session="owner-session", logical_request_key="owner-root")
        self.owner = PortfolioOwnerBootstrap(
            self.store, binding=self.binding, owner_actor="owner",
            portfolio_ref=self.portfolio, main_assignment_ref=self.default_root.ref)
        self.project = self.owner.graph.create_project(
            title="Port project", outcome="Preserve Port mandate",
            metadata={"keep": "intact"}, logical_request_key="port-project")
        self.manager = self.owner.assignments.assign(
            self.project.ref, role="manager", principal="port-manager",
            session="port-session", logical_request_key="port-manager")
        self.owner.consumer_operations().execute(
            "work.orchestrator.projects.attach",
            {"target_assignment_ref": self.default_root.ref.to_dict(),
             "target_assignment_revision": self.default_root.revision,
             "target_assignment_generation": self.default_root.generation,
             "projects": [{"project_ref": self.project.ref.to_dict(),
                           "project_version": self.project.version,
                           "assignment_ref": self.manager.ref.to_dict(),
                           "assignment_revision": self.manager.revision,
                           "assignment_generation": self.manager.generation}]},
            request_id="enroll-port", actor="owner")
        self.astrid_root = self.owner.assignments.assign(
            self.portfolio, role="orchestrator", principal="astrid-root",
            session="astrid-session", logical_request_key="astrid-root")

    def _transfer(self, project, relation, *, target=None, **overrides):
        target = target or self.astrid_root
        values = {
            "actor": self.owner.owner_actor,
            "request_id": "transfer-port-to-astrid",
            "portfolio_ref": self.portfolio.to_dict(),
            "project_ref": project.ref.to_dict(),
            "expected_project_revision": project.ref.revision,
            "expected_project_version": project.version,
            "current_assignment_ref": relation["assignment_ref"],
            "current_assignment_revision": relation["assignment_revision"],
            "current_assignment_generation": relation["generation"],
            "target_assignment_ref": target.ref.to_dict(),
            "target_assignment_revision": target.revision,
            "target_assignment_generation": target.generation,
            "overlap_acknowledged": True,
        }
        values.update(overrides)
        return self.owner.orchestration_port.transfer_supervision(**values)

    def _default_identity(self, relation):
        # Identity-only lookup returns the exact current pointer, including its
        # immutable revision/version and payload. The pointer id is derived
        # from the portfolio, so take it from the canonical supervision join.
        pinned = ResourceRef.from_dict(relation["default_ref"])
        ref = ResourceRef(pinned.authority, pinned.kind, pinned.id)
        return self.store.consumer().get_identity(ref)

    def test_second_own_root_transfers_one_project_without_changing_default(self):
        before_project = self.owner.graph.current(self.project.ref)
        before_relation = before_project.payload["metadata"]["otto_orchestrator"]
        before_default = self._default_identity(before_relation)
        self.assertIsNotNone(before_default)
        self.assertEqual(before_default.ref, ResourceRef.from_dict(before_relation["default_ref"]))
        self.assertEqual(before_default.payload["assignment_ref"],
                         ResourceRef("owner", "wrk.assignment", self.default_root.ref.id).to_dict())
        self.assertEqual(before_relation["assignment_ref"], self.default_root.ref.to_dict())

        transferred = self._transfer(before_project, before_relation)

        self.assertEqual(transferred["outcome"], "transferred")
        after_project = self.owner.graph.current(ResourceRef.from_dict(transferred["project_ref"]))
        after_relation = after_project.payload["metadata"]["otto_orchestrator"]
        self.assertEqual(after_relation["assignment_ref"], self.astrid_root.ref.to_dict())
        self.assertEqual(after_relation["portfolio_ref"], self.portfolio.to_dict())
        self.assertEqual(after_project.payload["outcome"], before_project.payload["outcome"])
        self.assertEqual(after_project.payload["metadata"]["keep"], "intact")
        self.assertEqual(self._default_identity(after_relation), before_default)

    def test_transfer_rejects_foreign_root_stale_pin_and_missing_overlap_ack(self):
        project = self.owner.graph.current(self.project.ref)
        relation = project.payload["metadata"]["otto_orchestrator"]
        foreign_portfolio = ResourceRef("owner", "wrk.portfolio", "foreign-portfolio")
        foreign_root = self.owner.assignments.assign(
            foreign_portfolio, role="orchestrator", principal="foreign-root",
            logical_request_key="foreign-root")
        with self.assertRaisesRegex(WorkValidationError, "outside the exact portfolio scope"):
            self._transfer(project, relation, target=foreign_root, request_id="foreign-transfer")
        with self.assertRaisesRegex(WorkValidationError, "revision is stale"):
            self._transfer(project, relation, target_assignment_revision="rev-0",
                           request_id="stale-transfer")
        with self.assertRaisesRegex(WorkValidationError, "overlap acknowledgement"):
            self._transfer(project, relation, overlap_acknowledged=False,
                           request_id="unacknowledged-transfer")
        current = self.owner.graph.current(self.project.ref)
        self.assertEqual(current.payload["metadata"]["otto_orchestrator"]["assignment_ref"],
                         self.default_root.ref.to_dict())


if __name__ == "__main__":
    unittest.main()

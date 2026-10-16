import tempfile
import unittest
from pathlib import Path

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work.model import WorkValidationError
from herzchen.domains.work import contributions
from herzchen.kernel import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class ExistingProjectOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "owner.sqlite", authority="owner")
        self.store.register_domain_handler((*contributions(), domain_contribution(),
                                             authoring_contribution(), packet_contribution()))
        self.binding = HerzchenBindingConfig("owner", "owner-credential")
        self.portfolio = ResourceRef("owner", "wrk.portfolio", "portfolio")
        seed = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner")
        self.orchestrator = seed.assignments.assign(
            self.portfolio, role="orchestrator", principal="orchestrator",
            session="orchestrator-session", logical_request_key="orchestrator")
        self.owner = PortfolioOwnerBootstrap(
            self.store, binding=self.binding, owner_actor="owner",
            portfolio_ref=self.portfolio, main_assignment_ref=self.orchestrator.ref)
        self.operations = self.owner.consumer_operations()
        self.projects = []
        self.specs = []
        for index in range(3):
            project = self.owner.graph.create_project(
                title=f"Project {index}", outcome=f"Mandate {index}",
                metadata={"preserve": index}, logical_request_key=f"project-{index}")
            assignment = self.owner.assignments.assign(
                project.ref, role="manager", principal=f"manager-{index}",
                session=f"session-{index}", logical_request_key=f"manager-{index}")
            self.projects.append(project)
            self.specs.append(self._spec(project, assignment))
        self.addCleanup(self.store.close)

    @staticmethod
    def _spec(project, assignment):
        return {
            "project_ref": project.ref.to_dict(),
            "project_version": project.version,
            "assignment_ref": assignment.ref.to_dict(),
            "assignment_revision": assignment.revision,
            "assignment_generation": assignment.generation,
        }

    def _request(self, specs=None, **extra):
        value = {
            "target_assignment_ref": self.orchestrator.ref.to_dict(),
            "target_assignment_revision": self.orchestrator.revision,
            "target_assignment_generation": self.orchestrator.generation,
            "projects": self.specs if specs is None else specs,
        }
        value.update(extra)
        return value

    def test_preview_is_inert_and_valid_selection_attaches_all_projects(self):
        before_counts = self.store.consumer().snapshot_counts()
        preview = self.operations.execute(
            "work.orchestrator.projects.attach", self._request(preview=True),
            request_id="preview", actor="owner")
        self.assertEqual(preview["outcome"], "preview")
        self.assertEqual(preview["writes"], 0)
        self.assertEqual(self.store.consumer().snapshot_counts(), before_counts)
        self.assertTrue(all("otto_orchestrator" not in project.payload["metadata"]
                            for project in (self.owner.graph.get(item.ref) for item in self.projects)))

        result = self.operations.execute(
            "work.orchestrator.projects.attach", self._request(),
            request_id="attach-selected", actor="owner")
        self.assertEqual(result["outcome"], "attached")
        self.assertEqual(result["writes"], 3)
        for original in self.projects:
            current = self.owner.graph.current(original.ref)
            self.assertEqual(current.payload["outcome"], original.payload["outcome"])
            self.assertEqual(current.payload["metadata"]["preserve"], original.payload["metadata"]["preserve"])
            relation = current.payload["metadata"]["otto_orchestrator"]
            self.assertEqual(relation["portfolio_ref"], self.portfolio.to_dict())
            self.assertEqual(relation["assignment_ref"], self.orchestrator.ref.to_dict())

    def test_foreign_target_and_stale_selected_inputs_are_rejected_before_effects(self):
        foreign_portfolio = ResourceRef("owner", "wrk.portfolio", "foreign-portfolio")
        foreign = self.owner.assignments.assign(
            foreign_portfolio, role="orchestrator", principal="foreign",
            logical_request_key="foreign-orchestrator")
        with self.assertRaises(WorkValidationError):
            self.operations.execute(
                "work.orchestrator.projects.attach",
                self._request(target_assignment_ref=foreign.ref.to_dict(),
                              target_assignment_revision=foreign.revision),
                request_id="foreign-target", actor="owner")
        self.assertIsNone(self.owner.graph.get(self.projects[0].ref).payload["metadata"].get("otto_orchestrator"))

        stale_project = self.owner.graph.revise(
            self.projects[1].ref, outcome="revised", logical_request_key="revise-project")
        self.assertNotEqual(stale_project.ref, self.projects[1].ref)
        with self.assertRaises(WorkValidationError):
            self.operations.execute(
                "work.orchestrator.projects.attach", self._request(),
                request_id="stale-project", actor="owner")
        self.assertIsNone(self.owner.graph.get(self.projects[0].ref).payload["metadata"].get("otto_orchestrator"))

        replacement = self.owner.assignments.reassign(
            self.owner.assignments.get(self.specs[0]["assignment_ref"]).ref,
            principal="manager-replacement", expected_generation=1,
            logical_request_key="replace-manager")
        stale_specs = list(self.specs)
        stale_specs[0] = dict(stale_specs[0], assignment_generation=1)
        with self.assertRaises(WorkValidationError):
            self.operations.execute(
                "work.orchestrator.projects.attach", self._request(stale_specs),
                request_id="stale-assignment", actor="owner")
        self.assertEqual(replacement.generation, 2)
        self.assertIsNone(self.owner.graph.get(self.projects[2].ref).payload["metadata"].get("otto_orchestrator"))

    def test_pending_unassigned_projects_attach_without_creating_managers(self):
        pending = self.owner.graph.create_project(title="Queued", logical_request_key="queued")
        spec = {"project_ref": pending.ref.to_dict(), "project_version": pending.version,
                "assignment_ref": None, "assignment_revision": None, "assignment_generation": None}
        request = self._request([self.specs[0], spec])
        before = self.store.consumer().find_identity_refs(kind="wrk.assignment", payload_matches={
            ("scope", "authority"): pending.ref.authority, ("scope", "kind"): pending.ref.kind,
            ("scope", "id"): pending.ref.id})
        counts = self.store.consumer().snapshot_counts()
        preview = self.operations.execute("work.orchestrator.projects.attach", {**request, "preview": True}, request_id="queued-preview", actor="owner")
        self.assertEqual(preview["outcome"], "preview")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        result = self.operations.execute("work.orchestrator.projects.attach", request, request_id="queued-attach", actor="owner")
        self.assertEqual(result["outcome"], "attached")
        current = self.owner.graph.get(pending.ref)
        self.assertEqual(current.payload["lifecycle"], "pending")
        for field in ("manager", "worker", "execution", "budget"):
            self.assertEqual(current.payload[field], pending.payload[field])
        after = self.store.consumer().find_identity_refs(kind="wrk.assignment", payload_matches={
            ("scope", "authority"): pending.ref.authority, ("scope", "kind"): pending.ref.kind,
            ("scope", "id"): pending.ref.id})
        self.assertEqual(before, after)
        replay = self.operations.execute("work.orchestrator.projects.attach", request, request_id="queued-attach", actor="owner")
        self.assertEqual(replay["outcome"], "replayed")

    def test_pending_null_pins_cannot_hide_existing_assignment_or_partial_pins(self):
        existing = {"project_ref": self.projects[0].ref.to_dict(), "assignment_ref": None,
                    "assignment_revision": None, "assignment_generation": None}
        with self.assertRaisesRegex(WorkValidationError, "current project assignment"):
            self.operations.execute("work.orchestrator.projects.attach", self._request([existing]), request_id="hidden-assignment", actor="owner")
        pending = self.owner.graph.create_project(title="Queued", logical_request_key="partial-queued")
        spec = {"project_ref": pending.ref.to_dict(), "assignment_ref": None, "assignment_generation": 1}
        with self.assertRaisesRegex(WorkValidationError, "absent assignment"):
            self.operations.execute("work.orchestrator.projects.attach", self._request([spec]), request_id="partial-null-pins", actor="owner")
        self.assertNotIn("otto_orchestrator", self.owner.graph.get(pending.ref).payload["metadata"])

    def test_noninert_pending_project_requires_assignment_pins(self):
        pending = self.owner.graph.create_project(title="Queued", logical_request_key="not-inert")
        changed = self.owner.graph.revise(pending.ref, lifecycle="active", logical_request_key="active-no-manager")
        with self.assertRaisesRegex(WorkValidationError, "inert pending"):
            self.operations.execute("work.orchestrator.projects.attach", self._request([{"project_ref": changed.ref.to_dict()}]), request_id="nonpending-null", actor="owner")
        self.assertNotIn("otto_orchestrator", self.owner.graph.get(pending.ref).payload["metadata"])

    def test_duplicate_selection_and_retained_replay_are_safe(self):
        duplicate = self.specs + [dict(self.specs[0])]
        with self.assertRaises(WorkValidationError):
            self.operations.execute(
                "work.orchestrator.projects.attach", self._request(duplicate),
                request_id="duplicate", actor="owner")
        self.assertTrue(all("otto_orchestrator" not in project.payload["metadata"]
                            for project in (self.owner.graph.get(item.ref) for item in self.projects)))

        first = self.operations.execute(
            "work.orchestrator.projects.attach", self._request(),
            request_id="retained", actor="owner")
        second = self.operations.execute(
            "work.orchestrator.projects.attach", self._request(),
            request_id="retained", actor="owner")
        self.assertEqual(first["outcome"], "attached")
        self.assertEqual(second["outcome"], "replayed")
        self.assertEqual(second["attachments"], first["attachments"])


if __name__ == "__main__":
    unittest.main()

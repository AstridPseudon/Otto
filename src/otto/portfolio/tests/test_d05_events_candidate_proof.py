"""D05 disposable host-bound proof over the accepted Events candidate."""

import tempfile
import unittest

from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import WorkGraph, contributions
from herzchen.kernel import ProjectHistoryGrant, SnapshotRefreshRequired, Store
from herzchen.kernel.project_history import AuthorizationError, ProjectHistoryError
from otto.portfolio.events_candidate_proof import run_candidate_journey
from otto.portfolio.observability_contract import CANDIDATE_COMMIT, RESOURCE_PINS, contract_record
from otto.portfolio.observability_views import ObservabilityViews


class EventsCandidateProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(self.temp.name + "/events.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(contributions(include_assignment_resources=True))
        self.actor = AuthenticatedActor("owner", "reader", "credential")
        self.store.configure_history_projection(batch_size=8)
        self.graph = WorkGraph(self.store, actor=self.actor)
        self.project = self.graph.create_project(title="Events", logical_request_key="d05-project")
        self.reader = self.store.project_history_reader(
            grant=ProjectHistoryGrant(self.actor, (self.project.id,), "d05-host", "grant-1")
        )
        self.views = ObservabilityViews(self.reader)

    def test_candidate_pins_use_current_checkpoint_and_delivered_worker_resource(self):
        record = contract_record()
        self.assertEqual(record["candidate"]["checkpoint"], CANDIDATE_COMMIT)
        self.assertEqual(record["candidate"]["status"], "candidate_not_adopted")
        self.assertEqual(record["resources"]["worker_brief"]["resource_ref"], "worker-cd2587a1bd225185b6f2dd1e")
        self.assertEqual(record["resources"], RESOURCE_PINS)

    def test_authenticated_json_text_and_bounded_detail_journey(self):
        proof = run_candidate_journey(
            views=self.views,
            grant=self.reader.grant,
            actor="reader",
            bound_actor="reader",
            project_ref=self.project.ref.to_dict(),
        )
        self.assertEqual(proof["schema"], "otto.events.candidate-proof.v1")
        self.assertEqual(proof["outcome"], "candidate_ready")
        self.assertFalse(proof["installed_claimed"])
        self.assertTrue(proof["limits"]["detail_bounded"])
        self.assertIn("Canonical response:", proof["renderings"]["text_overview"])
        self.assertEqual(proof["detail"]["facet_id"], proof["overview"]["rows"][0]["facet_id"])

    def test_withdrawn_unused_record_is_retained_without_acceptance(self):
        planning = self.graph.create_task(self.project, title="Unused plan", logical_request_key="d05-plan")
        self.graph.withdraw(planning.ref, logical_request_key="d05-withdraw")
        current = self.graph.get(planning.ref)
        self.assertEqual(current.lifecycle.value, "withdrawn")
        page = self.reader.read(projects=[self.project.ref], limit=50)
        withdrawn = [row for row in page["rows"] if row["subject_ref"]["id"] == planning.id
                     and row["summary"].get("after", {}).get("fields", {}).get("lifecycle") == "withdrawn"]
        self.assertTrue(withdrawn)
        self.assertNotIn("accepted", withdrawn[0]["summary"].get("after", {}).get("fields", {}))

    def test_foreign_stale_and_ambiguous_inputs_fail_closed(self):
        foreign = self.graph.create_project(title="Foreign", logical_request_key="d05-foreign")
        with self.assertRaises(AuthorizationError):
            self.reader.read(projects=[foreign.ref], limit=1)

        first = self.reader.read(projects=[self.project.ref], limit=1)
        self.store.configure_history_projection(batch_size=8).rebuild(batch_size=1)
        with self.assertRaises(SnapshotRefreshRequired):
            self.reader.read(projects=[self.project.ref], snapshot=first["snapshot"], limit=1)

        with self.assertRaises(ProjectHistoryError):
            self.reader.read(
                projects=[self.project.ref],
                from_at="2026-03-29T02:30:00",
                to_at="2026-03-29T03:30:00",
                timezone_name="Europe/Berlin",
                limit=1,
            )

    def test_each_page_reauthorizes_against_the_current_grant_reader(self):
        current = [self.reader.grant]
        reader = self.store.project_history_reader(
            grant_reader=lambda: current[0],
        )
        first = reader.read(projects=[self.project.ref], limit=1)
        current[0] = ProjectHistoryGrant(self.actor, (self.project.id,), "d05-host", "grant-2")
        with self.assertRaises(SnapshotRefreshRequired):
            reader.read(projects=[self.project.ref], snapshot=first["snapshot"], limit=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A pending project may hold inert tasks; they never dispatch.

Real owner Store: a draft accepts pending-lifecycle tasks through the typed
ProjectSheet route, refuses any task that could run, and the direction sync
path authors no task.
"""

from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.kernel.store import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio, PortfolioError
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


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
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner")
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())
        created = self.portfolio.create_draft(actor="owner", request_id="inert-create",
                                              title="A plan", brief="The plan brief")
        self.assertEqual(created["outcome"], "created", created)
        self.project_ref = created["project_ref"]

    def _record(self):
        return self.owner.graph.get(ResourceRef.from_dict(self.project_ref))

    def test_draft_edit_accepts_pending_task_without_activation_or_dispatch(self):
        edited = self.portfolio.edit_pending(self.project_ref, {"tasks": [_task("P01")]},
                                             actor="owner", request_id="inert-edit")
        self.assertIn(edited["outcome"], {"edited", "authored"}, edited)
        self.assertFalse(edited.get("dispatch", False))
        self.assertFalse(edited.get("launch", False))
        record = self._record()
        self.assertEqual(record.lifecycle.value, "pending")
        self.assertEqual(len(record.payload["tasks"]), 1)
        task = self.owner.graph.get(ResourceRef.from_dict(record.payload["tasks"][0]))
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
        task = self.owner.graph.get(ResourceRef.from_dict(record.payload["tasks"][0]))
        self.assertEqual(task.lifecycle.value, "pending")


if __name__ == "__main__":
    unittest.main()

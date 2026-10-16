"""A work-record revision is an immutable snapshot; a save names the task revision it read.

``owner.graph.get`` on a pinned task ref returns the content of exactly that
revision, or raises WorkNotFoundError for a revision never kept. A save file may
name each task's ``revision`` (the base it was read at); a task edited since is
refused as ``stale_base`` and nothing is written. Real owner Store, real lane.
"""

from collections.abc import Mapping
from pathlib import Path
import tempfile
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import admission, contributions
from herzchen.domains.work.model import WorkNotFoundError
from herzchen.kernel.store import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.plan_metadata import PLAN_NAMESPACE, register_plan_metadata


GOOD_PLAN = {"route": "normal", "size": 0.5, "lines": 40, "repo": "otto", "branch": "lab/A2"}
LATER_PLAN = dict(GOOD_PLAN, size=0.75, lines=60)


def _task(local_id, **extra):
    return {"id": local_id, "title": "Plan " + local_id, "instructions": "Do " + local_id,
            "acceptance": "Done " + local_id, **extra}


def _file(*tasks, title="Save plan", **extra):
    return {"project": {"title": title, "outcome": "One creation route"}, "tasks": list(tasks), **extra}


def unpinned(ref):
    return ResourceRef(ref.authority, ref.kind, ref.id)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="a2-revisions-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.sqlite"
        domains = tuple((*contributions(include_assignment_resources=True),
                         authoring_contribution(), content_contribution()))
        self.store = Store.create(self.path, authority="a2-revisions-test")
        self.store.register_domain_handler(domains)
        self.addCleanup(self.store.close)
        register_plan_metadata()
        binding = HerzchenBindingConfig("a2-revisions-test", "fixture-credential")
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner")
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    # ---- helpers -----------------------------------------------------------------

    def _counts(self):
        return self.store.consumer().snapshot_counts()

    def _save(self, document, **kwargs):
        return self.portfolio.save_project(document, actor="owner", **kwargs)

    def _created(self, *tasks, **extra):
        saved = self._save(_file(*tasks, **extra))
        self.assertEqual(saved["outcome"], "saved", saved)
        return saved

    def _project(self, ref):
        return self.owner.graph.get(ResourceRef.from_dict(ref))

    def _ref(self, saved, local_id="A"):
        """The task's unpinned durable ref, read from a save reply."""
        ref = ResourceRef.from_dict(saved["task_refs"][local_id])
        return ResourceRef(ref.authority, ref.kind, ref.id)

    def _at(self, saved, revision, local_id="A"):
        ref = self._ref(saved, local_id)
        return self.owner.graph.get(ResourceRef(ref.authority, ref.kind, ref.id, revision))

    def _current(self, saved, local_id="A"):
        return self.owner.graph.get(self._ref(saved, local_id))

    def _revision(self, value):
        return ResourceRef.from_dict(value).revision if isinstance(value, Mapping) else value.revision

    def _events(self, stream, event_type):
        return [event for event in self.store.list_events(stream=stream) if event.event_type == event_type]

    # ---- tests -------------------------------------------------------------------

    def test_get_returns_each_revisions_own_content(self):
        created = self._created(_task("A"))
        self.owner.graph.revise(self._ref(created), title="Direct edit", logical_request_key="direct-1")
        self.assertEqual(self._at(created, "rev-1").title, "Plan A")
        self.assertEqual(self._at(created, "rev-2").title, "Direct edit")
        self.assertEqual(self._current(created).title, "Direct edit")
        with self.assertRaises(WorkNotFoundError):
            self._at(created, "rev-99")
        revised = self._events("work:" + created["task_refs"]["A"]["id"], "work.revised")[-1]
        self.assertIn("title", revised.effects["history_summary"]["primary"]["changed_fields"])

    def test_mapping_form_of_a_pinned_ref_reads_its_own_revision(self):
        created = self._created(_task("A"))
        self.owner.graph.revise(self._ref(created), title="Direct edit", logical_request_key="direct-m")
        ref = self._ref(created)
        form = dict(ref.to_dict(), revision="rev-1")
        self.assertEqual(self.owner.graph.get(form).title, "Plan A")
        self.assertEqual(self.owner.graph.get({"ref": form}).title, "Plan A")
        self.assertEqual(self.owner.graph.get(dict(form, revision="rev-2")).title, "Direct edit")
        self.assertEqual(self.owner.graph.current(form).title, "Direct edit")
        for missing in (dict(form, revision="rev-99"), {"id": ref.id, "revision": "rev-99"}):
            with self.assertRaises(WorkNotFoundError):
                self.owner.graph.get(missing)

    def test_sheet_revision_keeps_the_old_content(self):
        created = self._created(_task("A"))
        second = self._save(_file(_task("A", title="Plan A two"), project_ref=created["project_ref"]))
        self.assertEqual(second["outcome"], "saved", second)
        self.assertEqual(self._at(created, "rev-1").title, "Plan A")
        self.assertEqual(self._at(created, "rev-2").title, "Plan A two")

    def test_first_save_names_the_created_task_revision(self):
        created = self._created(_task("A"))
        self.assertEqual(created["task_refs"]["A"]["revision"], "rev-1", created)
        self.assertEqual(self._revision(self._project(created["project_ref"]).payload["tasks"][0]), "rev-1")

    def test_second_save_names_the_new_task_revision(self):
        created = self._created(_task("A"))
        second = self._save(_file(_task("A", title="Plan A two"), project_ref=created["project_ref"]))
        self.assertEqual(second["outcome"], "saved", second)
        self.assertEqual(second["task_refs"]["A"]["revision"], "rev-2", second)
        project = self._project(second["project_ref"])
        self.assertEqual(self._revision(project.payload["tasks"][0]), "rev-2")
        applied = self._events("work:" + project.id, "work.project-sheet.applied")[-1]
        self.assertEqual(self._revision(applied.effects["mapping"]["A"]), "rev-2")

    def test_stale_task_after_direct_revision_is_refused_and_writes_nothing(self):
        created = self._created(_task("A"), _task("B"))
        self.owner.graph.revise(self._ref(created, "A"), title="Direct edit", logical_request_key="direct-4")
        counts = self._counts()
        stale = self._save(_file(
            _task("A", title="Old plan A", revision=created["task_refs"]["A"]["revision"]),
            _task("B", revision=created["task_refs"]["B"]["revision"]),
            project_ref=created["project_ref"]))
        self.assertEqual(stale["outcome"], "conflict", stale)
        self.assertEqual(stale["error"]["code"], "stale_base", stale)
        self.assertRegex(stale["error"]["message"], r"\bA\b")
        self.assertNotRegex(stale["error"]["message"], r"\bB\b")
        self.assertEqual(self._counts(), counts)
        self.assertEqual(self._current(created, "A").title, "Direct edit")

    def test_save_with_current_task_bases_is_accepted(self):
        created = self._created(_task("A"), _task("B"))
        saved = self._save(_file(
            _task("A", revision=created["task_refs"]["A"]["revision"]),
            _task("B", revision=created["task_refs"]["B"]["revision"]),
            project_ref=created["project_ref"]))
        self.assertEqual(saved["outcome"], "saved", saved)

    def test_task_base_revision_is_optional(self):
        created = self._created(_task("A"))
        self.owner.graph.revise(self._ref(created), title="Direct edit", logical_request_key="direct-6")
        saved = self._save(_file(_task("A"), project_ref=created["project_ref"]))
        self.assertEqual(saved["outcome"], "saved", saved)

    def test_history_entry_lists_changed_content_fields(self):
        created = self._created(_task("A", metadata_namespace={PLAN_NAMESPACE: GOOD_PLAN}))
        second = self._save(_file(
            _task("A", title="Plan A two", instructions="Do A two", acceptance="Done A two",
                  metadata_namespace={PLAN_NAMESPACE: LATER_PLAN}),
            project_ref=created["project_ref"]))
        self.assertEqual(second["outcome"], "saved", second)
        event = self._events("work:" + created["project_ref"]["id"], "work.project-sheet.applied")[-1]
        task_id = created["task_refs"]["A"]["id"]
        facets = [facet for facet in event.effects["history_summary"]["facets"] if facet["subject"]["id"] == task_id]
        self.assertEqual(len(facets), 1, event.effects["history_summary"])
        changed = facets[0]["changed_fields"]
        for field in ("title", "instructions", "acceptance", PLAN_NAMESPACE):
            self.assertIn(field, changed)

    def test_derived_name_follows_title(self):
        created = self._created(_task("A"))
        self.assertEqual(self._current(created).payload["name"], "Plan A")
        self._save(_file(_task("A", title="Plan A two"), project_ref=created["project_ref"]))
        current = self._current(created)
        self.assertEqual((current.payload["name"], current.title), ("Plan A two", "Plan A two"))
        self.owner.graph.revise(self._ref(created), title="Direct edit", logical_request_key="direct-8")
        current = self._current(created)
        self.assertEqual((current.payload["name"], current.title), ("Direct edit", "Direct edit"))

    def test_explicit_name_is_kept_when_the_title_changes(self):
        created = self._created(_task("A", name="Custom"))
        self._save(_file(_task("A", title="Plan A two"), project_ref=created["project_ref"]))
        current = self._current(created)
        self.assertEqual((current.payload["name"], current.title), ("Custom", "Plan A two"))

    def test_admitted_revision_resolves_to_its_own_content(self):
        created = self._created(_task("A"))
        owner = self.owner.owner_actor
        task = self.owner.graph.create_task(self._project(created["project_ref"]), title="Admitted plan",
                                            logical_request_key="admitted-task", actor=owner)
        before = self.owner.graph.admission_state(unpinned(task.ref))
        self.assertEqual(before["admitted_revision"], task.revision, before)
        stamp = before["stamp"]
        revised = self.owner.graph.revise(unpinned(task.ref), title="Later plan",
                                          logical_request_key="admitted-later", actor=owner)
        admitted = self.owner.graph.get(ResourceRef(task.ref.authority, task.ref.kind, task.ref.id, before["admitted_revision"]))
        later = self.owner.graph.get(ResourceRef(task.ref.authority, task.ref.kind, task.ref.id, revised.revision))
        self.assertEqual(admission.content_digest(admitted.payload), stamp["digest"])
        self.assertNotEqual(admission.content_digest(later.payload), stamp["digest"])


if __name__ == "__main__":
    unittest.main()

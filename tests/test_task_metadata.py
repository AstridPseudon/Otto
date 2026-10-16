"""Task metadata namespaces are typed.

A registered namespace validator refuses a bad payload through every writer
(work.create, work.revise and the project-sheet batch path) before any
revision is saved.  Tasks saved without metadata still read.
"""

from pathlib import Path
import tempfile
import unittest

from herzchen.domains.work import WorkGraph, WorkKind, contributions
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.model import WorkValidationError
from herzchen.domains.work.module import register_metadata_namespace
from herzchen.kernel.store import Store
from otto.portfolio.plan_metadata import PLAN_NAMESPACE, register_plan_metadata


GOOD_PLAN = {"route": "normal", "size": "small", "lines": 40, "repo": "otto", "branch": "lab/TYPE"}

BAD_PLANS = (
    {"route": "fast"},
    {"size": "huge"},
    {"lines": 0},
    {"lines": "40"},
    {"route": "normal", "colour": "blue"},
    {"branch": "lab/TYPE"},
)


def _sheet(task_alias, namespace_values, *, title="Batch plan"):
    return {"tasks": [{"alias": task_alias, "title": title, "metadata_namespace": {PLAN_NAMESPACE: namespace_values}}]}


class TaskMetadataWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="type-task-metadata-test-")
        self.addCleanup(self.temporary.cleanup)
        self.store = Store.create(Path(self.temporary.name) / "fixture.sqlite", authority="type-task-metadata-test")
        self.store.register_domain_handler(contributions())
        self.addCleanup(self.store.close)
        register_plan_metadata()
        self.graph = WorkGraph(self.store)
        self.batches = ProjectBatches(self.store)
        self.project = self.graph.create_project(title="Typed plan", outcome="Plans are typed")

    def _counts(self):
        return self.store.consumer().snapshot_counts()

    def _tasks(self):
        return self.graph.list(project=self.project, kind=WorkKind.TASK)

    def _task(self, alias, **kwargs):
        return self.graph.create(WorkKind.TASK, project=self.project, title="Plan " + alias, alias=alias, **kwargs)

    def test_create_stores_a_valid_plan(self):
        task = self._task("C1", metadata_namespaces={PLAN_NAMESPACE: GOOD_PLAN})
        self.assertEqual(self.graph.get(task.ref).payload["metadata_namespaces"], {PLAN_NAMESPACE: GOOD_PLAN})

    def test_create_refuses_bad_plans_before_any_record(self):
        counts = self._counts()
        for index, bad in enumerate(BAD_PLANS):
            with self.subTest(bad=bad):
                with self.assertRaises(WorkValidationError):
                    self._task("BAD%d" % index, metadata_namespaces={PLAN_NAMESPACE: bad})
        self.assertEqual(self._counts(), counts)
        self.assertEqual(self._tasks(), ())

    def test_revise_refusal_leaves_task_unchanged_and_corrected_revise_saves(self):
        task = self._task("R1", metadata_namespaces={PLAN_NAMESPACE: GOOD_PLAN})
        counts = self._counts()
        with self.assertRaises(WorkValidationError):
            self.graph.revise(task, metadata_namespaces={PLAN_NAMESPACE: {"route": "fast"}})
        self.assertEqual(self._counts(), counts)
        unchanged = self.graph.get(task.ref)
        self.assertEqual(unchanged.revision, task.revision)
        self.assertEqual(unchanged.payload["metadata_namespaces"], {PLAN_NAMESPACE: GOOD_PLAN})

        saved = self.graph.revise(task, metadata_namespaces={PLAN_NAMESPACE: {"route": "xhard"}})
        self.assertNotEqual(saved.revision, task.revision)
        self.assertEqual(saved.payload["metadata_namespaces"][PLAN_NAMESPACE]["route"], "xhard")

    def test_revise_refuses_bad_plans_and_leaves_no_revision(self):
        task = self._task("R2")
        counts = self._counts()
        for bad in BAD_PLANS:
            with self.subTest(bad=bad):
                with self.assertRaises(WorkValidationError):
                    self.graph.revise(task, metadata_namespaces={PLAN_NAMESPACE: bad})
                self.assertEqual(self._counts(), counts)

    def test_revise_merges_namespace_values_and_validates_the_merged_plan(self):
        task = self._task("M1", metadata_namespaces={PLAN_NAMESPACE: {"repo": "otto"}})
        saved = self.graph.revise(task, metadata_namespaces={PLAN_NAMESPACE: {"branch": "lab/TYPE"}})
        self.assertEqual(saved.payload["metadata_namespaces"][PLAN_NAMESPACE], {"repo": "otto", "branch": "lab/TYPE"})

        orphan = self._task("M2")
        with self.assertRaises(WorkValidationError):
            self.graph.revise(orphan, metadata_namespaces={PLAN_NAMESPACE: {"branch": "lab/TYPE"}})

    def test_batch_refuses_bad_task_and_project_plans_without_writes(self):
        counts = self._counts()
        for index, bad in enumerate(BAD_PLANS):
            with self.subTest(bad=bad):
                with self.assertRaises(WorkValidationError):
                    self.batches.apply_project_sheet(self.project, _sheet("BT%d" % index, bad),
                                                     logical_request_key="batch-bad-%d" % index)
                self.assertEqual(self._counts(), counts)
        with self.assertRaises(WorkValidationError):
            self.batches.apply_project_sheet(self.project, {"metadata_namespace": {PLAN_NAMESPACE: {"route": "fast"}}},
                                             logical_request_key="batch-bad-project")
        self.assertEqual(self._counts(), counts)
        self.assertEqual(self._tasks(), ())

    def test_batch_refusal_then_corrected_sheet_saves(self):
        with self.assertRaises(WorkValidationError):
            self.batches.apply_project_sheet(self.project, _sheet("BR1", {"route": "fast"}),
                                             logical_request_key="batch-recover-bad")
        self.batches.apply_project_sheet(self.project, _sheet("BR1", {"route": "xhard"}),
                                         logical_request_key="batch-recover-good")
        (task,) = self._tasks()
        self.assertEqual(task.payload["metadata_namespaces"][PLAN_NAMESPACE]["route"], "xhard")

    def test_unregistered_namespace_is_refused_through_every_writer(self):
        task = self._task("U1")
        counts = self._counts()
        unregistered = {"fixture.untyped": {"anything": 1}}
        with self.assertRaises(WorkValidationError):
            self._task("U2", metadata_namespaces=unregistered)
        with self.assertRaises(WorkValidationError):
            self.graph.revise(task, metadata_namespaces=unregistered)
        with self.assertRaises(WorkValidationError):
            self.batches.apply_project_sheet(
                self.project, {"tasks": [{"alias": "U3", "title": "x", "metadata_namespace": unregistered}]},
                logical_request_key="batch-unregistered")
        self.assertEqual(self._counts(), counts)

    def test_work_owned_namespaces_still_accepted_by_sheets(self):
        self.batches.apply_project_sheet(self.project, {"tasks": [{"alias": "W1", "title": "Policy task",
                                                                  "metadata_namespace": {"work.policy": {"mode": "owner"}}}]},
                                         logical_request_key="work-owned-namespace")
        (task,) = self._tasks()
        self.assertEqual(task.payload["metadata_namespaces"], {"work.policy": {"mode": "owner"}})

    def test_task_saved_without_metadata_still_reads(self):
        task = self._task("OLD1")
        self.assertNotIn("metadata_namespaces", task.payload)
        read = self.graph.get(task.ref)
        self.assertEqual((read.kind, read.lifecycle.value, read.title), (WorkKind.TASK, "pending", "Plan OLD1"))
        self.assertEqual([item.id for item in self._tasks()], [task.id])


class MetadataHookTests(unittest.TestCase):
    def test_registration_is_idempotent_for_the_same_validator_only(self):
        def first(values):
            return None

        def second(values):
            return None

        register_metadata_namespace("fixture.hook", first)
        register_metadata_namespace("fixture.hook", first)
        with self.assertRaises(WorkValidationError):
            register_metadata_namespace("fixture.hook", second)

    def test_work_owned_namespace_cannot_be_registered(self):
        with self.assertRaises(WorkValidationError):
            register_metadata_namespace("work.policy", lambda values: None)


if __name__ == "__main__":
    unittest.main()

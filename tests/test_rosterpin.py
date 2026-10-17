"""ROSTERPIN regressions for owner setup content and task admission."""

import unittest

from herzchen.content import ContentDocument, ContentRevision
from herzchen.contracts import ResourceRef, TransactionContext
from otto.portfolio.execution import _digest as _content_digest


class RosterPinTests(unittest.TestCase):
    def setUp(self):
        from otto.portfolio.tests.test_operating_setup import OperatingSetupTests

        fixture = OperatingSetupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.f = fixture.f

    def test_unrelated_unadmitted_sheet_task_preserves_admitted_a_launch(self):
        f = self.f
        a = f.task
        seeded = f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": a.id, "title": a.payload["title"]}]},
            logical_request_key="rosterpin-seed-a", actor=f.actor,
        )
        f.project = seeded.project
        f.task = f.owner.graph.current(a.ref)
        self.assertIsNotNone(
            f.owner.graph.admission_state(f.task.ref)["admitted_revision"]
        )

        setup = self.fixture.manual()
        activated_pin = f.project.ref.to_dict()
        self.assertEqual(
            f.app.prepare_operating_setup(
                project_ref=activated_pin, setup=setup,
                request_key="rosterpin-prepare"
            )["outcome"], "prepared"
        )
        self.assertEqual(
            f.app.activate_operating_setup(project_ref=activated_pin)["outcome"],
            "succeeded",
        )
        pending_a = next(
            due for due in f.port.list_due()
            if due["role"] == "worker"
            and due["target"]["task_ref"]["id"] == f.task.id
        )
        calls_before = len(f.provider.calls)

        added = f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": "D", "title": "Unrelated D"}]},
            logical_request_key="rosterpin-add-d", actor=f.actor,
        )
        current_project = added.project.ref.to_dict()
        d_ref = added.mappings["D"]
        self.assertEqual(f.owner.graph.current(f.task.ref).ref, f.task.ref)
        self.assertIsNone(
            f.owner.graph.admission_state(d_ref)["admitted_revision"]
        )
        self.assertTrue(
            f.app.read_operating_setup(project_ref=current_project)["ready"]
        )

        launched = f.app.start(schedule_id=pending_a["schedule_id"])
        self.assertEqual(launched["outcome"], "succeeded", launched)
        self.assertEqual(len(f.provider.calls), calls_before + 1)

        request = f.request()
        request.update(
            project_ref=current_project, task_ref=d_ref.to_dict(),
            request_key="rosterpin-unadmitted-d",
        )
        request["instruction_contract"]["task_ref"] = d_ref.to_dict()
        denied = f.app.assign_and_start(**request)
        self.assertEqual(denied["outcome"], "partial", denied)
        self.assertEqual(denied["stage"], "admission", denied)
        self.assertEqual(len(f.provider.calls), calls_before + 1)

    def _activated_worker(self, key):
        f = self.f
        seeded = f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": f.task.id, "title": f.task.payload["title"]}]},
            logical_request_key=key + "-seed-task", actor=f.actor,
        )
        f.project = seeded.project
        f.task = f.owner.graph.current(f.task.ref)
        self.assertIsNotNone(
            f.owner.graph.admission_state(f.task.ref)["admitted_revision"]
        )
        setup = self.fixture.manual()
        project_pin = f.project.ref.to_dict()
        self.assertEqual(f.app.prepare_operating_setup(
            project_ref=project_pin, setup=setup,
            request_key=key + "-prepare-setup")["outcome"], "prepared")
        self.assertEqual(f.app.activate_operating_setup(
            project_ref=project_pin)["outcome"], "succeeded")
        due = next(
            item for item in f.port.list_due()
            if item["role"] == "worker"
            and item["target"]["task_ref"]["id"] == f.task.id
        )
        return due, project_pin

    def _assert_start_refused_without_provider_call(self, due, *, stage, reason):
        f = self.f
        calls_before = len(f.provider.calls)
        result = f.app.start(schedule_id=due["schedule_id"])
        self.assertEqual(result["outcome"], "partial", result)
        self.assertEqual(result["stage"], stage, result)
        self.assertIn(reason, result["error"]["message"], result)
        self.assertEqual(len(f.provider.calls), calls_before)

    def test_changed_task_instructions_through_sheet_refuse_prepared_worker(self):
        f = self.f
        due, _project_pin = self._activated_worker("rosterpin-task-change")
        original = f.owner.graph.current(f.task.ref)
        f.owner.sheet.apply(
            f.project.ref,
            {"tasks": [{"id": f.task.id, "instructions": "Changed owner instructions"}]},
            logical_request_key="rosterpin-change-task-instructions", actor=f.actor,
        )
        changed = f.owner.graph.current(original.ref)
        self.assertNotEqual(changed.ref, original.ref)
        self.assertEqual(changed.payload["instructions"], "Changed owner instructions")
        self.assertIsNone(f.owner.graph.admission_state(changed.ref)["admitted_revision"])
        self._assert_start_refused_without_provider_call(
            due, stage="admission", reason="task_not_admitted"
        )

    def test_changed_adopted_mandate_content_refuses_prepared_worker(self):
        f = self.f
        due, _project_pin = self._activated_worker("rosterpin-mandate-change")
        mandate_pin = due["target"]["mandate_ref"]
        identity = ResourceRef(mandate_pin["authority"], mandate_pin["kind"], mandate_pin["id"])
        current = f.owner.content.read(identity)
        document = ContentDocument.from_dict(current["document"])
        revision_pin = current["current_revision"]
        before = current["revision"]["content"]
        after = {**before, "brief": {**before["brief"], "mandate": "Changed adopted mandate"}}
        revision = ContentRevision(
            identity, "rosterpin-mandate-revised", after, f.actor,
            parent_revision=revision_pin["revision"],
        )
        f.owner.content.execute(f.owner.content.build_append_revision(
            TransactionContext(
                f.actor, "rosterpin-append-mandate",
                _content_digest(after),
                expected_revision=revision_pin["revision"],
            ),
            document, revision,
        ))
        self._assert_start_refused_without_provider_call(
            due, stage="runtime", reason="mandate.brief"
        )

    def test_changed_project_acceptance_through_sheet_refuses_prepared_worker(self):
        f = self.f
        due, _project_pin = self._activated_worker("rosterpin-acceptance-change")
        changed = f.owner.sheet.apply(
            f.project.ref, {"acceptance": {"owner": "Changed project acceptance"}},
            logical_request_key="rosterpin-change-project-acceptance", actor=f.actor,
        )
        self.assertNotEqual(changed.project.ref, f.project.ref)
        self._assert_start_refused_without_provider_call(
            due, stage="runtime", reason="project.acceptance"
        )

"""Operating setup content pins through the real owner and fake provider."""
import unittest

from herzchen.domains.work import WorkGraph
from otto.portfolio.owner_readers import project_reader


class OperatingSetupPinContentTests(unittest.TestCase):
    def setUp(self):
        from otto.portfolio.tests.test_operating_setup import OperatingSetupTests
        fixture = OperatingSetupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.f = fixture.f

    def manual(self):
        return self.fixture.manual()

    def test_scoped_reader_exposes_only_retained_granted_project_revision(self):
        f = self.f
        old = f.project.ref
        f.owner.sheet.batches.apply_project_sheet(old, {"scope": "Edited scope"},
            logical_request_key="setup-pin-retained", actor=f.actor)
        retained = f.app.portfolio.operations.reader.get_revision(old)
        self.assertEqual(retained.ref, old)
        foreign = f.owner.graph.create_project(title="Other project",
            logical_request_key="setup-pin-foreign", actor=f.actor)
        self.assertIsNone(f.app.portfolio.operations.reader.get_revision(foreign.ref))

    def test_reviewed_activation_marker_does_not_change_setup_content(self):
        f = self.f
        pin = f.project.ref.to_dict()
        WorkGraph(f.store, actor=f.actor).revise(f.project.ref,
            fields={"reviewed_activation": {"request_key": "activation"}},
            logical_request_key="setup-pin-marker", actor=f.actor)
        observed = project_reader(f.app.portfolio.operations, pin)(
            {key: pin[key] for key in ("authority", "kind", "id")})
        self.assertNotEqual(observed["ref"], pin)
        self.assertTrue(observed["project_pin_content_matches"])

    def test_activated_setup_survives_other_task_plan_edit_and_launches_a_and_b(self):
        f = self.f
        graph = WorkGraph(f.store, actor=f.actor)
        batch = f.owner.sheet.batches.apply_project_sheet(f.project.ref,
            {"tasks": [{"id": alias, "title": "Task " + alias} for alias in "ABC"]},
            logical_request_key="setup-pin-seed", actor=f.actor)
        f.project = batch.project
        graph.revise(batch.mappings["C"], title="Admitted C",
            logical_request_key="setup-pin-admit-c", actor=f.actor)
        setup = self.manual()
        activated_pin = f.project.ref.to_dict()
        self.assertEqual(f.app.prepare_operating_setup(project_ref=activated_pin,
            setup=setup, request_key="setup-pin-prepare")["outcome"], "prepared")
        self.assertEqual(f.app.activate_operating_setup(project_ref=activated_pin)["outcome"], "succeeded")

        edited = f.owner.sheet.batches.apply_project_sheet(f.project.ref,
            {"tasks": [{"id": "C", "title": "Edited C"}]},
            logical_request_key="setup-pin-edit-c", actor=f.actor)
        current_project = edited.project.ref.to_dict()
        self.assertNotEqual(current_project["revision"], activated_pin["revision"])
        self.assertTrue(f.app.read_operating_setup(project_ref=current_project)["ready"])
        for alias in "AB":
            admitted = graph.revise(batch.mappings[alias], title="Admitted " + alias,
                logical_request_key="setup-pin-admit-" + alias, actor=f.actor)
            request = f.request()
            request.update(project_ref=current_project, task_ref=admitted.ref.to_dict(),
                request_key="setup-pin-worker-" + alias)
            request["instruction_contract"]["task_ref"] = admitted.ref.to_dict()
            worker = f.app.assign_worker(**request)
            self.assertEqual(worker["outcome"], "committed", worker)
            self.assertTrue(f.app.read_operating_setup(project_ref=current_project)["ready"])
            self.assertEqual(f.app.start(schedule_id=worker["schedule_id"])["outcome"], "succeeded")
        self.assertEqual(len(f.provider.calls), 3)

    def test_changed_project_scope_names_field_and_reactivation_command(self):
        f = self.f
        setup = self.manual()
        pin = f.project.ref.to_dict()
        self.assertEqual(f.app.prepare_operating_setup(project_ref=pin,
            setup=setup, request_key="setup-pin-scope")["outcome"], "prepared")
        self.assertEqual(f.app.activate_operating_setup(project_ref=pin)["outcome"], "succeeded")
        changed = f.owner.sheet.batches.apply_project_sheet(f.project.ref,
            {"scope": "New project scope"}, logical_request_key="setup-pin-change-scope", actor=f.actor)
        decision = f.app.read_operating_setup(project_ref=changed.project.ref.to_dict())
        self.assertFalse(decision["ready"])
        self.assertIn("project.scope", decision["blockers"][0]["message"])
        self.assertIn("operating-setup activate", decision["blockers"][0]["message"])
        self.assertEqual(len(f.provider.calls), 1)


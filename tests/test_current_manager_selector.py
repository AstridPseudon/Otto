"""Current occurrence selection preserves historical effects and exact scope."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from otto.portfolio.manager_journey_service import ManagerJourneyService

class CurrentManagerSelectorTests(unittest.TestCase):
    def setUp(self):
        self.assignment = {"authority":"fixture", "kind":"wrk.assignment", "id":"manager", "revision":"rev-2"}
        self.project = {"authority":"fixture", "kind":"work.project", "id":"project", "revision":"rev-1"}
        common = {"role":"manager", "recipient":"manager", "generation":1,
            "target":{"project_ref":self.project, "native_id":"same-session"}, "assignment_ref":self.assignment}
        self.rows = {"current":{**deepcopy(common), "stop_state":"active", "completion_state":"none", "in_flight_request":"prepared"},
            "old":{**deepcopy(common), "assignment_ref":{**self.assignment, "revision":"rev-1"},
                "stop_state":"completed", "completion_state":"succeeded", "in_flight_request":None,
                "completion_evidence":{"schema":"otto.role-result.v1", "result_digest":"retained-exact-result"}}}
        self.service = object.__new__(ManagerJourneyService)
        self.service.server = SimpleNamespace(state={"assignment_ref":self.assignment, "project_ref":self.project,
            "manager":"manager", "manager_generation":1, "schedule_id":"current", "manager_continuation":{"schedule_id":"old"}},
            due_port=SimpleNamespace(read_due=lambda key:deepcopy(self.rows.get(key))))

    def test_verified_old_revision_selects_current_prepared_occurrence_without_mutation(self):
        before = deepcopy(self.rows)
        self.assertEqual(self.service._current_manager_schedule(), "current")
        self.assertEqual(self.rows, before)

    def test_current_live_occurrence_is_kept_instead_of_another_preparation(self):
        self.rows["old"]["assignment_ref"] = self.assignment
        self.rows["old"].update(stop_state="active", completion_state="none", in_flight_request="live")
        self.assertEqual(self.service._current_manager_schedule(), "old")

    def test_unknown_or_unattempted_stale_intent_cannot_be_skipped(self):
        for state in ("unknown", "none"):
            with self.subTest(state=state):
                self.rows["old"].update(stop_state="active", completion_state=state, in_flight_request="original")
                with self.assertRaisesRegex(PermissionError, "require exact reconciliation"):
                    self.service._current_manager_schedule()

    def test_foreign_identity_generation_principal_project_and_missing_occurrence_denied(self):
        original = deepcopy(self.rows)
        changes = [("assignment_ref",{**self.assignment,"id":"foreign"}), ("generation",2),
            ("recipient","foreign"), ("target",{"project_ref":{**self.project,"id":"foreign"}})]
        for field,value in changes:
            with self.subTest(field=field):
                self.rows = deepcopy(original);self.rows["old"][field]=value
                with self.assertRaisesRegex(PermissionError,"foreign"):
                    self.service._current_manager_schedule()
        self.rows = deepcopy(original);self.rows.pop("current")
        with self.assertRaisesRegex(PermissionError,"missing"):
            self.service._current_manager_schedule()

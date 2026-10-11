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

class WorkerFocusInputBoundaryTests(unittest.TestCase):
    def test_invalid_focus_rejected_before_canonical_preparation_or_host_effects(self):
        for value in ('', ' ', 'x' * 4001, None):
            with self.subTest(focus=value if value is None else len(value)):
                service = object.__new__(ManagerJourneyService)
                service.commands = SimpleNamespace(_authorize=lambda:None, _key=lambda request:request['request_key'])
                service.host = SimpleNamespace(_closing=False)
                service.server = SimpleNamespace(state={'task_refs':{'T1':{'id':'task'}}})
                # No run_path, reader, execution factory or submit capability:
                # reaching any of those is a test failure at this boundary.
                result = service._submit_worker({'command':'run-worker','task':'T1','route':'normal',
                    'principal':'worker','request_key':'rejected-original','focus':value})
                self.assertEqual(result['outcome'], 'rejected')
                self.assertFalse(result['effects_started'])
                self.assertFalse(result['provider_called'])
                self.assertFalse(result['retry'])
                self.assertIn('manifest', result['next_action'])

class NativeManagerWorkerSubmissionTests(unittest.TestCase):
    def test_actual_native_context_retains_exact_manager_and_one_child_start(self):
        import json
        from otto.portfolio.tests.test_worker_occurrences import WorkerOccurrenceTests
        from otto.portfolio.identity_context import HostIngress
        fixture = WorkerOccurrenceTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.config['worker_operation_profiles'] = {}
        (fixture.run / 'run.yaml').write_text(json.dumps(fixture.config))
        fixture.server.state['workers'] = {}
        schedule = fixture.server.state['schedule_id']
        fixture.bindings['manager'] = fixture.binding(fixture.f.app._read(schedule))
        request = {**fixture.request, 'principal':'ordinary-leaf', 'request_key':'ordinary-native-worker'}
        before = len(fixture.f.provider.calls)
        answer = fixture.host._dispatch(request, ingress=HostIngress('synthetic-owner-caller', 'manager'))
        self.assertEqual(answer['outcome'], 'admitted', answer)
        slot = fixture.server.state['workers']['D02']
        self.assertEqual(slot['manager_schedule_id'], schedule)
        self.assertEqual(slot['schedule_id'], answer['occurrence']['schedule_id'])
        self.assertEqual(len(fixture.f.provider.calls), before)
        counts = fixture.f.store.consumer().snapshot_counts()
        again = fixture.host._dispatch(request, ingress=HostIngress('synthetic-owner-caller', 'manager'))
        self.assertEqual(again['occurrence'], answer['occurrence'])
        self.assertEqual(fixture.f.store.consumer().snapshot_counts(), counts)
        self.assertEqual(len(fixture.f.provider.calls), before)

    def test_missing_occurrence_fails_before_worker_preparation(self):
        import json, tempfile
        from pathlib import Path
        from otto.portfolio.manager_journey_service import _CALLER
        with tempfile.TemporaryDirectory() as tmp:
            service = object.__new__(ManagerJourneyService)
            service.commands = SimpleNamespace(_authorize=lambda:None, _key=lambda r:r['request_key'])
            service.host = SimpleNamespace(_closing=False)
            service.server = SimpleNamespace(state={'task_refs':{'T1':{'id':'task'}}, 'project_ref':{'id':'project'}})
            service.run_path = Path(tmp); (service.run_path / 'run.yaml').write_text(json.dumps({}))
            token = _CALLER.set({'role':'manager'})
            try:
                with self.assertRaisesRegex(PermissionError, 'exact authenticated occurrence'):
                    service._submit_worker({'command':'run-worker','task':'T1','route':'normal',
                        'principal':'worker','request_key':'missing-native-anchor','focus':'bounded'})
            finally:
                _CALLER.reset(token)

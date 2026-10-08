"""Focused service joins over real local assessment/completion fixture ports.

Only the execution boundary and queue receiver are replaced; real accepted
journals, task completion receipts, ref refresh and limit accounting execute.
"""
import copy
import json
from types import SimpleNamespace
import unittest
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from tests import test_manager_journey_command as command_fixture

class HelpCompletionRegressionTests(unittest.TestCase):
    setUp = command_fixture.ManagerJourneyCommandTests.setUp
    source = command_fixture.ManagerJourneyCommandTests.source
    request = command_fixture.ManagerJourneyCommandTests.request

    def pool(self):
        return LimitService(self.application.store).get_pool(ResourceRef(
            self.application.actor.authority, "limit", "local-inspection"))

    def service(self, outcome="succeeded"):
        state = self.fixture.state
        state.update(requested_model="fixture", requested_reasoning="high", schedule_id="anchor",
                     manager_continuation={"schedule_id": "anchor", "outcome": "succeeded"})
        fixture = SimpleNamespace(active=True, recover_calls=0, prepare_calls=0, queued=[], saved=[], review=None,
            replay=False, foreign_anchor=False)
        raw = {"schedule_id": "help", "role": "manager", "stop_state": "active", "in_flight_request": "help-work",
               "host_evidence": {"gateway_attempt": {"retained": True}},
               "assignment_ref": state["assignment_ref"], "generation": state["manager_generation"],
               "target": {"task_ref": state["task_refs"]["PA01"]}}
        self.commands.due_port = SimpleNamespace(list_due=lambda: [raw] if fixture.active else [])
        due = lambda key: SimpleNamespace(schedule_id=key,
            assignment_ref={**state["assignment_ref"], "id": "foreign"} if fixture.foreign_anchor else state["assignment_ref"],
            generation=state["manager_generation"], target={"native_id": "retained-manager"},
            in_flight_request="task-wake-work", instruction="Inspect committed task results")
        def prepare(**kw):
            fixture.prepare_calls += 1
            return {"outcome": "replayed" if fixture.replay else "prepared", "schedule_id": "help"}
        def recover(**kw):
            fixture.recover_calls += 1
            fixture.review = self.commands.review_task(self.request(key="inside-help"))
            self.assertEqual(fixture.review["outcome"], "accepted")
            self.assertEqual(fixture.review["completion"]["outcome"], "pending")
            if outcome in {"succeeded", "replayed"}: fixture.active = False
            return {"outcome": outcome, "schedule_id": "help"}
        app = SimpleNamespace(_read=due, continue_manager_from_help=prepare, recover=recover,
            continue_manager_after_tasks=lambda **kw: {"outcome": "prepared", "schedule_id": "task-wake"})
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.commands = self.commands
        service.server = SimpleNamespace(state=state, owner=self.application.owner,
            _save_state=lambda: fixture.saved.append(copy.deepcopy(state)))
        service.host = SimpleNamespace(_closing=False,
            submit=lambda request: fixture.queued.append(dict(request)) or {"outcome": "pending", "request_id": "retained-wake"})
        service._execution = lambda **kw: app
        request = {"command": "manager-help-result", "principal": "manager", "schedule_id": "anchor",
                   "report_ref": {"retained": "reply"}, "generation": state["manager_generation"]}
        return service, fixture, request

    def test_help_success_settles_accepted_pending_finish_and_retains_wake(self):
        service, fixture, request = self.service()
        result = service(request)
        self.assertEqual(result["completion_intents"][0]["result"]["outcome"], "completed")
        current = self.fixture.state["task_refs"]["PA01"]
        self.assertEqual(current["revision"], "rev-2")
        self.assertEqual(self.application.owner.graph.reader.get_identity(ResourceRef.from_dict(current)).payload["lifecycle"], "completed")
        self.assertEqual(fixture.queued, [{"command": "manager-task-settlement", "principal": "manager", "schedule_id": "task-wake"}])
        self.assertEqual(fixture.saved[-1]["manager_continuation"]["schedule_id"], "task-wake")
        self.assertEqual(self.pool().cumulative_used_units, 1)
        self.assertEqual(self.application.provider.calls, [])
        # Restart the command composition over retained real journals; CLI form
        # reuses automatic missing-discriminator finish without new assessment.
        restarted = ManagerJourneyCommands(owner=self.application.owner, portfolio=self.application.app.portfolio,
            state=self.fixture.state)
        replay = restarted.finish_task({"command": "finish-task", "task": "PA01",
            "request_key": "inside-help:finish", "review_key": "inside-help"})
        self.assertEqual(replay["outcome"], "replayed")
        fixture.replay = True
        self.assertEqual(service(request)["outcome"], "replayed")
        self.assertEqual(fixture.recover_calls, 1)
        self.assertEqual(len(fixture.queued), 1)
        self.assertEqual(self.pool().cumulative_used_units, 1)

    def test_help_unknown_preserves_pending_finish_without_task_wake(self):
        service, fixture, request = self.service("unknown")
        original = copy.deepcopy(self.fixture.state["task_refs"]["PA01"])
        result = service(request)
        self.assertEqual(result["outcome"], "unknown")
        self.assertNotIn("completion_intents", result)
        self.assertEqual(self.fixture.state["task_refs"]["PA01"], original)
        self.assertEqual(fixture.queued, [])
        self.assertIsNotNone(self.commands._journal("inside-help:finish", "finish-intent"))
        self.assertEqual(self.pool().cumulative_used_units, 1)

    def test_help_foreign_generation_and_assignment_reject_before_execution(self):
        service, fixture, request = self.service()
        for changed in ({**request, "generation": 2}, {**request, "principal": "other"}):
            with self.subTest(changed=changed), self.assertRaises(PermissionError): service(changed)
        fixture.foreign_anchor = True
        with self.assertRaises(PermissionError): service(request)
        self.assertEqual((fixture.prepare_calls, fixture.recover_calls, fixture.queued), (0, 0, []))
        self.assertIsNone(self.commands._journal("inside-help", "review"))

    def test_legacy_explicit_command_finish_intent_preserves_original_journal(self):
        review = self.commands.review_task({**self.request(key="legacy-review"), "finish": False})
        self.assertEqual(review["outcome"], "accepted")
        legacy = {"command": "finish-task", "task": "PA01", "request_key": "legacy-finish", "review_key": "legacy-review"}
        self.commands._journal("legacy-finish", "finish-intent", legacy)
        before = json.dumps(self.commands._journal("legacy-finish", "finish-intent"), sort_keys=True)
        result = self.commands.finish_task({k: v for k, v in legacy.items() if k != "command"})
        self.assertEqual(result["outcome"], "completed")
        self.fixture.state["task_refs"]["PA01"] = result["task_ref"]
        self.assertEqual(self.commands.finish_task(legacy)["outcome"], "replayed")
        self.assertEqual(json.dumps(self.commands._journal("legacy-finish", "finish-intent"), sort_keys=True), before)
        self.assertEqual(self.pool().cumulative_used_units, 1)

    def test_finish_semantic_drift_and_wrong_discriminator_reject_without_effects(self):
        reviewed = self.commands.review_task(self.request(key="drift-review"))
        self.fixture.state["task_refs"]["PA01"] = reviewed["completion"]["task_ref"]
        finish = {"command": "finish-task", "task": "PA01", "request_key": "drift-review:finish", "review_key": "drift-review"}
        before = self.application.owner.graph.reader.snapshot_counts()
        for changed in ({**finish, "command": "review-task"}, {**finish, "review_key": "other"}, {**finish, "task": "PA06"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError): self.commands.finish_task(changed)
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.pool().cumulative_used_units, 1)
        self.assertEqual(self.application.provider.calls, [])

    def test_automatic_finish_accepts_same_public_cli_request_after_completion(self):
        reviewed = self.commands.review_task(self.request(key="automatic-review"))
        self.fixture.state["task_refs"]["PA01"] = reviewed["completion"]["task_ref"]
        before = self.commands._journal("automatic-review:finish", "finish-intent")
        replay = self.commands.finish_task({"command": "finish-task", "task": "PA01",
            "request_key": "automatic-review:finish", "review_key": "automatic-review"})
        self.assertEqual(replay["outcome"], "replayed")
        self.assertEqual(self.commands._journal("automatic-review:finish", "finish-intent"), before)
        self.assertEqual(self.pool().cumulative_used_units, 1)

    def test_wrong_retained_discriminator_cannot_be_normalized_into_finish(self):
        self.commands.review_task({**self.request(key="bad-prior-review"), "finish": False})
        finish = {"task": "PA01", "request_key": "bad-prior-finish", "review_key": "bad-prior-review"}
        self.commands._journal("bad-prior-finish", "finish-intent", {**finish, "command": "review-task"})
        before = self.application.owner.graph.reader.snapshot_counts()
        with self.assertRaises(ValueError): self.commands.finish_task(finish)
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.pool().cumulative_used_units, 1)

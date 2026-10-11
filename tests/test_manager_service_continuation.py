"""Explicit continuation checks use the maintained owner and a fake provider."""
from datetime import timedelta
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, patch
from herzchen.domains.work import Lifecycle

from otto.portfolio.manager_continuation_command import manager_continuation_from_command
from otto.portfolio.execution_operations import derive_manager_continuation_request, read_project_progress_reports
from tests.test_execution_application import ExecutionApplicationTests, NOW


class ManagerServiceContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExecutionApplicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        assignment, guide, mandate = f.role_handles("manager", "manager", "manager-session")
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="settled-manager",
            instruction="Inspect current project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        first = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(first["outcome"], "succeeded")
        self.anchor = first["schedule_id"]
        self.key = "explicit-pa02-inspection"
        f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "PA02", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "next_action": "Inspect retained PA02 source and its acceptance boundary; do not rerun its worker.",
             "logical_request_key": self.key, "recorded_at": (NOW + timedelta(minutes=1)).isoformat()},
            expected_generation=1, logical_request_key=self.key, actor=f.actor)
        self.provider_calls = len(f.provider.calls)

    def reports(self):
        f = self.fixture
        return read_project_progress_reports(f.store.consumer(), f.project.ref.to_dict())

    def test_settled_task_notification_is_not_replayed_after_public_resource_adoption(self):
        from herzchen.contracts import ResourceRef
        from herzchen.content.instructions import validate_instruction_content
        from otto.portfolio.execution import OccurrencePreparationError, _digest
        f = self.fixture
        prior = f.app._read(self.anchor)
        guide = next(ref for ref in prior.context_refs if ref != prior.target['mandate_ref'])
        doc = f.app.portfolio.create_document(f.project.ref, actor='manager', request_id='completion-artifact',
            document_id='completion-artifact', role='SOURCE', content={'observed': 'fixture artifact'})
        artifact = doc['record']['payload']['current_revision']
        from herzchen.domains.assessment import AssessmentModule
        from herzchen.kernel.limits import LimitService
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope('finish-scope', parent_obligation=f.task.ref,
            protocol='fixture-inspection', criteria=[{'id': 'inspected', 'definition': 'Fixture artifact inspected'}],
            designated_approver='manager', policy={'required_for_completion': True}, logical_request_key='finish-scope')
        packet = assessment.freeze_input(scope.ref, packet={'observed': 'fixture artifact'},
            consumed_refs=[ResourceRef.from_dict(artifact)], logical_request_key='finish-input')
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, 'limit', 'finish-allowance'),
            capacity_units=1, cumulative_allowance_units=1, logical_request_key='finish-allowance', actor=f.actor)
        judged = assessment.assess(scope.ref, candidate=ResourceRef.from_dict(artifact), criterion=scope.criterion_refs[0],
            input_packet=packet.ref, verdict='PASS', limit_pool=pool.ref, logical_request_key='finish-judgment')
        gate = assessment.accept(judged.ref, rationale='Observed fixture artifact',
            evidence_refs=[ResourceRef.from_dict(artifact)], logical_request_key='finish-acceptance')
        f.app.assignments.complete(f.task.ref, project=f.project.ref, assignment=prior.assignment_ref,
            expected_generation=1, expected_project_revision=f.project.ref.revision,
            expected_task_revision=f.task.ref.revision, disposition='accepted', evidence_refs=[artifact],
            evidence_hashes={artifact['kind'] + ':' + artifact['id'] + ':' + artifact['revision']: _digest({'observed': 'fixture artifact'})},
            gate_refs=[gate.ref.to_dict()], candidate_ref=artifact,
            logical_request_key='fixture-real-finish', actor=f.actor)
        old = f.app.continue_manager_after_tasks(manager_schedule_id=self.anchor, execute=True)
        self.assertEqual(old['outcome'], 'succeeded', old)
        old_due = f.port.read_due(old['schedule_id'])
        # Revisit the exact already-created callback before any resource
        # adoption. Recovery must not reference help-only variables or submit
        # another native turn/debit for the same completed-task notification.
        calls_after = len(f.provider.calls)
        same = f.app.continue_manager_after_tasks(manager_schedule_id=self.anchor, execute=True)
        self.assertEqual(same['outcome'], 'replayed', same)
        self.assertEqual(f.port.read_due(old['schedule_id']), old_due)
        self.assertEqual(len(f.provider.calls), calls_after)
        base = f.app.assignments.get(ResourceRef.from_dict(prior.assignment_ref))
        content = f.owner.content.read(ResourceRef.from_dict(guide))['content']
        current = f.app.assignments.adopt_resources(base.ref,
            resources=[{'resource_ref': guide, 'resource_name': content['name'],
                'content_digest': validate_instruction_content(content), 'required': True}],
            expected_revision=base.revision, expected_generation=base.generation,
            logical_request_key='new-resource-adoption', actor=f.actor)
        mandate_content = f.owner.content.read(ResourceRef.from_dict(prior.target['mandate_ref']))['content']
        current_task = f.owner.graph.get(f.task.ref).ref.to_dict()
        made = f.app.portfolio.create_document(f.project.ref, actor='manager', request_id='current-mandate',
            document_id='current-mandate', role='mandate', content={**mandate_content,
                'assignment_ref': current.ref.to_dict(), 'task_ref': current_task,
                'instruction_contract': {**mandate_content['instruction_contract'], 'task_ref': current_task}})
        mandate = made['record']['payload']['current_revision']
        prepared = f.app.prepare_role(role='manager', project_ref=f.project.ref.to_dict(), task_ref=current_task,
            assignment_ref=current.ref.to_dict(), generation=1, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key='new-current-intent', instruction='Inspect remaining work',
            model='gpt-test', reasoning='high', profile='workspace-write', native_session_id='manager-session')
        settled = f.app.start(schedule_id=prepared['schedule_id'])
        self.assertEqual(settled['outcome'], 'succeeded', settled)
        calls = len(f.provider.calls); before = f.owner.graph.reader.snapshot_counts()
        observed = f.app.continue_manager_after_tasks(manager_schedule_id=settled['schedule_id'], execute=True)
        self.assertEqual(observed['outcome'], 'already_observed')
        self.assertEqual(f.port.read_due(old['schedule_id']), old_due)
        self.assertEqual(len(f.provider.calls), calls)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), before)
        # The installed service must choose the same current verified anchor,
        # even when its informational continuation metadata still names the
        # original successful manager revision. Neither acceptance nor provider
        # work is repeated merely to prepare a task-settlement destination.
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        service = object.__new__(ManagerJourneyService)
        current_due = f.port.read_due(settled['schedule_id'])
        service.server = SimpleNamespace(state={'assignment_ref': current_due['assignment_ref'],
            'project_ref': current_due['target']['project_ref'], 'manager': 'manager',
            'manager_generation': 1, 'schedule_id': current_due['schedule_id'],
            'manager_continuation': {'schedule_id': old_due['schedule_id']}}, due_port=f.port)
        service.host = SimpleNamespace(_closing=False)
        current_before = f.port.read_due(current_due['schedule_id'])
        selected = service._retain_task_settlement(f.app)
        self.assertEqual(selected['outcome'], 'already_observed', selected)
        self.assertEqual(f.port.read_due(current_due['schedule_id']), current_before)
        self.assertEqual(f.port.read_due(old_due['schedule_id']), old_due)
        self.assertEqual(len(f.provider.calls), calls)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), before)
        # Unknown historical delivery is not promoted to observed/success.
        read_due = f.port.read_due
        with patch.object(type(f.port), 'read_due', new=lambda port, schedule: (
                {**old_due, 'completion_state': 'unknown'} if schedule == old['schedule_id'] else read_due(schedule))):
            with self.assertRaisesRegex(OccurrencePreparationError, 'binding differs'):
                f.app.continue_manager_after_tasks(manager_schedule_id=settled['schedule_id'], execute=True)
        self.assertEqual(len(f.provider.calls), calls)

    def call(self, operation="prepare", current=None):
        f = self.fixture
        return manager_continuation_from_command(
            request={"report_key": self.key, "operation": operation}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=current or self.anchor,
            native_session_id="manager-session", task_refs={"PA02": f.task.ref.to_dict()},
            read_reports=self.reports)

    def test_external_explicit_report_is_consumed_prepare_restart_and_duplicate_without_provider(self):
        f = self.fixture
        self.assertIsNone(derive_manager_continuation_request(f.app._read(self.anchor), self.reports()))
        first = self.call()
        self.assertEqual(first["outcome"], "committed", first)
        identity = first["continuation"]["schedule_id"]
        due = f.port.read_due(identity)
        self.assertEqual(due["target"]["native_id"], "manager-session")
        self.assertEqual(due["target"]["task_ref"], f.task.ref.to_dict())
        self.assertIn("retained PA02", due["instruction"])
        self.assertEqual(due["in_flight_request"], self.key)
        f.compose()
        repeated = self.call()
        self.assertEqual(repeated["continuation"]["schedule_id"], identity)
        self.assertEqual(repeated["outcome"], "prepared")
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        self.assertEqual(self.call("status")["request"]["logical_request_key"], self.key)

    def test_explicit_command_consumes_retained_action_in_same_session_with_fake_provider(self):
        f = self.fixture
        result = self.call("dispatch")
        self.assertEqual(result["outcome"], "succeeded", result)
        identity = result["continuation"]["schedule_id"]
        due = f.port.read_due(identity)
        self.assertEqual(due["last_result"]["physical_session_id"], "manager-session")
        self.assertEqual(due["target"]["task_ref"], f.task.ref.to_dict())
        self.assertEqual(due["assignment_ref"]["id"], f.app._read(self.anchor).assignment_ref["id"])
        self.assertIn("Inspect retained PA02 source", f.provider.calls[-1])
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        f.compose()
        repeated = self.call("dispatch")
        self.assertEqual(repeated["outcome"], "replayed")
        self.assertEqual(repeated["continuation"]["schedule_id"], identity)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

    def test_existing_unknown_is_not_replayed_and_blocks_dispatch(self):
        f = self.fixture
        prior = f.app._read(self.anchor)
        unknown = replace(prior, schedule_id="existing-unknown", completion_state="unknown",
            delivery_state="unknown", last_result={"outcome": "unknown", "retry_allowed": False})
        f.port.save_due(unknown.schedule_id, unknown.to_dict(), request_id="fixture-original-unknown", expected_version=0)
        before = f.port.read_due(unknown.schedule_id)
        prepared = self.call(current=unknown.schedule_id)
        self.assertEqual(prepared["outcome"], "committed")
        self.assertTrue(prepared["current_unknown_effect"])
        with patch.object(f.app, "continue_manager", wraps=f.app.continue_manager) as continued:
            held = self.call("dispatch", current=unknown.schedule_id)
        self.assertEqual(held["outcome"], "held")
        continued.assert_not_called()
        self.assertEqual(f.port.read_due(unknown.schedule_id), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_report_key_scope_and_current_task_pin_fence_preparation(self):
        f = self.fixture
        real = self.reports()
        changed = [{**item, "value": {**item["value"], "project_ref": {**f.project.ref.to_dict(), "id": "foreign"}}} for item in real]
        with patch.object(f.app, "continue_manager") as continued:
            result = manager_continuation_from_command(
                request={"report_key": self.key}, execution=f.app, anchor_schedule_id=self.anchor,
                current_schedule_id=self.anchor, native_session_id="manager-session",
                task_refs={"PA02": f.task.ref.to_dict()}, read_reports=lambda: changed)
        self.assertEqual(result["outcome"], "idle")
        continued.assert_not_called()

    def test_roster_only_session_uses_retained_anchor_binding_not_uncreated_callback(self):
        f = self.fixture
        with patch.object(f.app, "_verify_native_binding", wraps=f.app._verify_native_binding) as verify:
            result = self.call()
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(verify.call_args.args[2], self.anchor)

    def test_same_prepared_callback_refreshes_project_revision_without_rebinding_task(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        before = f.port.read_due(schedule)
        self.assertIsNone((before.get("host_evidence") or {}).get("gateway_attempt"))
        project = f.owner.graph.set_lifecycle(f.project.ref, Lifecycle.ACTIVE,
            logical_request_key="owner-project-advanced", actor=f.actor)
        self.assertNotEqual(project.ref.to_dict(), before["target"]["project_ref"])
        with patch.object(f.app, "_manager_project_reference", side_effect=lambda due, assignment: due):
            failed = f.app.start(schedule_id=schedule)
        self.assertEqual(failed["outcome"], "partial", failed)
        self.assertEqual(failed["error"]["message"], "project does not match the pinned canonical reference")
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)
        # This public same-occurrence recovery is the real retry of the previous
        # pre-runtime failure, through canonical briefing and gateway/provider.
        result = f.app.recover(schedule_id=schedule, execute=True)
        self.assertEqual(result["outcome"], "succeeded", result)
        after = f.port.read_due(schedule)
        self.assertEqual(after["target"]["project_ref"], project.ref.to_dict())
        for field in ("task_ref", "reported_task_ref", "mandate_ref", "native_id"):
            self.assertEqual(after["target"][field], before["target"][field])
        self.assertEqual(after["assignment_ref"], before["assignment_ref"])
        self.assertEqual(after["generation"], before["generation"])
        self.assertEqual(after["invocation_identity"], before["invocation_identity"])
        reconciliation = after["host_evidence"]["manager_project_reconciliation"]
        self.assertEqual(reconciliation["before_project_ref"], before["target"]["project_ref"])
        self.assertEqual(reconciliation["current_project_ref"], project.ref.to_dict())
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        original = after
        self.assertEqual(f.app.recover(schedule_id=schedule, execute=True)["outcome"], "replayed")
        self.assertEqual(f.port.read_due(schedule), original)
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)

    def test_project_reconciliation_rejects_foreign_scope_and_never_edits_attempted_due(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        due = f.app._read(schedule)
        assignment = f.app._current(due.assignment_ref, due.generation)
        foreign = replace(due, target={**due.target, "project_ref": {**due.target["project_ref"], "id": "foreign-project"}})
        with self.assertRaisesRegex(ValueError, "current manager scope"):
            f.app._manager_project_reference(foreign, assignment)
        attempted = replace(due, host_evidence={**(due.host_evidence or {}),
            "gateway_attempt": {"state": "attempt", "process_created": False}})
        with patch("otto.portfolio.execution.project_reader") as read:
            self.assertEqual(f.app._manager_project_reference(attempted, assignment), attempted)
            read.assert_not_called()
        self.assertEqual(f.app._read(schedule), due)
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_new_bound_callback_is_prepared_with_current_project_revision_without_provider(self):
        f = self.fixture
        project = f.owner.graph.set_lifecycle(f.project.ref, Lifecycle.ACTIVE,
            logical_request_key="project-before-callback", actor=f.actor)
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        due = f.port.read_due(prepared["continuation"]["schedule_id"])
        self.assertEqual(due["target"]["project_ref"], project.ref.to_dict())
        self.assertIn('"report_consumed_by_this_invocation":true', due["message"])
        self.assertIn("do not redispatch that report", due["message"])
        self.assertEqual(due["target"]["task_ref"], f.app._read(self.anchor).target["task_ref"])
        self.assertIsNone((due.get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(len(f.provider.calls), self.provider_calls)

    def test_consumed_transport_prose_is_advice_not_the_delivered_work_instruction(self):
        f = self.fixture
        anchor_before = f.port.read_due(self.anchor)
        assignment = f.app.assignments.get(f.app._read(self.anchor).assignment_ref)
        key = "transport-and-artifact-action"
        reported = "Use this report through manager-continue with operation dispatch; then deliver the artifact."
        f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "PA02", "task_ref": f.task.ref.to_dict(), "continue_requested": True,
             "next_action": reported, "logical_request_key": key,
             "recorded_at": (NOW + timedelta(minutes=1)).isoformat()},
            expected_generation=1, logical_request_key=key, actor=f.actor)
        reports = self.reports()
        prepared = manager_continuation_from_command(
            request={"report_key": key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=lambda: reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        due = f.port.read_due(schedule)
        self.assertNotIn(reported, due["instruction"])
        self.assertIn("Advance the adopted manager objective", due["instruction"])
        context = json.loads(due["message"].split("\n", 1)[1])
        self.assertEqual(context["current_intent"]["source"], "adopted_manager_contract")
        self.assertEqual(context["current_intent"]["reported_next_action"], reported)
        self.assertEqual(context["current_intent"]["next_action"], due["instruction"])
        self.assertTrue(context["current_continuation"]["report_consumed_by_this_invocation"])
        self.assertEqual(f.app.start(schedule_id=schedule)["outcome"], "succeeded")
        self.assertIn(due["instruction"], f.provider.calls[-1])
        invocation = json.loads(f.provider.calls[-1].split("<otto-invocation-request", 1)[1]
                                .split("\n", 1)[1].split("\n</otto-invocation-request>", 1)[0])
        delivered_instruction, delivered_context = invocation["prompt"].split(
            "\nCurrent canonical manager report context:\n", 1)
        self.assertEqual(delivered_instruction, due["instruction"])
        self.assertEqual(json.loads(delivered_context), context)
        f.compose()
        self.assertEqual(f.app.start(schedule_id=schedule)["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), self.provider_calls + 1)
        self.assertEqual(f.port.read_due(self.anchor), anchor_before)
        self.assertEqual(self.reports(), reports)

    def test_worker_result_wakes_same_manager_without_a_progress_report_or_worker_replay(self):
        f = self.fixture
        worker = f.app.assign_and_start(**f.request())
        before = f.port.read_due(worker["schedule_id"])
        reports = self.reports()
        calls = len(f.provider.calls)
        prepared = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=False)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        due = f.port.read_due(prepared["schedule_id"])
        self.assertEqual(due["target"]["native_id"], "manager-session")
        self.assertEqual(due["target"]["reported_task_ref"], before["target"]["task_ref"])
        self.assertIn(worker["schedule_id"], due["instruction"])
        self.assertIn("not task acceptance", due["instruction"])
        result = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(result["outcome"], "succeeded", result)
        self.assertEqual(len(f.provider.calls), calls + 1)
        f.compose()
        duplicate = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(duplicate["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), calls + 1)
        self.assertEqual(f.port.read_due(worker["schedule_id"]), before)
        self.assertEqual(self.reports(), reports)
        self.assertNotEqual(f.owner.graph.get(f.task.ref).lifecycle.value, "completed")

    def test_worker_result_waits_for_manager_settlement_without_preparing_or_provider(self):
        f = self.fixture
        worker = f.app.assign_and_start(**f.request())
        prior = f.app._read(self.anchor)
        f.port.save_due(self.anchor, replace(prior, stop_state="active", completion_state="none",
            in_flight_request="current-manager").to_dict(), request_id="fixture-manager-active", expected_version=prior.version)
        calls = len(f.provider.calls)
        pending = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(pending["outcome"], "pending")
        self.assertFalse(pending["provider_called"])
        self.assertFalse(pending["effects_started"])
        self.assertEqual(len(f.provider.calls), calls)
        live = f.app._read(self.anchor)
        f.port.save_due(self.anchor, prior.to_dict(), request_id="fixture-manager-settled", expected_version=live.version)
        result = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=False)
        self.assertEqual(result["outcome"], "committed", result)

    def test_unknown_manager_blocks_even_an_existing_unattempted_worker_result_callback(self):
        f = self.fixture
        worker = f.app.assign_and_start(**f.request())
        prepared = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=False)
        callback = f.port.read_due(prepared["schedule_id"])
        prior = f.app._read(self.anchor)
        f.port.save_due(self.anchor, replace(prior, completion_state="unknown").to_dict(),
            request_id="fixture-current-manager-unknown", expected_version=prior.version)
        calls = len(f.provider.calls)
        held = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(held["outcome"], "held")
        self.assertFalse(held["provider_called"])
        self.assertFalse(held["retry"])
        self.assertEqual(f.port.read_due(prepared["schedule_id"]), callback)
        self.assertEqual(len(f.provider.calls), calls)

    def test_worker_result_consumes_existing_unattempted_report_callback_without_stranding_it(self):
        f = self.fixture
        report_callback = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)["continuation"]["schedule_id"]
        before = f.port.read_due(report_callback)
        reports = self.reports()
        worker = f.app.assign_and_start(**f.request())
        calls = len(f.provider.calls)
        prepared = f.app.continue_manager_from_worker(manager_schedule_id=report_callback,
            worker_schedule_id=worker["schedule_id"], execute=False)
        self.assertEqual(prepared["schedule_id"], report_callback)
        enriched = f.port.read_due(report_callback)
        self.assertEqual(enriched["in_flight_request"], before["in_flight_request"])
        self.assertTrue(enriched["message"].startswith(before["message"]))
        self.assertEqual(self.reports(), reports)
        self.assertIsNone((enriched.get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(f.app.continue_manager_from_worker(manager_schedule_id=report_callback,
            worker_schedule_id=worker["schedule_id"], execute=True)["outcome"], "succeeded")
        f.compose()
        # Even an old settled anchor finds the same delivered owner receipt.
        repeated = f.app.continue_manager_from_worker(manager_schedule_id=self.anchor,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(repeated["outcome"], "replayed")
        self.assertEqual(repeated["schedule_id"], report_callback)
        self.assertEqual(len(f.provider.calls), calls + 1)

    def test_completed_task_refresh_never_changes_attempted_callbacks_or_nonmanager_roles(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        due = f.app._read(prepared["continuation"]["schedule_id"])
        assignment = f.app._current(due.assignment_ref, due.generation)
        for retained in (replace(due, role="worker"), replace(due, role="project_advisor"),
                         replace(due, host_evidence={**(due.host_evidence or {}),
                                 "gateway_attempt": {"state": "attempt", "process_created": False}})):
            with patch("otto.portfolio.execution.task_reader") as reader:
                self.assertEqual(f.app._manager_task_reference(retained, assignment), retained)
                reader.assert_not_called()
        self.assertEqual(f.app._read(due.schedule_id), due)

    def test_changed_uncompleted_task_requires_owner_action_without_new_mandate_or_provider(self):
        f = self.fixture
        prepared = manager_continuation_from_command(
            request={"report_key": self.key, "operation": "prepare"}, execution=f.app,
            anchor_schedule_id=self.anchor, current_schedule_id=self.anchor,
            task_refs={"PA02": f.task.ref.to_dict()}, native_session_id="manager-session",
            read_reports=self.reports, preserve_execution_binding=True)
        schedule = prepared["continuation"]["schedule_id"]
        before = f.port.read_due(schedule)
        f.owner.graph.set_lifecycle(f.task.ref, Lifecycle.ACTIVE,
            logical_request_key="changed-uncompleted-task", actor=f.actor)
        with patch.object(f.app.portfolio, "create_document", wraps=f.app.portfolio.create_document) as create:
            held = f.app.start(schedule_id=schedule)
        self.assertEqual(held["outcome"], "partial", held)
        self.assertIn("committed completion", held["error"]["message"])
        create.assert_not_called()
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(len(f.provider.calls), self.provider_calls)


if __name__ == "__main__":
    unittest.main()

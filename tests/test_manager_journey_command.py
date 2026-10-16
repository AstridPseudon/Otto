"""Ordinary explicit judgment uses real assessment/completion/lifecycle APIs."""
import unittest
import argparse
import json
import hashlib

from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.kernel.limits import LimitService
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from tests import test_local_assessment_composition as local


class ManagerJourneyCommandTests(unittest.TestCase):
    def setUp(self):
        self.fixture = local.LocalAssessmentCompositionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.application = self.fixture.f
        self.commands = ManagerJourneyCommands(owner=self.application.owner, portfolio=self.application.app.portfolio,
                                               state=self.fixture.state)

    def source(self, alias):
        document = ContentDocument(ResourceRef(self.application.actor.authority, "dat.content.document", "source-" + alias),
            role="SOURCE", visibility="shared", access_mode="read", maintainer="manager", authoring_scope=self.application.project.ref)
        revision = ContentRevision(document.ref, "rev-1", {"verified": alias}, self.application.actor, initial=True)
        envelope = self.application.owner.content.build_create_document(
            TransactionContext(self.application.actor, "source-" + alias, "a" * 64), document, revision)
        self.application.owner.content.execute(envelope)
        return revision.ref.to_dict()

    def request(self, alias="PA01", candidate=None, verdict="PASS", key="ordinary-review"):
        criterion = "C01" if alias == "PA01" else "C09"
        candidate = candidate or self.source(alias)
        return {"command": "review-task", "task": alias, "request_key": key,
                "candidate_ref": candidate, "source_refs": [candidate],
                "inspection": {"observed": "Inspected the exact retained source and its focused verification"},
                "judgments": {criterion: {"verdict": verdict,
                    "rationale": "The retained evidence satisfies the declared criterion" if verdict == "PASS" else "The retained check is incomplete",
                    "evidence_refs": [candidate]}}}

    def test_review_input_exposes_exact_occurrence_and_complete_judgment_schema(self):
        from otto.portfolio.occurrence_reads import exact_due, handle
        from otto.portfolio.manager_journey_client import command_result_summary
        f=self.application
        worker=f.app.assign_and_start(**f.request())
        self.assertEqual(worker['outcome'],'succeeded')
        due=f.port.read_due(worker['schedule_id'])
        self.fixture.state['workers']={'PA01':{'schedule_id':worker['schedule_id'],
            'assignment_ref':due['assignment_ref'],'generation':due['generation'],'principal':due['recipient']}}
        self.commands.due_port=f.port
        read=self.commands.review_input('PA01')
        self.assertEqual(read['occurrence'],handle(due))
        self.assertIn('parent',read['occurrence'])
        self.assertEqual(command_result_summary(read)['occurrence'],handle(due))
        self.assertEqual(exact_due(f.port,read['occurrence']),due)
        self.assertEqual(read['judgment_schema']['verdict_enum'],['PASS','REWORK','UNKNOWN'])
        for change in ({'parent':'foreign'}, {'generation':2}, {'principal':'worker'}):
            with self.subTest(change=change),self.assertRaises((ValueError,PermissionError)):
                exact_due(f.port,{**read['occurrence'],**change})
        missing=dict(read['occurrence']);missing.pop('parent')
        with self.assertRaises(ValueError):exact_due(f.port,missing)

    def test_explicit_judgment_schema_refuses_before_journal_or_assessment_effect(self):
        from unittest.mock import patch
        from otto.portfolio.manager_journey_command import ReviewInputSchemaError
        for changes in ({'verdict':'ACCEPT'},{'rationale':'inspection/path'}, {'rationale':'inspection\\path'}, {'rationale':'bad\x00id'}):
            with self.subTest(changes=changes):
                request=self.request(key='schema-refusal')
                request['judgments']['C01'].update(changes)
                before=self.application.store.consumer().snapshot_counts()
                with patch.object(self.commands,'_journal',wraps=self.commands._journal) as journal, patch.object(type(self.application.owner),'create_manager_assessment_pool') as pool:
                    with self.assertRaises(ReviewInputSchemaError) as error:self.commands.review_task(request)
                    self.assertFalse(error.exception.refusal['effects_started'])
                    self.assertEqual(error.exception.refusal['error']['code'],'review_input_schema')
                    self.assertFalse(any(len(call.args)>2 for call in journal.call_args_list))
                    pool.assert_not_called()
                self.assertEqual(before,self.application.store.consumer().snapshot_counts())
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        service=SimpleNamespace(commands=self.commands)
        invalid=self.request(key='service-explicit-schema-refusal')
        invalid['judgments']['C01']['verdict']='ACCEPT'
        before=self.application.store.consumer().snapshot_counts()
        refusal=ManagerJourneyService.__call__(service,invalid)
        self.assertEqual(refusal['outcome'],'rejected')
        self.assertFalse(refusal['effects_started'])
        self.assertEqual(before,self.application.store.consumer().snapshot_counts())
        corrected=self.request(key='corrected-schema')
        self.assertEqual(self.commands.review_task(corrected)['outcome'],'accepted')
        self.assertEqual(self.application.provider.calls,[])

    def test_author_tasks_accepts_current_work_task_scope_and_keeps_project_scope_fence(self):
        f = self.application
        task = ResourceRef.from_dict(self.fixture.state["task_refs"]["PA01"])

        def report_for(scope, suffix):
            assignment = f.owner.assignments.command_port.assign(scope, role="executor", principal="worker",
                manager=self.fixture.state["manager"], session="authoring-" + suffix, pins=[],
                logical_request_key="authoring-assignment-" + suffix, actor=f.actor)
            report = f.owner.assignments.command_port.append_report(assignment.ref,
                {"schema": "fixture.authoring-review.v1", "suffix": suffix},
                expected_generation=assignment.generation, logical_request_key="authoring-report-" + suffix,
                actor=f.actor)
            return report

        def request(report, suffix):
            return {"command": "author-tasks", "request_key": "author-task-plan-" + suffix,
                "base_revision": self.fixture.state["project_ref"]["revision"], "review_ref": report.ref.to_dict(),
                "dispositions": [{"finding_id": "finding-" + suffix, "decision": "defer",
                    "reason": "Keep this evidence for the next review", "revisit": "After the exact owner check"}],
                "tasks": []}

        task_scoped = report_for(task, "current-task")
        authored = self.commands.author_tasks(request(task_scoped, "current-task"))
        self.assertEqual(authored["outcome"], "authored", authored)
        self.assertFalse(authored["provider_called"])
        self.assertFalse(authored["dispatch"])

        # Existing same-project project-scope evidence remains a supported
        # authoring input; the namespace repair does not narrow that route.
        project_report = report_for(f.project.ref, "same-project")
        self.assertEqual(self.commands.author_tasks(request(project_report, "same-project"))["outcome"], "authored")

        other = f.owner.graph.create_project(title="Foreign project", logical_request_key="authoring-foreign-project")
        foreign_task = f.owner.graph.create_task(other.ref, title="Foreign task", logical_request_key="authoring-foreign-task")
        foreign_report = report_for(foreign_task.ref, "foreign-task")
        with self.assertRaisesRegex(PermissionError, "another project"):
            self.commands.author_tasks(request(foreign_report, "foreign-task"))

        missing_ref = ResourceRef(task.authority, "work.task", "missing-authoring-task", "rev-1")
        missing_report = report_for(missing_ref, "missing-task")
        with self.assertRaisesRegex(PermissionError, "missing or stale"):
            self.commands.author_tasks(request(missing_report, "missing-task"))

        stale_report = report_for(task, "stale-task")
        f.owner.graph.revise(task, title="Changed task head", base_revision=task.revision,
            logical_request_key="authoring-stale-task", actor=f.actor)
        with self.assertRaisesRegex(PermissionError, "missing or stale"):
            self.commands.author_tasks(request(stale_report, "stale-task"))

    def test_one_operation_accepts_source_and_completes_replay_without_provider(self):
        request = self.request()
        first = self.commands.review_task(request)
        self.assertEqual(first["outcome"], "accepted")
        self.assertEqual(first["completion"]["outcome"], "completed", first)
        self.assertEqual(self.commands.review_task(request)["completion"]["outcome"], "replayed")
        self.assertEqual(self.application.provider.calls, [])
        pool = LimitService(self.application.store).get_pool(ResourceRef(self.application.actor.authority, "limit", "local-inspection"))
        self.assertEqual(pool.cumulative_used_units, 1)
        with self.assertRaises(ValueError):
            self.commands.review_task({**request, "inspection": {"different": True}})

    def test_project_view_retains_committed_acceptance_independently_of_native_result(self):
        from herzchen.kernel import ProjectHistoryGrant
        from otto.portfolio.observability_views import ObservabilityViews
        store=self.application.store;store.configure_history_projection(batch_size=1000).maintain(limit=1000)
        request=self.request(key='view-completion');result=self.commands.review_task(request)
        grant=ProjectHistoryGrant(self.application.actor,(self.application.project.id,),'fixture','completion-view')
        views=ObservabilityViews(store.project_history_reader(grant=grant))
        page=views.read('tasks-reviews',projects=[self.application.project.ref.to_dict()],
            filters={'facet_type':'lifecycle_transition'},limit=50)
        row=next(row for row in page['rows']if row['subject_ref']==result['completion']['task_ref'])
        self.assertEqual(row['semantic']['task_acceptance']['value']['candidate_ref'],request['candidate_ref'])
        self.assertEqual(row['semantic']['native_result']['state'],'unknown')
        self.assertEqual(self.application.provider.calls,[])

    def test_review_reuses_precreated_bound_pool_from_a_different_setup_key(self):
        policy = self.fixture.state["assessment_policy"]
        LimitService(self.application.store).create_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"),
            capacity_units=policy["capacity_units"],
            cumulative_allowance_units=policy["cumulative_allowance_units"],
            logical_request_key="controller-local-pool-setup", actor=self.application.actor)
        result = self.commands.review_task(self.request(key="precreated-pool-review"))
        self.assertEqual(result["outcome"], "accepted", result)
        self.assertEqual(result["completion"]["outcome"], "completed", result)
        pool = LimitService(self.application.store).get_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"))
        self.assertEqual(pool.cumulative_used_units, 1)

    def test_completed_finish_replays_exact_receipt_then_settles_later_task(self):
        first = self.commands.review_task(self.request(key="first-review"))
        self.fixture.state["task_refs"]["PA01"] = first["completion"]["task_ref"]
        second = self.commands.review_task({**self.request(alias="PA06", key="second-review"), "finish": False})
        self.assertEqual(second["outcome"], "accepted")
        finish = {"command": "finish-task", "task": "PA06", "request_key": "second-finish", "review_key": "second-review"}
        self.commands._journal(finish["request_key"], "finish-intent", finish)
        limits = LimitService(self.application.store)
        poolref = ResourceRef(self.application.actor.authority, "limit", "local-inspection")
        before = limits.get_pool(poolref)
        settled = self.commands.settle_completion_intents()
        by_key = {r["request_key"]: r["result"] for r in settled}
        self.assertEqual(by_key["first-review:finish"]["outcome"], "replayed")
        self.assertEqual(by_key["second-finish"]["outcome"], "completed")
        self.assertEqual(by_key["first-review:finish"]["task_ref"], first["completion"]["task_ref"])
        self.assertEqual(limits.get_pool(poolref), before)
        self.assertEqual(self.application.provider.calls, [])

    def test_completed_finish_rejects_changed_task_key_and_generation_without_effects(self):
        reviewed = self.commands.review_task(self.request(key="completed-review"))
        state = self.fixture.state
        state["task_refs"]["PA01"] = reviewed["completion"]["task_ref"]
        finish = self.commands._journal("completed-review:finish", "finish-intent")
        before = self.application.owner.graph.reader.snapshot_counts()
        with self.assertRaises(PermissionError):
            self.commands.finish_task({**finish, "request_key": "different-finish"})
        state["task_refs"]["PA01"] = state["task_refs"]["PA06"]
        with self.assertRaises(PermissionError): self.commands.finish_task(finish)
        state["task_refs"]["PA01"] = reviewed["completion"]["task_ref"]
        state["manager_generation"] += 1
        with self.assertRaises(PermissionError): self.commands.finish_task(finish)
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(), before)
        state["manager_generation"] -= 1
        state["task_refs"]["PA01"] = {**reviewed["completion"]["task_ref"], "revision": "rev-999"}
        before = self.application.owner.graph.reader.snapshot_counts()
        with self.assertRaises(PermissionError): self.commands.finish_task(finish)
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.application.provider.calls, [])

    def test_retained_help_reports_are_hashed_without_reauthoring_or_extra_charge(self):
        f = self.application
        assignment = self.fixture.manager
        reply = f.owner.assignments.command_port.append_report(assignment.ref,
            {"schema": "otto.issue.response.v1", "solution": "Observed actual help resolution"},
            expected_generation=assignment.generation, logical_request_key="retained-help-reply", actor=f.actor)
        application = f.owner.assignments.command_port.append_report(assignment.ref,
            {"schema": "otto.issue.application.v1", "response_ref": reply.ref.to_dict(), "state": "resolved"},
            expected_generation=assignment.generation, logical_request_key="retained-help-application", actor=f.actor)
        request = self.request(candidate=self.source("connected-evidence"), key="report-evidence-review")
        request["finish"] = False
        reports = [reply.ref.to_dict(), application.ref.to_dict()]
        request["source_refs"].extend(reports)
        request["judgments"]["C01"]["evidence_refs"].extend(reports)
        old_reports = [f.owner.graph.reader.get_identity(record.ref) for record in (reply, application)]
        # An unretained report revision still fails before review/pool effects.
        stale = {**request, "request_key": "stale-report-evidence",
            "judgments": {"C01": {**request["judgments"]["C01"], "evidence_refs": [
                request["candidate_ref"], {**reports[0], "revision": "rev-999"}]}}}
        before = f.owner.graph.reader.snapshot_counts()
        with self.assertRaises(ValueError): self.commands.review_task(stale)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), before)
        accepted = self.commands.review_task(request)
        self.assertEqual(accepted["outcome"], "accepted")
        self.assertFalse(accepted["task_completion_recorded"])
        for record in (reply, application):
            expected = hashlib.sha256(json.dumps(record.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(accepted["evidence_hashes"][record.ref.kind + ":" + record.ref.id + ":" + record.ref.revision], expected)
        before = f.owner.graph.reader.snapshot_counts()
        self.assertEqual(self.commands.review_task(request), accepted)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual([f.owner.graph.reader.get_identity(record.ref) for record in (reply, application)], old_reports)
        pool = LimitService(f.store).get_pool(ResourceRef(f.actor.authority, "limit", "local-inspection"))
        self.assertEqual(pool.cumulative_used_units, 1)
        self.assertEqual(f.provider.calls, [])

    def test_existing_bound_pool_with_different_limits_is_rejected(self):
        policy = self.fixture.state["assessment_policy"]
        LimitService(self.application.store).create_pool(
            ResourceRef(self.application.actor.authority, "limit", "local-inspection"),
            capacity_units=policy["capacity_units"],
            cumulative_allowance_units=policy["cumulative_allowance_units"] + 1,
            logical_request_key="controller-wrong-pool-setup", actor=self.application.actor)
        with self.assertRaises(PermissionError):
            self.commands.review_task(self.request(key="wrong-pool-review"))

    def test_accepted_review_finishes_after_same_generation_resource_adoption_without_reassessment(self):
        request = {**self.request(key="accepted-before-adoption"), "finish": False}
        accepted = self.commands.review_task(request)
        self.assertEqual(accepted["outcome"], "accepted")
        f = self.application; manager = self.fixture.manager
        content = {"schema": "herzchen.instructions.v1", "name": "updated-manager-guide",
            "entrypoint": "MANAGER.md", "instructions": "Use the newly adopted installed command",
            "bundle_digest": hashlib.sha256(b"Use the newly adopted installed command").hexdigest(),
            "export_manifest_digest": "new-selected-pack", "required": True, "supporting_refs": []}
        made = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="updated-manager-guide", document_id=content["name"], content=content)
        ref = made["record"]["payload"]["current_revision"]
        adopted = f.owner.assignments.command_port.adopt_resources(manager.ref,
            resources=[{"resource_ref": ref, "resource_name": content["name"],
                "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=manager.revision, expected_generation=manager.generation,
            logical_request_key="adopt-corrected-guide", actor=f.actor)
        self.fixture.state["assignment_ref"] = adopted.ref.to_dict()
        limits = LimitService(f.store); poolref = ResourceRef(f.actor.authority, "limit", "local-inspection")
        before = limits.get_pool(poolref)
        result = self.commands.finish_task({"command": "finish-task", "task": "PA01",
            "request_key": "finish-retained-accepted", "review_key": request["request_key"]})
        self.assertEqual(result["outcome"], "completed", result)
        self.assertEqual(limits.get_pool(poolref), before)
        retained = self.commands._journal(request["request_key"], "review", adopted_history=True)
        self.assertEqual(retained["gate_refs"], accepted["gate_refs"])
        self.assertEqual(retained["candidate_ref"], accepted["candidate_ref"])
        self.assertEqual(f.provider.calls, [])
        reassigned = f.owner.assignments.command_port.reassign(adopted.ref,
            principal="manager", reason="new generation", expected_generation=adopted.generation,
            logical_request_key="reassigned-after-accepted", actor=f.actor)
        self.fixture.state.update(assignment_ref=reassigned.ref.to_dict(), manager_generation=reassigned.generation)
        self.assertIsNone(self.commands._journal(request["request_key"], "review", adopted_history=True))
        with self.assertRaisesRegex(ValueError, "retained explicit accepted"):
            self.commands.finish_task({"task": "PA01", "request_key": "foreign-generation-finish", "review_key": request["request_key"]})
        foreign = f.owner.assignments.command_port.reassign(reassigned.ref,
            principal="another-manager", reason="another manager", expected_generation=reassigned.generation,
            logical_request_key="foreign-manager-after-accepted", actor=f.actor)
        self.fixture.state.update(assignment_ref=foreign.ref.to_dict(), manager_generation=foreign.generation, manager="another-manager")
        self.assertIsNone(self.commands._journal(request["request_key"], "review", adopted_history=True))
        self.assertEqual(limits.get_pool(poolref), before)

    def test_rework_never_accepts_and_repaired_evidence_uses_same_required_scope(self):
        request = self.request(verdict="REWORK")
        rejected = self.commands.review_task(request)
        self.assertEqual(rejected["outcome"], "rework")
        self.assertEqual(rejected["gate_refs"], [])
        current = self.application.owner.graph.reader.get_identity(self.application.task.ref)
        self.assertEqual(current.payload["lifecycle"], "pending")
        repaired = self.request(candidate=request["candidate_ref"], key="repaired-review")
        result = self.commands.review_task(repaired)
        self.assertEqual(result["completion"]["outcome"], "completed", result)

    def test_unknown_missing_criteria_foreign_actor_and_stale_source_do_not_autoaccept(self):
        request = self.request(verdict="UNKNOWN")
        self.assertEqual(self.commands.review_task(request)["outcome"], "unknown")
        with self.assertRaises(ValueError):
            self.commands.review_task({**request, "request_key": "missing-criteria", "judgments": {}})
        stale = {**request["candidate_ref"], "revision": "rev-999"}
        with self.assertRaises(ValueError):
            self.commands.review_task(self.request(candidate=stale, key="stale-source"))
        self.fixture.state["manager"] = "foreign-manager"
        with self.assertRaises(PermissionError):
            self.commands.review_task(request)

    def test_project_finish_holds_unfinished_tasks_then_records_terminal_and_pending_settlement(self):
        request = {"command": "finish-project", "request_key": "project-finish",
            "dispositions": {name: {"status": "qualified", "rationale": "Isolated local journey; no publication or remote effects required"}
                             for name in ("acceptance", "publication", "remote", "runtime")}}
        observer = lambda project: {"mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
            "coverage": {"project_id": project, "fixture": "all fixture Due records inspected"}, "shared_records": []}
        call = lambda: self.commands.finish_project(request, orchestrator_principal="orchestrator", observe_schedules=observer)
        self.assertEqual(call()["outcome"], "held")
        for alias in ("PA01", "PA06"):
            result = self.commands.review_task(self.request(alias=alias, key="review-" + alias))
            self.assertEqual(result["completion"]["outcome"], "completed", result)
        observer = lambda project: {"unknown_ownership": True}
        pending = call()
        self.assertEqual(pending["outcome"], "pending", pending)
        self.assertTrue(pending["project_completion_recorded"])
        self.assertTrue(pending["settlement_pending"])
        observer = lambda project: {"mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
            "coverage": {"project_id": project}, "shared_records": []}
        terminal = call()
        self.assertEqual(terminal["outcome"], "completed", terminal)
        self.assertEqual(terminal["readback"]["lifecycle"], "completed")
        self.assertFalse(terminal["settlement_pending"])
        self.assertEqual(call()["outcome"], "completed")

    def close_request(self, key="withdrawn-project-close"):
        return {"command": "finish-project", "request_key": key, "dispositions": {
            name: {"status": "qualified", "rationale": "Verified local fixture obligations; no external effects"}
            for name in ("acceptance", "publication", "remote", "runtime")}}

    def close(self, key="withdrawn-project-close"):
        return self.commands.finish_project(self.close_request(key), orchestrator_principal="orchestrator",
            observe_schedules=lambda project: {"mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project_id": project}, "shared_records": []})

    def complete_required(self):
        for alias in ("PA01", "PA06"):
            self.commands.review_task(self.request(alias=alias, key="required-" + alias))

    def planning_task(self, withdraw=True):
        graph=self.application.owner.graph
        task=graph.create_task(self.application.project.ref, title="Unused duplicate planning record",
            logical_request_key="extra-plan")
        self.fixture.state["task_refs"]["EXTRA"] = task.ref.to_dict()
        if withdraw:
            task=graph.withdraw(task.ref, logical_request_key="withdraw-extra")
            self.fixture.state["task_refs"]["EXTRA"] = task.ref.to_dict()
        return task

    def test_project_close_preserves_unused_withdrawn_history_without_accepting_it(self):
        planning=self.planning_task();self.complete_required()
        self.assertEqual(self.close()["outcome"], "completed")
        intent=self.commands._journal("withdrawn-project-close", "project-intent")
        self.assertEqual(intent["withdrawn_unused_planning_refs"], [planning.ref.to_dict()])
        self.assertNotIn(planning.id, [ref['id'] for ref in intent['task_refs']])
        retained=self.application.owner.graph.current(planning.ref)
        self.assertEqual(retained.lifecycle.value, "withdrawn");self.assertNotIn("completion",retained.payload)
        self.assertEqual(self.application.provider.calls, [])

    def test_pending_extra_and_unjudged_original_tasks_still_hold_project(self):
        planning=self.planning_task(withdraw=False);self.complete_required()
        self.assertEqual(self.close()["outcome"], "held")
        planning=self.application.owner.graph.withdraw(planning.ref,logical_request_key="withdraw-after-hold")
        self.fixture.state["task_refs"]["EXTRA"]=planning.ref.to_dict()
        self.assertEqual(self.close()["outcome"], "completed")

    def test_required_withdrawn_task_cannot_be_omitted(self):
        task=self.application.owner.graph.withdraw(ResourceRef.from_dict(self.fixture.state['task_refs']['PA01']),
            logical_request_key='withdraw-required')
        self.fixture.state['task_refs']['PA01']=task.ref.to_dict()
        self.assertEqual(self.close()["outcome"], "held")
        self.assertFalse(self.close()['project_completion_recorded'])

    def test_used_stale_and_foreign_withdrawn_planning_pins_hold_without_effects(self):
        planning=self.planning_task();self.complete_required()
        valid=planning.ref.to_dict()
        for pin in ({**valid,'revision':'rev-1'},{**valid,'authority':'foreign'}):
            self.fixture.state['task_refs']['EXTRA']=pin
            before=self.application.owner.graph.reader.snapshot_counts()
            self.assertEqual(self.close()['outcome'],'held')
            self.assertEqual(self.application.owner.graph.reader.snapshot_counts(),before)
        self.fixture.state['task_refs']['EXTRA']=valid
        self.application.owner.assignments.assign(planning.ref,role='worker',principal='unused-is-now-used',
            logical_request_key='used-plan')
        before=self.application.owner.graph.reader.snapshot_counts()
        self.assertEqual(self.close()['outcome'],'held')
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(),before)

    def test_project_scoped_executor_makes_withdrawn_planning_use_ambiguous(self):
        planning=self.planning_task();self.complete_required()
        self.application.owner.assignments.assign(self.application.project.ref,role='executor',principal='project-executor',
            pins=[planning.ref],logical_request_key='project-executor')
        before=self.application.owner.graph.reader.snapshot_counts()
        self.assertEqual(self.close()['outcome'],'held')
        self.assertEqual(self.application.owner.graph.reader.snapshot_counts(),before)

    def test_client_definitions_request_judgment_without_owner_pins_or_pool_fields(self):
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest="command", required=True))
        candidate = self.source('parser-candidate')
        source = self.source('parser-source')
        request = vars(parser.parse_args(["review-task", "--task", "J01", "--request-key", "review",
            "--candidate-ref", json.dumps(candidate), "--source-ref", json.dumps(source),
            "--judgments", '{"C01":{"verdict":"PASS"}}', "--inspection", '{"observed":"check"}',
            "--review-only"]))
        self.assertFalse(request["finish"])
        self.assertEqual(request["source_refs"], [source])
        self.assertFalse(any(name in request for name in ("actor", "pool", "expected_task_ref")))

    def test_current_reassigned_manager_can_review_and_close_with_distinct_orchestrator_epoch(self):
        assignment = self.application.owner.assignments.command_port.reassign(self.fixture.manager.ref,
            principal="manager", reason="same-manager native recovery", expected_generation=1,
            logical_request_key="current-manager", actor=self.application.actor)
        self.fixture.state.update(assignment_ref=assignment.ref.to_dict(), manager_generation=assignment.generation)
        for alias in ("PA01", "PA06"):
            result = self.commands.review_task(self.request(alias=alias, key="reassigned-" + alias))
            self.assertEqual(result["completion"]["outcome"], "completed", result)
        result = self.commands.finish_project({"request_key": "reassigned-project",
            "dispositions": {name: {"status": "qualified", "rationale": "Local fixture only; no external obligations"}
                             for name in ("acceptance", "publication", "remote", "runtime")}},
            orchestrator_principal="orchestrator", observe_schedules=lambda project: {
                "mode": "no-owned-schedule", "pm_owned_schedule_ids": [],
                "coverage": {"project": project}, "shared_records": []})
        self.assertEqual(result["outcome"], "completed", result)
        project = self.application.owner.graph.reader.get_identity(ResourceRef(self.application.project.ref.authority, "work.project", self.application.project.ref.id))
        attribution = project.payload["lifecycle_control"]["owner_attribution"]
        self.assertEqual(attribution["manager"]["generation"], 2)
        self.assertEqual(attribution["orchestrator"]["generation"], 1)

    def test_native_completion_intent_waits_for_exact_settlement_without_provider_retry(self):
        prepared = self.application.app.assign_worker(**self.application.request())
        self.application.app.start(schedule_id=prepared["schedule_id"], settle=False)
        candidate = self.application.app.assignments.list_observations(
            ResourceRef.from_dict(prepared["assignment_ref"]), kind="result")[0].ref.to_dict()
        request = self.request(candidate=candidate)
        self.commands.due_port = self.application.port
        reviewed = self.commands.review_task(request)
        self.assertEqual(reviewed["completion"]["outcome"], "pending", reviewed)
        self.assertEqual(self.application.owner.graph.current(self.application.task.ref).lifecycle.value, "pending")
        calls = len(self.application.provider.calls)
        self.commands.settle_execution = lambda due: self.application.app.recover(schedule_id=due["schedule_id"], execute=False)
        completed = self.commands.review_task(request)
        self.assertEqual(completed["completion"]["outcome"], "completed", completed)
        self.assertEqual(len(self.application.provider.calls), calls)
        self.assertEqual(self.application.port.read_due(prepared["schedule_id"])["completion_state"], "succeeded")


if __name__ == "__main__":
    unittest.main()

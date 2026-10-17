"""Focused S01 checks over the existing disposable owner/provider fixture.

Run: PYTHONPATH=src:. python3 -m unittest discover -s src/otto/portfolio/tests
Provider substitutions exercise admission; the installed live journey is S06.
"""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import unittest

from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule
from herzchen.kernel.limits import LimitService
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.operating_setup import OperatingSetupError, evaluate_setup, normalize_setup
from otto.portfolio.manager_journey_service import ManagerJourneyService
from tests import test_execution_application as owner_fixture
from tests import test_manager_journey_command as journey_fixture
from tests import test_manager_service_continuation as continuation_fixture


class OperatingSetupTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def role(self, role):
        f = self.f
        assigned, guide, mandate = f.role_handles(role, role if role != "project_advisor" else "advisor", role + "-session")
        prepared = f.app.prepare_role(role=role, project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=assigned.ref.to_dict(), generation=assigned.generation, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key="setup-" + role, instruction="Advance useful project",
            model="gpt-test", reasoning="high", profile="workspace-write" if role == "manager" else "read-only",
            native_session_id=role + "-session")
        self.assertEqual(prepared["outcome"], "committed", prepared)
        return assigned, prepared["schedule_id"]

    def manual(self):
        _manager, schedule = self.role("manager")
        return {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": {"manager": schedule},
                "advisor_policy": {"mode": "disabled", "reason": "Owner supervises this bounded run"}, "acceptance_tasks": []}

    def test_unstarted_continuation_uses_completed_fresh_manager_admission(self):
        from copy import deepcopy
        from otto.portfolio.execution import _digest
        self.test_pending_callback_keeps_settled_native_proof_for_worker_result()
        f = self.f
        current = next(v for v in f.port.list_due() if v["role"] == "manager"
            and v["schedule_id"] != "owner-bootstrap-native" and v["completion_state"] == "succeeded")
        proof = deepcopy(f.port.read_due("owner-bootstrap-native"))
        proof["target"].pop("native_id")
        proof["execution_mode"] = "fresh_manager"
        proof["host_evidence"]["gateway_attempt"]["result"].update(
            outcome="succeeded", context_digest_verified=True, physical_session_id="actual-manager-session")
        pending = deepcopy(current)
        pending.update(host_evidence=None, stop_state="active", completion_state="none",
            in_flight_request="fixture-pending")
        config = {"schema":"otto.operating-setup.v1", "mode":"manual",
            "roles":{"manager":pending["schedule_id"]},
            "advisor_policy":{"mode":"disabled","reason":"Fixture owner"}, "acceptance_tasks":[]}
        original = f.app.runtime.due_port
        def ready(candidate):
            raw = deepcopy(pending)
            raw["target"]["native_binding"] = {"schedule_id":candidate["schedule_id"], "due_sha256":_digest(candidate)}
            f.app.runtime.due_port = SimpleNamespace(read_due=lambda schedule:
                raw if schedule == raw["schedule_id"] else candidate if schedule == candidate["schedule_id"] else original.read_due(schedule))
            self.last_fresh_readiness = evaluate_setup(f.app.runtime,f.project.ref.to_dict(),config)
            return self.last_fresh_readiness["ready"]
        try:
            self.assertTrue(ready(proof), self.last_fresh_readiness["blockers"])
            changes = [(("execution_mode",),"continue_existing"), (("completion_state",),"unknown"),
                (("stop_state",),"active"), (("generation",),2),
                (("target","project_ref","id"),"foreign-project"),
                (("host_evidence","gateway_attempt","result","context_digest_verified"),False),
                (("host_evidence","gateway_attempt","result","physical_session_id"),"foreign-session"),
                (("host_evidence","gateway_attempt","delivery_admission","native_turn_started"),False),
                (("host_evidence","gateway_attempt","delivery_authorization","status"),"unverified"),
                (("host_evidence","gateway_attempt","delivery_authorization","principal"),"foreign")]
            for path,value in changes:
                bad=deepcopy(proof); target=bad
                for key in path[:-1]:target=target[key]
                target[path[-1]]=value
                with self.subTest(path=path):self.assertFalse(ready(bad))
        finally:f.app.runtime.due_port=original

    def test_settled_callback_uses_own_admission_after_fresh_initial_target(self):
        from copy import deepcopy
        from otto.portfolio.execution import _digest
        self.test_pending_callback_keeps_settled_native_proof_for_worker_result()
        f = self.f
        records = f.port.list_due()
        current = next(v for v in records if v["role"] == "manager"
            and v["schedule_id"] != "owner-bootstrap-native"
            and v["completion_state"] == "succeeded")
        proof = deepcopy(f.port.read_due("owner-bootstrap-native"))
        proof["target"]["native_id"] = None  # genuine fresh-manager target shape
        raw = deepcopy(current)
        raw["target"]["native_binding"] = {"schedule_id":proof["schedule_id"], "due_sha256":_digest(proof)}
        config = {"schema":"otto.operating-setup.v1", "mode":"manual",
            "roles":{"manager":raw["schedule_id"]},
            "advisor_policy":{"mode":"disabled","reason":"Fixture owner"}, "acceptance_tasks":[]}
        original = f.app.runtime.due_port
        f.app.runtime.due_port = SimpleNamespace(read_due=lambda schedule:
            raw if schedule == raw["schedule_id"] else proof if schedule == proof["schedule_id"] else original.read_due(schedule))
        try:
            self.assertTrue(evaluate_setup(f.app.runtime,f.project.ref.to_dict(),config)["ready"])
            for field,value in (("generation",2),("principal","foreign"),("physical_session_id","foreign"),("status","unverified")):
                bad = deepcopy(current)
                bad["host_evidence"]["gateway_attempt"]["delivery_authorization"][field] = value
                f.app.runtime.due_port = SimpleNamespace(read_due=lambda schedule,bad=bad:
                    bad if schedule == bad["schedule_id"] else original.read_due(schedule))
                self.assertFalse(evaluate_setup(f.app.runtime,f.project.ref.to_dict(),config)["ready"],field)
        finally:f.app.runtime.due_port=original

    def test_pending_callback_keeps_settled_native_proof_for_worker_result(self):
        from otto.attention import DueRecord
        from otto.portfolio.execution import _digest
        from otto.portfolio.execution_operations import prepare_current_assignment_occurrence
        from herzchen.content.instructions import validate_instruction_content
        f = self.f
        manager, guide, mandate = f.role_handles("manager", "manager", None)
        at = f.app.clock().isoformat()
        target = {"host": "local", "native_id": "actual-manager-session", "role": "manager", "principal": "manager",
            "project_ref": f.project.ref.to_dict(), "task_ref": f.task.ref.to_dict(),
            "assignment_ref": manager.ref.to_dict(), "mandate_ref": mandate,
            "requested_model": "gpt-test", "requested_reasoning": "high", "requested_profile": "workspace-write"}
        # The owner bootstrap issues the initial exact native occurrence. Its
        # proof below comes from an actual authorized provider fixture turn.
        initial = DueRecord(schedule_id="owner-bootstrap-native", recipient="manager", instruction="Inspect project",
            profile="workspace-write", anchor=at, due_at=at, last_covered_slot=0, invocation_identity="bootstrap-native",
            in_flight_request="bootstrap-native", delivery_state="ready", owner="manager", project_ref=f.project.id,
            manager_ref="manager", assignment_ref=manager.ref.to_dict(), generation=manager.generation,
            target=target, role="manager", lifecycle_owner="manager", execution_mode="continue_existing",
            requested_model="gpt-test", requested_reasoning="high", context_refs=(guide, mandate), result_owner="manager", timeout_seconds=1200)
        prepare_current_assignment_occurrence(due_port=f.port, assignments=f.app.assignments,
            binding=f.binding, due=initial, assignment_ref=manager.ref.to_dict(), assignment_owner="manager",
            operation="resume", lifecycle="resume", request_key="owner-bootstrap-native")
        started = f.app.start(schedule_id=initial.schedule_id)
        self.assertEqual(started["outcome"], "succeeded", started)
        anchor = f.port.read_due(initial.schedule_id)
        self.assertIsNone(manager.session)
        from otto.portfolio.execution_operations import build_manager_callback_due
        callback = build_manager_callback_due(f.app._read(initial.schedule_id), schedule_id="pending-finish-callback",
            request_key="pending-finish", assignment_ref=manager.ref.to_dict(), guide_ref=guide,
            mandate_ref=mandate, due_at=at, timeout_seconds=1200)
        prepare_current_assignment_occurrence(due_port=f.port, assignments=f.app.assignments,
            binding=f.binding, due=callback, assignment_ref=manager.ref.to_dict(), assignment_owner="manager",
            operation="resume", lifecycle="callback", request_key="pending-finish")
        pending = f.port.read_due(callback.schedule_id)
        self.assertIsNone((pending.get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(pending["target"]["native_binding"], {"schedule_id": initial.schedule_id, "due_sha256": _digest(anchor)})
        f.app._verify_native_binding(manager, "actual-manager-session", callback.schedule_id)
        # A correct-looking session cannot authorize an inexact anchor, cycle,
        # foreign epoch/principal, or a second unattempted proof hop.
        original_read = f.app._read
        from unittest.mock import patch
        for pin in ({"schedule_id": initial.schedule_id, "due_sha256": "0" * 64},
                    {"schedule_id": callback.schedule_id, "due_sha256": _digest(pending)}):
            bad = replace(callback, target={**callback.target, "native_binding": pin})
            with patch.object(f.app, "_read", side_effect=lambda schedule, bad=bad: bad if schedule == callback.schedule_id else original_read(schedule)):
                with self.assertRaises(ValueError):
                    f.app._verify_native_binding(manager, "actual-manager-session", callback.schedule_id)
        for field, value in (("generation", 2), ("recipient", "foreign"), ("completion_state", "unknown")):
            forged = replace(original_read(initial.schedule_id), **{field: value})
            bad = replace(callback, target={**callback.target, "native_binding": {
                "schedule_id": initial.schedule_id, "due_sha256": _digest(forged.to_dict())}})
            with patch.object(f.app, "_read", side_effect=lambda schedule, bad=bad, forged=forged:
                              bad if schedule == callback.schedule_id else forged if schedule == initial.schedule_id else original_read(schedule)):
                with self.assertRaises(ValueError):
                    f.app._verify_native_binding(manager, "actual-manager-session", callback.schedule_id)
        worker = f.app.assign_and_start(**f.request())
        self.assertEqual(worker["outcome"], "succeeded", worker)
        delivered = f.app.continue_manager_from_worker(manager_schedule_id=callback.schedule_id,
            worker_schedule_id=worker["schedule_id"], execute=True)
        self.assertEqual(delivered["outcome"], "succeeded", delivered)
        self.assertEqual(delivered["schedule_id"], callback.schedule_id)
        count = len(f.provider.calls)
        self.assertEqual(count, 3)
        self.assertEqual(f.app.recover(schedule_id=callback.schedule_id, execute=True)["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), count)
        self.assertEqual(f.port.read_due(initial.schedule_id), anchor)

    def test_adopted_resource_continuation_retains_actual_native_binding_for_setup_and_admission(self):
        from otto.attention import DueRecord
        from otto.portfolio.execution import _digest
        from otto.portfolio.execution_operations import prepare_current_assignment_occurrence
        from herzchen.content.instructions import validate_instruction_content
        f = self.f
        manager, guide, mandate = f.role_handles("manager", "manager", None)
        at = f.app.clock().isoformat()
        target = {"host": "local", "native_id": "actual-manager-session", "role": "manager", "principal": "manager",
            "project_ref": f.project.ref.to_dict(), "task_ref": f.task.ref.to_dict(),
            "assignment_ref": manager.ref.to_dict(), "mandate_ref": mandate,
            "requested_model": "gpt-test", "requested_reasoning": "high", "requested_profile": "workspace-write"}
        # The owner bootstrap issues the initial exact native occurrence. Its
        # proof below comes from an actual authorized provider fixture turn.
        initial = DueRecord(schedule_id="owner-bootstrap-native", recipient="manager", instruction="Inspect project",
            profile="workspace-write", anchor=at, due_at=at, last_covered_slot=0, invocation_identity="bootstrap-native",
            in_flight_request="bootstrap-native", delivery_state="ready", owner="manager", project_ref=f.project.id,
            manager_ref="manager", assignment_ref=manager.ref.to_dict(), generation=manager.generation,
            target=target, role="manager", lifecycle_owner="manager", execution_mode="continue_existing",
            requested_model="gpt-test", requested_reasoning="high", context_refs=(guide, mandate), result_owner="manager", timeout_seconds=1200)
        prepare_current_assignment_occurrence(due_port=f.port, assignments=f.app.assignments,
            binding=f.binding, due=initial, assignment_ref=manager.ref.to_dict(), assignment_owner="manager",
            operation="resume", lifecycle="resume", request_key="owner-bootstrap-native")
        started = f.app.start(schedule_id=initial.schedule_id)
        self.assertEqual(started["outcome"], "succeeded", started)
        anchor = f.port.read_due(initial.schedule_id)
        self.assertIsNone(manager.session)
        old = f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        instructions = old["instructions"] + "\nRead the updated selected host command."
        updated = {**old, "name": "updated-selected-manager", "instructions": instructions,
            "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest()}
        made = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager", request_id="updated-native-guide",
            document_id="updated-native-guide", content=updated)
        new_guide = made["record"]["payload"]["current_revision"]
        adopted = f.app.assignments.adopt_resources(manager.ref, resources=[{"resource_ref": new_guide,
            "resource_name": updated["name"], "content_digest": validate_instruction_content(updated), "required": True}],
            expected_revision=manager.revision, expected_generation=manager.generation,
            logical_request_key="adopt-native-guide", actor=f.actor)
        # Several ordinary closed resource corrections retain one actual native
        # anchor; continuity requires every authenticated consecutive adoption.
        for index in range(2):
            adopted = f.app.assignments.adopt_resources(adopted.ref, resources=adopted.payload['resource_adoptions'],
                expected_revision=adopted.revision, expected_generation=adopted.generation,
                logical_request_key='adopt-native-guide-again-' + str(index), actor=f.actor)
        from otto.portfolio.operating_setup import authenticated_adoption_ancestor
        projection={'ref':adopted.ref.to_dict(),'generation':adopted.generation,'principal':adopted.principal,'role':adopted.role,'payload':adopted.payload}
        reader=f.app.portfolio.operations._owner_reader
        events=reader.list_events(stream='assignment:'+adopted.id)
        self.assertTrue(authenticated_adoption_ancestor(projection,manager.ref.to_dict(),reader))
        adoption_events=[e for e in events if e.event_type=='work.assignment.resources-adopted']
        middle=adoption_events[-2]
        from copy import deepcopy
        for field in ('missing','generation','foreign','actor','jump'):
            changed=deepcopy(middle.effects);body=changed['result_payload']
            if field=='generation':body['generation']=2
            if field=='foreign':body['scope']={**body['scope'],'id':'foreign-project'}
            if field=='jump':body['resource_adoption_base_ref']=manager.ref.to_dict()
            revised=replace(middle,effects=changed)
            if field=='actor':revised=replace(revised,actor=f.binding.authenticated_actor('foreign'))
            selected=[revised if e==middle else e for e in events if not(field=='missing' and e==middle)]
            with self.subTest(chain=field):
                self.assertFalse(authenticated_adoption_ancestor(projection,manager.ref.to_dict(),SimpleNamespace(list_events=lambda **kw:selected)))
        before = f.owner.content.read(ResourceRef.from_dict(mandate))["content"]
        made = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager", request_id="updated-native-mandate",
            document_id="updated-native-mandate", role="mandate", content={**before, "assignment_ref": adopted.ref.to_dict()})
        new_mandate = made["record"]["payload"]["current_revision"]
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=adopted.ref.to_dict(), generation=adopted.generation, mandate_ref=new_mandate,
            request_key="adopted-native-context", instruction="Read updated role context", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="actual-manager-session", binding_schedule_id=initial.schedule_id)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        raw = f.port.read_due(prepared["schedule_id"])
        self.assertEqual(raw["target"]["native_binding"], {"schedule_id": initial.schedule_id, "due_sha256": _digest(anchor)})
        f.app._verify_native_binding(adopted,'actual-manager-session',prepared['schedule_id'])
        setup = {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": {"manager": prepared["schedule_id"]},
            "advisor_policy": {"mode": "disabled", "reason": "No advisor selected"}, "acceptance_tasks": []}
        self.assertTrue(evaluate_setup(f.app.runtime, f.project.ref.to_dict(), setup)["ready"])
        self.assertEqual(f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="adopted-context-setup")["outcome"], "prepared")
        self.assertTrue(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["ready"])
        from otto.portfolio.owner_issue_loop import OwnerIssueReaders
        from otto.portfolio.issue_loop import IssueLoopError
        help_readers = OwnerIssueReaders(f.owner.consumer_operations(), f.port)
        self.assertEqual(help_readers.conversation(f.project.ref.to_dict(), adopted), "actual-manager-session")
        # Valid-looking pins to foreign sessions, generations and roles do not
        # establish continuity, even when their declared content hash matches.
        for field, value in (("generation", 2), ("role", "worker"), ("recipient", "foreign"), ("native_id", "foreign"),
                             ("authorization_status", "pending"), ("authorization_owner", "foreign")):
            fake = {**anchor, "schedule_id": "foreign-" + field}
            if field == "native_id": fake["target"] = {**anchor["target"], field: value}
            elif field.startswith("authorization_"):
                from copy import deepcopy
                fake["host_evidence"] = deepcopy(anchor["host_evidence"])
                key = "status" if field == "authorization_status" else "lifecycle_owner"
                fake["host_evidence"]["gateway_attempt"]["delivery_authorization"][key] = value
            else: fake[field] = value
            bad = replace(f.app._read(prepared["schedule_id"]), target={**raw["target"], "native_binding": {
                "schedule_id": fake["schedule_id"], "due_sha256": _digest(fake)}})
            original_port = f.app.runtime.due_port
            f.app.runtime.due_port = SimpleNamespace(read_due=lambda schedule: fake if schedule == fake["schedule_id"] else original_port.read_due(schedule))
            try:
                decision = evaluate_setup(f.app.runtime, f.project.ref.to_dict(), setup, current_due=bad)
                self.assertFalse(decision["ready"], field)
                proxy = SimpleNamespace(read_due=lambda schedule: bad.to_dict() if schedule == prepared["schedule_id"]
                    else fake if schedule == fake["schedule_id"] else original_port.read_due(schedule))
                with self.assertRaises(IssueLoopError, msg=field):
                    OwnerIssueReaders(f.owner.consumer_operations(), proxy).conversation(f.project.ref.to_dict(), adopted)

            finally:
                f.app.runtime.due_port = original_port
        self.assertEqual(f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        self.assertEqual(len(f.provider.calls), 2)
        self.assertEqual(f.port.read_due(initial.schedule_id), anchor)

    def test_draft_read_and_activation_are_inert(self):
        f = self.f
        self.assertEqual(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["state"], "draft")
        self.assertEqual(f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())["outcome"], "blocked")
        self.assertEqual(f.provider.calls, [])

    def test_installed_policy_binds_outer_dispatch_of_same_preprovider_callback(self):
        from otto.portfolio.manager_journey_service import install_manager_journey_service
        fixture = continuation_fixture.ManagerServiceContinuationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.fixture
        anchor = f.app._read(fixture.anchor)
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope("dispatch-required", parent_obligation=f.task.ref,
            criteria=[{"id": "dispatch-check"}], protocol="focused", designated_approver="manager",
            policy={"required_for_completion": True}, logical_request_key="dispatch-scope")
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "dispatch-pool"),
            capacity_units=1, cumulative_allowance_units=1, logical_request_key="dispatch-pool", actor=f.actor)
        state = {"authority": f.actor.authority, "owner": "manager", "manager": "manager",
            "assignment_ref": anchor.assignment_ref, "manager_generation": anchor.generation,
            "project_ref": f.project.ref.to_dict(), "task_refs": {"PA02": f.task.ref.to_dict()},
            "criterion_refs": {"C01": scope.criterion_refs[0].to_dict()}, "schedule_id": anchor.schedule_id,
            "requested_model": "gpt-test", "requested_reasoning": "high",
            "manager_continuation": {"schedule_id": anchor.schedule_id, "native_session_id": "manager-session"},
            "assessment_policy": {"kind": "owner_local_bookkeeping", "local_only": True,
                "purpose": "Installed dispatch check", "pool_id": "dispatch-pool", "capacity_units": 1,
                "cumulative_allowance_units": 1, "task_criterion_pairs": ["PA02/C01"]}}
        policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        prepared_app = f.owner.execution_application(due_port=f.port, adapter=f.app.runtime.adapter,
            clock=f.app.clock, assessment_policy=policy)
        setup = {"schema": "otto.operating-setup.v1", "mode": "manual",
            "roles": {"manager": anchor.schedule_id}, "acceptance_tasks": [f.task.ref.to_dict()],
            "advisor_policy": {"mode": "disabled", "reason": "Explicit isolated manual supervision"}}
        self.assertEqual(prepared_app.prepare_operating_setup(project_ref=state["project_ref"],
            setup=setup, request_key="dispatch-setup")["outcome"], "prepared")
        from otto.portfolio.manager_continuation_command import manager_continuation_from_command
        pending = manager_continuation_from_command(request={"operation": "prepare", "report_key": fixture.key},
            execution=prepared_app, anchor_schedule_id=fixture.anchor, current_schedule_id=fixture.anchor,
            task_refs=state["task_refs"], native_session_id="manager-session", read_reports=fixture.reports,
            preserve_execution_binding=True)
        schedule = pending["continuation"]["schedule_id"]
        before = f.port.read_due(schedule)
        pool_before = LimitService(f.store).get_pool(pool.ref)
        calls_before = len(f.provider.calls)
        # Reproduce the real boundary: setup preparation had a policy while
        # the host's subsequent execution factory omitted it.
        failed = f.app.start(schedule_id=schedule)
        self.assertEqual(failed["outcome"], "partial", failed)
        self.assertIn("owner-bound assessment policy", failed["error"]["message"])
        self.assertIsNone((f.port.read_due(schedule).get("host_evidence") or {}).get("gateway_attempt"))
        self.assertEqual(len(f.provider.calls), calls_before)
        host = SimpleNamespace(_closing=True, handler=None)
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, state=state, due_port=f.port,
            store=f.store, execution_host=host, _execution=lambda **_: f.app, _save_state=lambda: None)
        service = install_manager_journey_service(server, run_path=f.temporary.name, workspace=f.temporary.name,
            policy=state["assessment_policy"])
        # The installed factory also serves host-owned entrypoint paths.
        self.assertTrue(server._execution().read_operating_setup(project_ref=state["project_ref"])["ready"])
        request = {"command": "manager-continue", "operation": "dispatch", "report_key": fixture.key}
        result = host.handler(request)
        self.assertEqual(result["outcome"], "succeeded", result)
        self.assertEqual(result["continuation"]["schedule_id"], schedule)
        self.assertEqual(f.port.read_due(schedule)["target"], before["target"])
        self.assertEqual(len(f.provider.calls), calls_before + 1)
        self.assertEqual(LimitService(f.store).get_pool(pool.ref), pool_before)
        repeat = service(request)
        self.assertEqual(repeat["outcome"], "replayed", repeat)
        self.assertEqual(repeat["continuation"]["schedule_id"], schedule)
        self.assertEqual(len(f.provider.calls), calls_before + 1)

    def test_maintained_service_prepares_and_reads_setup_without_provider(self):
        f = self.f
        setup = self.manual()
        manager = f.app.assignments.get(ResourceRef.from_dict(f.app._read(setup["roles"]["manager"]).assignment_ref))
        state = {"authority": f.actor.authority, "owner": "manager", "manager": "manager",
                 "assignment_ref": manager.ref.to_dict(), "manager_generation": manager.generation,
                 "project_ref": f.project.ref.to_dict(), "task_refs": {"S01": f.task.ref.to_dict()},
                 "requested_model": "gpt-test", "requested_reasoning": "high"}
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, state=state, due_port=f.port,
                                 _execution=lambda **_: f.app)
        service = ManagerJourneyService(server=server, host=None, run_path=f.temporary.name, workspace=f.temporary.name)
        self.assertEqual(service({"command": "operating-setup", "operation": "read"})["state"], "draft")
        prepared = service({"command": "operating-setup", "operation": "prepare", "setup": setup, "request_key": "service-setup"})
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        read = service({"command": "operating-setup", "operation": "read", "setup": None, "request_key": None})
        self.assertEqual(read["outcome"], "read")
        self.assertEqual(read["state"], "ready")
        with self.assertRaisesRegex(ValueError, "bound project"):
            service({"command": "operating-setup", "operation": "read", "project_ref": f.project.ref.to_dict()})
        self.assertEqual(f.provider.calls, [])

    def test_manual_prepare_replay_start_and_active_read(self):
        f = self.f
        setup = self.manual()
        before = f.port.read_due(setup["roles"]["manager"])
        request = dict(project_ref=f.project.ref.to_dict(), setup=setup, request_key="setup-adopt")
        prepared = f.app.prepare_operating_setup(**request)
        duplicate = f.app.prepare_operating_setup(**request)
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        self.assertEqual(duplicate["setup_ref"], prepared["setup_ref"])
        self.assertEqual(f.port.read_due(setup["roles"]["manager"]), before)
        self.assertEqual(f.provider.calls, [])
        decision = f.app.read_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(decision["state"], "ready")
        self.assertFalse(decision["autonomous_ready"])
        self.assertFalse(decision["capabilities"]["operational_help_delivery"])
        started = f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(started["outcome"], "succeeded", started)
        self.assertEqual(f.app.read_operating_setup(project_ref=f.project.ref.to_dict())["state"], "active")
        self.assertEqual(f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), 1)

    def test_invalid_modes_and_advisor_omissions_fail_without_effects(self):
        config = self.manual()
        for change in ({"mode": "implicit"}, {"advisor_policy": {}},
                       {"advisor_policy": {"mode": "disabled"}}, {"roles": {}},
                       {"mode": "autonomous"}, {"advisor_policy": {"mode": "enabled"}}):
            with self.subTest(change=change), self.assertRaises(OperatingSetupError):
                normalize_setup({**config, **change})
        self.assertEqual(self.f.provider.calls, [])

    def test_missing_base_blocks_bootstrap_start_and_resume_without_claim(self):
        f = self.f
        manager, schedule = self.role("manager")
        unadopted = f.app.assignments.assign(f.project.ref, role="manager", principal="manager", manager="manager",
            session="manager-session", logical_request_key="missing-base", actor=f.actor)
        due = f.app._read(schedule)
        f.port.save_due(schedule, replace(due, assignment_ref=unadopted.ref.to_dict(),
            target={**due.target, "assignment_ref": unadopted.ref.to_dict()}, host_evidence={}).to_dict(),
            request_id="unadopted-role", expected_version=due.version)
        before = f.port.read_due(schedule)
        result = f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("BASE", result["error"]["message"])
        after = f.port.read_due(schedule)
        self.assertIsNone((after["host_evidence"] or {}).get("gateway_attempt"))
        self.assertEqual(before["target"], after["target"])
        self.assertEqual(f.provider.calls, [])

    def test_profile_conflict_is_rejected_before_gateway(self):
        f = self.f
        _, schedule = self.role("manager")
        due = f.app._read(schedule)
        changed = replace(due, profile="read-only", target={**due.target, "requested_profile": "read-only"})
        f.port.save_due(schedule, changed.to_dict(), request_id="profile-mismatch", expected_version=due.version)
        result = f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("profile", result["error"]["message"])
        self.assertEqual(f.provider.calls, [])
        self.assertIsNone((f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))

    def test_unknown_attempt_is_immutable_and_not_replayed_by_validation(self):
        f = self.f
        setup = self.manual()
        f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="setup-adopt")
        f.provider.unknown = True
        first = f.app.start(schedule_id=setup["roles"]["manager"])
        self.assertEqual(first["outcome"], "unknown", first)
        before = f.port.read_due(setup["roles"]["manager"])
        for _ in range(2):
            f.app.read_operating_setup(project_ref=f.project.ref.to_dict())
            f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(f.port.read_due(setup["roles"]["manager"]), before)
        self.assertEqual(len(f.provider.calls), 1)

    def acceptance(self, manager):
        f = self.f
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope("required-setup-gate", parent_obligation=f.task.ref,
            protocol="focused", criteria=[{"id": "A01", "definition": "Operating setup passes"}],
            designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="scope")
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "setup-review"),
            capacity_units=1, cumulative_allowance_units=1, logical_request_key="pool", actor=f.actor)
        policy = LocalAssessmentPolicy("Setup inspection", True, pool.ref, 1, 1, f.project.ref,
                                       ((f.task.ref, scope.criterion_refs[0]),))
        app = f.owner.execution_application(due_port=f.port, adapter=f.app.runtime.adapter,
                                           clock=f.app.clock, assessment_policy=policy)
        commands = f.owner.manager_assessment(project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            manager_assignment_ref=manager.ref.to_dict(), manager_actor="manager", manager_generation=1,
            assessment_policy=policy)
        return app, commands, scope, assessment, pool

    def test_autonomous_requires_real_help_route_and_uses_existing_acceptance(self):
        f = self.f
        manager, schedule = self.role("manager")
        orchestrator, help_schedule = self.role("orchestrator")
        app, _commands, _scope, _assessment, pool = self.acceptance(manager)
        config = {"schema": "otto.operating-setup.v1", "mode": "autonomous",
                  "roles": {"manager": schedule, "orchestrator": help_schedule},
                  "advisor_policy": {"mode": "disabled", "reason": "Explicit project opt-out"},
                  "acceptance_tasks": [f.task.ref.to_dict()]}
        decision = evaluate_setup(app.runtime, f.project.ref.to_dict(), config)
        self.assertFalse(decision["ready"])
        self.assertIn("delivery port", json.dumps(decision["blockers"]))
        loop = app.runtime.portfolio._issue_loop()
        class Delivery:
            def send(self, intent):
                raise AssertionError("Readiness must not send help")
        # Substitute scoped readers for a fixture project without default
        # orchestrator metadata; actual assignments and conversations are used.
        loop.ports = replace(loop.ports, current_manager=lambda _: manager,
                             current_supervisor=lambda _: orchestrator, delivery=Delivery())
        before = LimitService(f.store).get_pool(pool.ref)
        decision = evaluate_setup(app.runtime, f.project.ref.to_dict(), config)
        self.assertTrue(decision["autonomous_ready"], decision)
        self.assertEqual(decision["acceptance"]["required_scopes"][0]["limit_pool_ref"], pool.ref.to_dict())
        self.assertEqual(LimitService(f.store).get_pool(pool.ref), before)
        self.assertEqual(f.provider.calls, [])
        loop.ports = replace(loop.ports, current_supervisor=lambda _: manager)
        self.assertFalse(evaluate_setup(app.runtime, f.project.ref.to_dict(), config)["ready"])

    def test_required_scope_is_reused_and_conflicting_authority_is_pre_effect(self):
        f = self.f
        manager, _schedule = self.role("manager")
        _app, commands, scope, assessment, _pool = self.acceptance(manager)
        request = {"operation": "declare-scope", "request_key": "ordinary-manager-scope",
                   "expected_task_ref": f.task.ref.to_dict(), "expected_assignment_ref": manager.ref.to_dict(),
                   "expected_generation": 1, "arguments": {"scope_ref": {"authority": f.actor.authority,
                        "kind": "assessment.scope", "id": "would-duplicate-gate"},
                       "criterion_refs": [ref.to_dict() for ref in scope.criterion_refs], "protocol": "focused"}}
        result = commands.execute(request)
        self.assertEqual(result["ref"], scope.ref.to_dict())
        self.assertTrue(result["required_scope_reused"])
        self.assertEqual(commands._assessment.coverage(f.task.ref)["scope_count"], 1)
        assessment.declare_scope("incompatible-owner-gate", parent_obligation=f.task.ref, protocol="focused",
            criteria=scope.criterion_refs, designated_approver="root", policy={"required_for_completion": True},
            logical_request_key="incompatible-gate")
        with self.assertRaises(PermissionError):
            commands.execute({**request, "request_key": "reject-duplicate"})
        self.assertEqual(commands._assessment.coverage(f.task.ref)["scope_count"], 2)
        self.assertEqual(f.provider.calls, [])

    def test_adopted_setup_before_peer_completion_allows_next_worker_readiness(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f, state = fixture.application, fixture.fixture.state
        from herzchen.content.instructions import validate_instruction_content
        worker = f.app.assign_worker(**f.request())
        guide = worker["guide_ref"]
        content = f.owner.content.read(ResourceRef.from_dict(guide))["content"]
        base = fixture.fixture.manager
        manager = f.owner.assignments.command_port.adopt_resources(base.ref,
            resources=[{"resource_ref": guide, "resource_name": content["name"],
                "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=base.revision, expected_generation=base.generation,
            logical_request_key="peer-manager-adopt", actor=f.actor)
        state["assignment_ref"] = manager.ref.to_dict()
        contract = f.request()["instruction_contract"]
        contract["authority"]["owner_actor"] = "manager"
        contract["authority"]["effect_profile"] = "workspace-write-manager"
        contract["allowed_operations"].append("canonical_manager_commands")
        contract["authority"]["permitted_effects"].append("canonical_manager_commands")
        made = f.app.portfolio.create_document(state["project_ref"], actor="manager",
            request_id="peer-manager-mandate", document_id="peer-manager-mandate", role="mandate",
            content={"role": "manager", "scope_ref": state["project_ref"], "status": "active",
                "dispatch_enabled": True, "task_ref": f.task.ref.to_dict(), "assignment_ref": manager.ref.to_dict(),
                "generation": 1, "brief": {"role": "manager", "mandate": "Advance remaining work"},
                "instruction_contract": contract})
        mandate = made["record"]["payload"]["current_revision"]
        policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        app = f.owner.execution_application(due_port=f.port, adapter=f.app.runtime.adapter,
            clock=f.app.clock, assessment_policy=policy)
        role = app.prepare_role(role="manager", project_ref=state["project_ref"], task_ref=f.task.ref.to_dict(),
            assignment_ref=manager.ref.to_dict(), generation=1, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key="peer-completion-manager", instruction="Advance remaining delivery",
            model="gpt-test", reasoning="high", profile="workspace-write", native_session_id="retained-manager")
        configured = list(state["task_refs"].values())
        assessment = AssessmentModule(f.store, actor=f.actor)
        for alias, criterion in (("PA01", "C01"), ("PA06", "C09")):
            assessment.declare_scope("peer-scope-" + alias, parent_obligation=ResourceRef.from_dict(state["task_refs"][alias]),
                protocol="existing-pairs", criteria=[ResourceRef.from_dict(state["criterion_refs"][criterion])],
                designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="peer-scope-" + alias)
        f.owner.create_manager_assessment_pool(project_ref=state["project_ref"], task_ref=f.task.ref.to_dict(),
            manager_assignment_ref=manager.ref.to_dict(), manager_actor="manager", manager_generation=1,
            logical_request_key="peer-pool", assessment_policy=policy)
        config = {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": {"manager": role["schedule_id"]},
            "advisor_policy": {"mode": "disabled", "reason": "No advisor authorized"}, "acceptance_tasks": configured}
        prepared = app.prepare_operating_setup(project_ref=state["project_ref"], setup=config, request_key="before-peer-finish")
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        # The configured manager's execution task remains pending; a separate
        # acceptance task completes, as Portable D03 did before D04 startup.
        result = fixture.commands.review_task(fixture.request(alias="PA06", key="peer-review"))
        self.assertEqual(result["completion"]["outcome"], "completed", result)
        state["task_refs"]["PA06"] = result["completion"]["task_ref"]
        current_policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        current = f.owner.execution_application(due_port=f.port, adapter=f.app.runtime.adapter,
            clock=f.app.clock, assessment_policy=current_policy)
        pool_before = LimitService(f.store).get_pool(current_policy.pool_ref)
        from otto.portfolio.operating_setup import read_setup
        setup_before = read_setup(current.portfolio.operations, state["project_ref"])
        candidate = current.assign_worker(**{**f.request(), "request_key": "after-peer-completion"})
        started = current.start(schedule_id=candidate["schedule_id"])
        self.assertEqual(started["outcome"], "succeeded", started)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertEqual(read_setup(current.portfolio.operations, state["project_ref"]), setup_before)
        self.assertEqual(setup_before["acceptance_tasks"], configured)
        self.assertEqual(LimitService(f.store).get_pool(current_policy.pool_ref), pool_before)

    def test_ordinary_review_finishes_adopted_scope_without_owner_ratification(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.application
        task = ResourceRef.from_dict(fixture.fixture.state["task_refs"]["PA01"])
        criterion = ResourceRef.from_dict(fixture.fixture.state["criterion_refs"]["C01"])
        assessment = AssessmentModule(f.store, actor=f.actor)
        scope = assessment.declare_scope("owner-required-task-scope", parent_obligation=task,
            protocol="adopted-protocol", criteria=[criterion], designated_approver="manager",
            policy={"required_for_completion": True}, logical_request_key="owner-task-scope")
        result = fixture.commands.review_task(fixture.request(key="reuse-adopted-scope"))
        self.assertEqual(result["completion"]["outcome"], "completed", result)
        self.assertEqual(f.owner.graph.current(task).lifecycle.value, "completed")
        from otto.portfolio.assessment import OttoAssessment
        rows = OttoAssessment(assessment, f.actor).coverage(f.owner.graph.current(task).ref)
        self.assertEqual(rows["scope_count"], 1)
        self.assertEqual(rows["scopes"][0]["ref"], scope.ref.to_dict())
        # Setup uses the current completed head; completion consumed the
        # original accepted scope and must not create or spend another gate.
        state = fixture.fixture.state
        state["task_refs"]["PA01"] = f.owner.graph.current(task).ref.to_dict()
        policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        commands = f.owner.manager_assessment(project_ref=state["project_ref"],
            task_ref=state["task_refs"]["PA01"], manager_assignment_ref=state["assignment_ref"],
            manager_actor=state["manager"], manager_generation=state["manager_generation"], assessment_policy=policy)
        assessment.declare_scope("pending-task-scope", parent_obligation=ResourceRef.from_dict(state["task_refs"]["PA06"]),
            protocol="adopted-protocol", criteria=[ResourceRef.from_dict(state["criterion_refs"]["C09"])],
            designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="pending-scope")
        runtime = f.owner.role_runtime(due_port=f.port, adapter=f.app.runtime.adapter, assessment_policy=policy)
        request = {"operation": "resolve-required-scope", "arguments": {},
            "expected_task_ref": state["task_refs"]["PA01"],
            "expected_assignment_ref": state["assignment_ref"], "expected_generation": state["manager_generation"]}
        pool_before = LimitService(f.store).get_pool(policy.pool_ref)
        counts_before = f.owner.graph.reader.snapshot_counts()
        for _ in range(2):
            self.assertEqual(commands.execute(request)["scope_ref"], scope.ref.to_dict())
        ready = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                "generation": state["manager_generation"]}, list(state["task_refs"].values()))
        # A public setup admitted before finish retains the old exact task ref.
        # Readiness alone follows its exact completion transition to the head.
        configured_tasks = [task.to_dict(), state["task_refs"]["PA06"]]
        historical = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                "generation": state["manager_generation"]}, configured_tasks)
        self.assertEqual(historical["required_scopes"], ready["required_scopes"])
        self.assertEqual(historical["completed_task_readbacks"][0]["configured_task_ref"], task.to_dict())
        self.assertEqual(historical["completed_task_readbacks"][0]["current_task_ref"], state["task_refs"]["PA01"])
        with self.assertRaisesRegex(PermissionError, "completion predecessor"):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"], "generation": 1},
                [{**task.to_dict(), "revision": "rev-999"}, state["task_refs"]["PA06"]])
        with self.assertRaises(PermissionError):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"], "generation": 2}, configured_tasks)
        with self.assertRaisesRegex(PermissionError, "revision changed"):
            f.owner.manager_assessment(project_ref=state["project_ref"], task_ref=task.to_dict(),
                manager_assignment_ref=state["assignment_ref"], manager_actor=state["manager"],
                manager_generation=1, assessment_policy=policy)
        self.assertEqual(len(ready["required_scopes"]), 2)
        self.assertFalse(ready["allowance_created"])
        self.assertEqual(LimitService(f.store).get_pool(policy.pool_ref), pool_before)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), counts_before)
        # The historical read never grants mutable assessment authority.
        with self.assertRaisesRegex(PermissionError, "exact current task"):
            commands.required_scope()
        with self.assertRaisesRegex(PermissionError, "exact current task"):
            commands.execute({**request, "operation": "freeze-input", "request_key": "no-rejudge",
                "arguments": {"scope_ref": scope.ref.to_dict(), "candidate_ref": result["candidate_ref"],
                    "criterion_refs": [criterion.to_dict()], "source_refs": [], "evidence_refs": [], "packet": {}}})
        # A retained scope alone, or a later revision carrying a copied
        # completion payload, cannot satisfy the exact transition predicate.
        original_reader = commands._reader
        identity = original_reader.get_identity(ResourceRef.from_dict(state["task_refs"]["PA01"]))
        completion = identity.payload["completion"]
        class ReadView:
            def __init__(self, payload, receipt=None, missing=False):
                self.payload, self.receipt, self.missing = payload, receipt, missing
            def get_identity(self, ref):
                return replace(identity, payload=self.payload)
            def get_receipt(self, key):
                return None if self.missing else self.receipt or original_reader.get_receipt(key)
        receipt = original_reader.get_receipt(completion["logical_request_key"])
        cases = [
            ReadView({**identity.payload, "lifecycle": "pending"}),
            ReadView({**identity.payload, "completion": {**completion, "disposition": "unknown"}}),
            ReadView({**identity.payload, "completion": {**completion, "manager": "foreign"}}),
            ReadView({**identity.payload, "completion": {**completion, "task_ref": state["task_refs"]["PA01"]}}),
            ReadView({**identity.payload, "completion": {**completion, "assessment_gate_check": {
                **completion["assessment_gate_check"], "scope_refs": [], "blockers": [{"code": "UNKNOWN"}]}}}),
            ReadView(identity.payload, missing=True),
            ReadView(identity.payload, receipt=replace(receipt, result_ref=task)),
        ]
        for view in cases:
            with self.subTest(view=view):
                commands._reader = view
                with self.assertRaisesRegex(PermissionError, "completion proof"):
                    commands.execute(request)
        commands._reader = original_reader
        self.assertEqual(commands.execute(request)["scope_ref"], scope.ref.to_dict())
        # A genuine same-principal session handover changes the current
        # assignment generation. It does not reopen completed task scopes.
        adopted = f.owner.assignments.command_port.reassign(
            ResourceRef.from_dict(state["assignment_ref"]), principal=state["manager"],
            session="genuine-replacement-session", expected_generation=1,
            logical_request_key="scope-read-replacement", actor=f.actor)
        counts_after_binding = f.owner.graph.reader.snapshot_counts()
        replacement_ready = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": adopted.ref.to_dict(), "principal": state["manager"],
             "generation": adopted.generation}, configured_tasks)
        self.assertEqual(replacement_ready, historical)
        self.assertEqual(LimitService(f.store).get_pool(policy.pool_ref), pool_before)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), counts_after_binding)
        with self.assertRaises(PermissionError):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": adopted.ref.to_dict(), "principal": "foreign",
                 "generation": adopted.generation}, configured_tasks)
        self.assertEqual(f.provider.calls, [])

    def test_setup_acceptance_keeps_verified_completed_history_out_of_new_review_policy(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.application
        state = fixture.fixture.state
        graph = f.owner.graph
        original = {
            "D01": state["task_refs"]["PA01"],
            "D04": state["task_refs"]["PA06"],
        }
        state["task_refs"].update(D01=original["D01"], D04=original["D04"])
        for alias in ("D02", "D03", "D05"):
            task = graph.create_task(f.project.ref, title=alias, logical_request_key="history-task-" + alias)
            state["task_refs"][alias] = task.ref.to_dict()
            original[alias] = task.ref.to_dict()
        criterion_scope = AssessmentModule(f.store, actor=f.actor).declare_scope(
            "five-original-criteria", parent_obligation=f.project.ref, protocol="five-original-criteria",
            criteria=[{"id": value} for value in ("C01", "C02", "C03", "C04", "C05", "C09")],
            logical_request_key="five-original-criteria")
        criteria = {ref.id: ref.to_dict() for ref in criterion_scope.criterion_refs}
        state["criterion_refs"].update(criteria)
        # The original five task policies consumed their own local review pool;
        # current readiness now uses only the pending D04/D05 pair.
        original_policy = {"kind": "owner_local_bookkeeping", "purpose": "original five task reviews",
            "local_only": True, "pool_id": "historical-five-review", "capacity_units": 1,
            "cumulative_allowance_units": 3,
            "task_criterion_pairs": ["D01/C01", "D02/C02", "D03/C03", "D04/C04", "D05/C05"]}
        state["assessment_policy"] = original_policy
        aliases = {"D01": "C01", "D02": "C02", "D03": "C03"}
        configured_d03 = None
        for task_alias, criterion_alias in aliases.items():
            if task_alias == "D02":
                # Setup pins D02 at rev-1; owner admission advances its
                # revision without changing authored content before review.
                from herzchen.domains.work import admission
                pinned = ResourceRef.from_dict(original[task_alias])
                current_task = graph.current(pinned)
                admitted = graph.revise(current_task.ref, metadata_namespaces={admission.NAMESPACE: {
                    "revision": pinned.revision,
                    "digest": admission.content_digest(current_task.payload),
                    "reviewed_digest": admission.reviewed_content_digest(current_task.payload),
                    "basis": admission.BASIS_AUTHORING}},
                    logical_request_key="historical-admit-D02", actor=f.actor)
                state["task_refs"][task_alias] = admitted.ref.to_dict()
            if task_alias == "D03":
                # Preserve the original setup pin, then accept a later task
                # revision with changed authored instructions.
                changed = graph.revise(ResourceRef.from_dict(original[task_alias]),
                    title="D03 instructions changed before acceptance",
                    logical_request_key="historical-change-D03", actor=f.actor)
                state["task_refs"][task_alias] = changed.ref.to_dict()
                configured_d03 = changed.ref.to_dict()
            proof_evidence = None
            if task_alias == "D01":
                # Exercise the canonical mixed WRK+DAT evidence shape. The
                # generic assessment DAT verifier reports WRK evidence as
                # unknown, while the completion producer still pins a digest
                # for each exact evidence revision.
                result = f.owner.assignments.command_port.append_result(
                    ResourceRef.from_dict(state["assignment_ref"]),
                    {"outcome": "succeeded", "task_ref": state["task_refs"][task_alias],
                     "context_digest_verified": True},
                    expected_generation=state["manager_generation"],
                    logical_request_key="historical-wrk-evidence-" + task_alias, actor=f.actor)
                candidate = result.ref.to_dict()
                proof_evidence = fixture.source(task_alias + "-dat-proof")
            else:
                candidate = fixture.source(task_alias)
            reviewed = fixture.commands.review_task({"command": "review-task", "task": task_alias,
                "request_key": "historical-review-" + task_alias, "candidate_ref": candidate,
                "source_refs": [candidate], "inspection": {"observed": "Reviewed the exact task evidence"},
                "finish": task_alias != "D01",
                "judgments": {criterion_alias: {"verdict": "PASS", "rationale": "Evidence satisfies the criterion",
                    "evidence_refs": [candidate] + ([proof_evidence] if proof_evidence else [])}}})
            if task_alias == "D01":
                # Exercise the canonical completion producer directly: the
                # ordinary manager finish wrapper correctly holds WRK result
                # candidates until native settlement is bound.
                completion = f.owner.assignments.command_port.complete(
                    ResourceRef.from_dict(state["task_refs"][task_alias]),
                    project=ResourceRef.from_dict(state["project_ref"]),
                    assignment=ResourceRef.from_dict(state["assignment_ref"]),
                    expected_generation=state["manager_generation"],
                    expected_project_revision=state["project_ref"]["revision"],
                    expected_task_revision=state["task_refs"][task_alias]["revision"],
                    disposition="accepted", evidence_refs=reviewed["evidence_refs"],
                    evidence_hashes=reviewed["evidence_hashes"], gate_refs=reviewed["gate_refs"],
                    candidate_ref=reviewed["candidate_ref"],
                    logical_request_key="historical-review-D01:finish", actor=f.actor)
                reviewed = {**reviewed, "completion": completion}
            self.assertEqual(reviewed["completion"]["outcome"], "completed", reviewed)
            if task_alias == "D01":
                self.assertEqual(reviewed["completion"]["completion"]["assessment_gate_check"]["evidence_verification"], "unknown")
            state["task_refs"][task_alias] = reviewed["completion"]["task_ref"]

        # Preserve the setup pins before completion advances their heads.
        configured = [original["D01"], original["D02"], configured_d03,
            original["D04"], original["D05"]]
        current_policy = {"kind": "owner_local_bookkeeping", "purpose": "current D04/D05 readiness",
            "local_only": True, "pool_id": "current-two-review", "capacity_units": 1,
            "cumulative_allowance_units": 2, "task_criterion_pairs": ["D04/C04", "D05/C05"]}
        state["assessment_policy"] = current_policy
        policy = LocalAssessmentPolicy.from_run_config(current_policy, state=state)
        from herzchen.kernel import LimitService
        # Declare only the two current policy scopes; the old scopes remain
        # canonical history and are not reopened under the new policy.
        for alias, criterion in (("D04", "C04"), ("D05", "C05")):
            AssessmentModule(f.store, actor=f.actor).declare_scope("pending-" + alias,
                parent_obligation=ResourceRef.from_dict(state["task_refs"][alias]), protocol="current-policy",
                criteria=[ResourceRef.from_dict(criteria[criterion])], designated_approver="manager",
                policy={"required_for_completion": True}, logical_request_key="pending-scope-" + alias)
        f.owner.create_manager_assessment_pool(project_ref=state["project_ref"],
            task_ref=state["task_refs"]["D04"], manager_assignment_ref=state["assignment_ref"],
            manager_actor=state["manager"], manager_generation=state["manager_generation"],
            logical_request_key="current-two-review-pool", assessment_policy=policy)
        runtime = f.owner.role_runtime(due_port=f.port, adapter=f.app.runtime.adapter, assessment_policy=policy)
        pool = LimitService(f.store).get_pool(policy.pool_ref)
        foreign_task = graph.create_task(f.project.ref, title="Foreign historical task",
            logical_request_key="foreign-historical-task")
        counts = f.owner.graph.reader.snapshot_counts()
        ready = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                "generation": state["manager_generation"]}, configured)
        self.assertEqual(len(ready["required_scopes"]), 2)
        self.assertEqual([row["configured_task_ref"] for row in ready["completed_task_readbacks"]],
            configured[:3])
        changed_instructions = list(configured)
        changed_instructions[2] = original["D03"]
        with self.assertRaisesRegex(PermissionError, "content differs from completion predecessor"):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                 "generation": state["manager_generation"]}, changed_instructions)
        changed = list(configured)
        changed[1] = foreign_task.ref.to_dict()
        with self.assertRaises(PermissionError):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                 "generation": state["manager_generation"]}, changed)
        self.assertFalse(ready["allowance_created"])
        self.assertEqual(LimitService(f.store).get_pool(policy.pool_ref), pool)
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), counts)
        self.assertEqual(f.provider.calls, [])

        # Completion records the exact project head used at completion. A
        # later project revision is valid history when that stored ref and
        # project_revision agree; it must not be compared to the new head.
        prior_project_ref = dict(state["project_ref"])
        current_project = graph.current(ResourceRef.from_dict(prior_project_ref))
        next_project_ref = ResourceRef(current_project.ref.authority, current_project.ref.kind,
            current_project.ref.id, "rev-" + str(current_project.version + 1))
        f.store.revise_identity(current_project.ref, dict(current_project.payload),
            revision=next_project_ref.revision, expected_revision=current_project.ref.revision,
            expected_version=current_project.version)
        state["project_ref"] = next_project_ref.to_dict()
        policy = LocalAssessmentPolicy.from_run_config(current_policy, state=state)
        runtime = f.owner.role_runtime(due_port=f.port, adapter=f.app.runtime.adapter,
            assessment_policy=policy)
        after_project_revision = runtime.acceptance_readiness(state["project_ref"],
            {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                "generation": state["manager_generation"]}, configured)
        self.assertEqual(after_project_revision["completed_task_readbacks"], ready["completed_task_readbacks"])
        self.assertEqual(after_project_revision["required_scopes"], ready["required_scopes"])
        self.assertEqual(f.provider.calls, [])

        stale = list(configured)
        stale[1] = {**stale[1], "revision": "rev-999"}
        with self.assertRaisesRegex(PermissionError, "predecessor"):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                    "generation": state["manager_generation"]}, stale)
        missing = list(configured)
        pending = graph.create_task(f.project.ref, title="uncompleted extra", logical_request_key="uncompleted-extra")
        missing[2] = pending.ref.to_dict()
        with self.assertRaisesRegex(PermissionError, "canonical accepted completion"):
            runtime.acceptance_readiness(state["project_ref"],
                {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                    "generation": state["manager_generation"]}, missing)
        reader = f.owner.graph.reader
        original_get_identity = reader.get_identity
        def corrupt_completion(ref, corruption):
            identity = original_get_identity(ref)
            if identity is not None and identity.ref.id == ResourceRef.from_dict(original["D03"]).id:
                completion = identity.payload["completion"]
                payload_completion = dict(completion)
                if corruption == "gate":
                    gate = completion["assessment_gate_check"]
                    payload_completion["assessment_gate_check"] = {**gate, "accepted_decision_refs": []}
                elif corruption == "foreign-project":
                    payload_completion["project_ref"] = {**completion["project_ref"], "id": "other-project"}
                elif corruption == "stale-project-revision":
                    payload_completion["project_revision"] = "rev-999"
                elif corruption == "evidence-hash":
                    first_hash = next(iter(completion["evidence_hashes"]))
                    payload_completion["evidence_hashes"] = {**completion["evidence_hashes"],
                        first_hash: "0" * 64}
                elif corruption == "foreign-evidence":
                    evidence_refs = list(completion["evidence_refs"])
                    evidence_refs[0] = {**evidence_refs[0], "authority": "foreign-authority"}
                    payload_completion["evidence_refs"] = evidence_refs
                elif corruption == "stale-evidence":
                    evidence_refs = list(completion["evidence_refs"])
                    evidence_refs[0] = {**evidence_refs[0], "revision": "rev-999"}
                    payload_completion["evidence_refs"] = evidence_refs
                payload = {**identity.payload, "completion": payload_completion}
                return replace(identity, payload=payload)
            return identity
        class CorruptReader:
            def __init__(self, corruption):
                self.corruption = corruption
            def __getattr__(self, name):
                return getattr(reader, name)
            def get_identity(self, ref):
                return corrupt_completion(ref, self.corruption)
        for corruption, message in (("gate", "accepted gate proof"),
                                    ("foreign-project", "canonical accepted completion proof"),
                                    ("stale-project-revision", "canonical accepted completion proof"),
                                    ("evidence-hash", "evidence hash"),
                                    ("foreign-evidence", "evidence hash"),
                                    ("stale-evidence", "evidence hashes do not cover")):
            object.__setattr__(f.owner.graph, "reader", CorruptReader(corruption))
            try:
                with self.assertRaisesRegex(PermissionError, message):
                    runtime.acceptance_readiness(state["project_ref"],
                        {"assignment_ref": state["assignment_ref"], "principal": state["manager"],
                            "generation": state["manager_generation"]}, configured)
            finally:
                object.__setattr__(f.owner.graph, "reader", reader)

    def test_manual_manager_sync_failure_surfaces_finite_readiness_blockers(self):
        f = self.f
        _manager, schedule = self.role("manager")
        app = f.app
        original = app.synchronize_manual_manager_occurrence
        try:
            blocker = {"role": "manager", "code": "OccurrencePreparationError", "message": "retained selector is foreign"}
            app.synchronize_manual_manager_occurrence = lambda **_kwargs: {
                "outcome": "partial", "readiness": {"ready": False, "blockers": [blocker]}}
            partial = app.start(schedule_id=schedule)
            self.assertEqual(partial["stage"], "manager-synchronization")
            self.assertEqual(partial["readiness"]["blockers"], [blocker])
            self.assertFalse(partial["provider_called"])
            self.assertIn("reported manager readiness blocker", partial["next_action"])

            def fail(**_kwargs):
                raise PermissionError("current manual selector lacks its exact predecessor")
            app.synchronize_manual_manager_occurrence = fail
            raised = app.start(schedule_id=schedule)
            self.assertEqual(raised["readiness"]["blockers"], [{"role": "manager",
                "code": "PermissionError", "message": "current manual selector lacks its exact predecessor"}])
            self.assertFalse(raised["provider_called"])
            self.assertEqual(f.provider.calls, [])
        finally:
            app.synchronize_manual_manager_occurrence = original

    def test_missing_execution_contract_rejects_before_initialization_and_valid_request_recovers(self):
        f = self.f
        manager, valid_schedule = self.role("manager")
        bad = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager", request_id="incomplete-mandate",
            document_id="incomplete-mandate", role="mandate", content={"role": "manager", "scope_ref": f.project.ref.to_dict(),
                "status": "active", "brief": {"role": "manager", "mandate": "Advance useful project"}})
        due = f.app._read(valid_schedule)
        prepared = f.app.prepare_role(role="manager", project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=manager.ref.to_dict(), generation=manager.generation,
            mandate_ref=bad["record"]["payload"]["current_revision"], context_refs=due.context_refs,
            request_key="bad-execution-contract", instruction="Advance useful project", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        invalid_schedule = prepared["schedule_id"]
        for start in (lambda: f.app.start(schedule_id=invalid_schedule),
                      lambda: f.app.recover(schedule_id=invalid_schedule, execute=True)):
            result = start()
            self.assertEqual(result["outcome"], "partial", result)
            self.assertIsNone((f.port.read_due(invalid_schedule)["host_evidence"] or {}).get("gateway_attempt"))
        self.assertEqual(f.provider.calls, [])
        valid = f.app.start(schedule_id=valid_schedule)
        self.assertEqual(valid["outcome"], "succeeded", valid)
        self.assertEqual(len(f.provider.calls), 1)
        self.assertEqual(valid["result"]["physical_session_id"], "manager-session")

    def test_conflicting_required_authority_rejects_before_pool_or_review_writes(self):
        fixture = journey_fixture.ManagerJourneyCommandTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.application
        task = ResourceRef.from_dict(fixture.fixture.state["task_refs"]["PA01"])
        criterion = ResourceRef.from_dict(fixture.fixture.state["criterion_refs"]["C01"])
        AssessmentModule(f.store, actor=f.actor).declare_scope("owner-only-task-scope", parent_obligation=task,
            protocol="adopted-protocol", criteria=[criterion], designated_approver="root",
            policy={"required_for_completion": True}, logical_request_key="owner-only-scope")
        with self.assertRaisesRegex(PermissionError, "designated"):
            fixture.commands.review_task(fixture.request(key="reject-foreign-scope"))
        self.assertIsNone(LimitService(f.store).get_pool(ResourceRef(f.actor.authority, "limit", "local-inspection")))
        self.assertIsNone(fixture.commands._journal("reject-foreign-scope", "intent"))
        self.assertEqual(f.provider.calls, [])


if __name__ == "__main__":
    unittest.main()

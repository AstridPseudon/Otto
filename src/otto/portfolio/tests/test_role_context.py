"""S02 owner composition and actual provider-bound packet regressions.

All records and transports are disposable fixtures. No live host, allowance,
owner database or installed service is changed by this suite.
"""
from dataclasses import replace
import hashlib
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef, TransactionContext, canonical_json
from herzchen.kernel.limits import LimitService
from otto.portfolio.operating_setup import evaluate_setup
from tests import test_execution_application as owner_fixture


class RoleContextTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.number = 0

    def document(self, role, content):
        self.number += 1
        result = self.f.app.portfolio.create_document(self.f.project.ref.to_dict(), actor="manager",
            request_id="context-doc-" + str(self.number), document_id="context-doc-" + str(self.number),
            role=role, content=content)
        return result["record"]["payload"]["current_revision"]

    def revise(self, ref, content):
        self.number += 1
        port = self.f.app.portfolio.operations.content_port
        stable = ResourceRef(ref["authority"], ref["kind"], ref["id"])
        current = port.read(stable)
        doc = ContentDocument.from_dict(current["document"])
        revision = "rev-" + str(int(current["current_revision"]["revision"].split("-")[1]) + 1)
        value = ContentRevision(stable, revision, content, self.f.actor,
            parent_revision=current["current_revision"]["revision"])
        payload = {"document": doc, "revision": value}
        context = TransactionContext(self.f.actor, "context-revise-" + str(self.number),
            hashlib.sha256(canonical_json(payload).encode()).hexdigest(), expected_revision=value.parent_revision)
        port.execute(port.build_append_revision(context, doc, value))
        return {**ref, "revision": revision}

    def configuration(self):
        return {"schema": "otto.role-configuration.v1", "pack": "selected-fixture-pack",
                "role_bindings": {"manager": "coordinator", "orchestrator": "help", "project_advisor": "advisor"},
                "roles": {"coordinator": {"model": "gpt-test", "reasoning": "high"},
                          "help": {"model": "gpt-test", "reasoning": "high"},
                          "advisor": {"model": "gpt-test", "reasoning": "high"},
                          "worker_xhard": {"model": "configured-worker", "reasoning": "high"}},
                "tool_entrypoints": {"manager": "manager_ctl.py --help",
                                     "orchestrator": "python -m otto.portfolio.cli help --format text"}}

    def role(self, role="manager", sources=None, overrides=None):
        f = self.f
        principal = "advisor" if role == "project_advisor" else role
        assignment, guide, mandate = f.role_handles(role, principal, role + "-session")
        if sources is not None:
            instructions = "Selected pack policy: coordinate, delegate implementation to configured workers, review and bookkeep; ask for operational help when dispatch is unavailable."
            content = {"schema": "herzchen.instructions.v1", "name": "selected-" + role,
                       "entrypoint": role.upper() + ".md", "instructions": instructions,
                       "bundle_digest": hashlib.sha256(instructions.encode()).hexdigest(),
                       "export_manifest_digest": "selected-pack-manifest", "required": True,
                       "supporting_refs": sources}
            guide = self.document("role_instructions", content)
            assignment = f.app.assignments.adopt_resources(assignment.ref,
                resources=[{"resource_ref": guide, "resource_name": content["name"],
                            "content_digest": validate_instruction_content(content), "required": True}],
                expected_revision=assignment.revision, expected_generation=assignment.generation,
                logical_request_key="selected-" + role, actor=f.actor)
            old = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(mandate))["content"]
            mandate = self.document("mandate", {**old, "assignment_ref": assignment.ref.to_dict()})
        request = dict(role=role, project_ref=f.project.ref.to_dict(), task_ref=f.task.ref.to_dict(),
            assignment_ref=assignment.ref.to_dict(), generation=assignment.generation, mandate_ref=mandate,
            request_key="sparse-" + role, profile="workspace-write" if role == "manager" else "read-only")
        if sources is None:
            request.update(model="gpt-test", reasoning="high")
        request.update(overrides or {})
        prepared = f.app.prepare_role(**request)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        return assignment, prepared["schedule_id"], request

    def setup(self, schedules, *, advisor=False):
        return {"schema": "otto.operating-setup.v1", "mode": "manual", "roles": schedules,
                "advisor_policy": {"mode": "enabled"} if advisor else
                    {"mode": "disabled", "reason": "No advisor execution allowance selected"},
                "acceptance_tasks": []}

    def packet(self, index=-1):
        match = re.search(r'<otto-resource-brief[^>]*>\s*(.*?)\s*</otto-resource-brief>',
                          self.f.provider.calls[index], re.S)
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_sparse_role_receives_selected_policy_sources_bindings_and_disabled_advisor(self):
        f = self.f
        configuration = self.document("run_configuration", self.configuration())
        goal = self.document("goal", {"text": "Deliver the adopted outcome under owner constraints"})
        skill = self.document("skill", {"text": "Maintained delegation and operational-help guidance"})
        _manager, schedule, _request = self.role(sources=[configuration, goal, skill])
        due = f.app._read(schedule)
        self.assertEqual(due.context_refs, (due.context_refs[0], due.target["mandate_ref"], configuration, goal, skill))
        self.assertEqual(due.target["native_id"], "manager-session")
        self.assertEqual(due.target["execution_selection"]["model"], {"source": "selected_configuration", "ref": configuration})
        setup = self.setup({"manager": schedule})
        prepared = f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="sparse-setup")
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        self.assertEqual(f.provider.calls, [])
        intro = prepared["readiness"]["introductions"]["manager"]
        self.assertEqual(intro["current_task"]["ref"], f.task.ref.to_dict())
        self.assertEqual(intro["goal"]["title"], "Useful project")
        self.assertEqual(intro["tool_entrypoint"], "manager_ctl.py --help")
        result = f.app.activate_operating_setup(project_ref=f.project.ref.to_dict())
        self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
        packet = self.packet()
        self.assertIn("delegate implementation", packet["operating_core"]["operating_contract"])
        installed_evidence = packet["operating_core"]["introduction"]["operating_guidance"]["installed_evidence"]
        self.assertIn("criteria that explicitly require installed behavior", installed_evidence)
        self.assertIn("request operational help", installed_evidence)
        self.assertIn("ordinary REWORK finding", installed_evidence)
        self.assertEqual(packet["context"]["selected_configuration"]["ref"], configuration)
        self.assertEqual([s["ref"] for s in packet["context"]["supporting_context"]], [configuration, goal, skill])
        operating = packet["context"]["operating_setup"]
        self.assertEqual(operating["advisor_policy"], setup["advisor_policy"])
        self.assertFalse(operating["operational_help"]["ready"])
        self.assertEqual(operating["roles"]["manager"]["conversation_id"], "manager-session")

    def test_explicit_overrides_retain_configuration_and_provenance(self):
        config = self.configuration()
        config["roles"]["coordinator"] = {"model": "configured-model", "reasoning": "low"}
        ref = self.document("run_configuration", config)
        _manager, schedule, _request = self.role(sources=[ref], overrides={"model": "gpt-test", "reasoning": "high"})
        due = self.f.app._read(schedule)
        self.assertEqual(due.requested_model, "gpt-test")
        self.assertEqual(due.target["execution_selection"]["model"]["source"], "explicit_override")
        result = self.f.app.start(schedule_id=schedule)
        self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
        self.assertEqual(self.packet()["context"]["selected_configuration"]["ref"], ref)
        self.assertEqual(self.packet()["context"]["operating_setup"]["current_execution"]["model"], "gpt-test")

    def test_selected_manager_policy_is_provenance_bearing_and_not_a_core_default(self):
        for selected in ("Megado: delegate normal implementation to worker_normal and justified XHARD to worker_xhard.",
                         "Other pack: the manager implements directly under this project's policy."):
            with self.subTest(policy=selected):
                case = RoleContextTests(); case.setUp(); self.addCleanup(case.doCleanups)
                config = case.configuration(); config["role_policies"] = {"manager": selected}
                ref = case.document("run_configuration", config)
                _manager, schedule, _request = case.role(sources=[ref])
                result = case.f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "succeeded", result.get("error"))
                intro = case.packet()["operating_core"]["introduction"]
                self.assertEqual(intro["selected_policy"], selected)
                self.assertEqual(intro["selected_policy_source"], ref)
                self.assertNotIn("worker_normal", intro["responsibility"])
                self.assertNotIn("worker_xhard", intro["responsibility"])
        _manager, schedule, _request = self.role()
        self.assertEqual(self.f.app.start(schedule_id=schedule)["outcome"], "succeeded")
        self.assertIsNone(self.packet()["operating_core"]["introduction"]["selected_policy"])

    def test_ordinary_worker_inherits_current_adopted_configuration_and_installed_command(self):
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        config = self.configuration()
        config["role_bindings"]["worker"] = "worker_normal"
        config["roles"]["worker_normal"] = {"model": "gpt-test", "reasoning": "high"}
        command = "/verified/python3 /verified/controller/manager_ctl.py help --format text"
        config["tool_entrypoints"]["worker"] = command
        ref = self.document("run_configuration", config)
        manager, _schedule, _request = self.role(sources=[ref])
        f = self.f; root = Path(f.temporary.name).resolve()
        (root / "run.yaml").write_text(json.dumps({"roles": {
            "worker_normal": {"model": "gpt-test", "reasoning": "high"},
            "worker_xhard": {"model": "gpt-xhard-test", "reasoning": "high"}}}))
        state = {"project_ref": f.project.ref.to_dict(), "task_refs": {"S06": f.task.ref.to_dict()},
            "assignment_ref": manager.ref.to_dict(), "manager_generation": manager.generation, "manager": "manager"}
        host = SimpleNamespace(_closing=False, submit=lambda _: {"outcome": "admitted"})
        server = SimpleNamespace(owner=f.owner, portfolio=f.app.portfolio, state=state,
            due_port=f.port, _execution=lambda **_: f.app, _save_state=lambda: None)
        service = ManagerJourneyService(server=server, host=host, workspace=root, run_path=root)
        request = {"command": "run-worker", "task": "S06", "route": "normal", "principal": "worker",
            "request_key": "selected-worker", "focus": "Read the delivered installed command"}
        prepared = service._submit_worker(request)
        self.assertEqual(prepared["outcome"], "admitted", prepared)
        self.assertEqual(f.provider.calls, [])
        self.assertEqual(f.app._read(prepared["schedule_id"]).context_refs[2:], (ref,))
        self.assertEqual(f.app.start(schedule_id=prepared["schedule_id"])["outcome"], "succeeded")
        intro = self.packet()["operating_core"]["introduction"]
        self.assertEqual(intro["tool_entrypoint"], command)
        self.assertEqual(intro["tool_entrypoint_source"], ref)
        # A selected default worker slot does not replace the explicit XHARD
        # route. Both receive the same adopted policy/host command provenance.
        f.app.runtime.adapter.requested_model = "gpt-xhard-test"
        xhard = service._submit_worker({**request, "route": "xhard", "request_key": "xhard-worker", "principal": "xhard"})
        due = f.app._read(xhard["schedule_id"])
        self.assertEqual(due.requested_model, "gpt-xhard-test")
        self.assertEqual(due.target["execution_selection"]["model"],
            {"source": "explicit_override", "selected_configuration_ref": ref})
        self.assertEqual(f.app.start(schedule_id=due.schedule_id)["outcome"], "succeeded")
        self.assertEqual(self.packet()["operating_core"]["introduction"]["tool_entrypoint"], command)
        self.assertEqual(self.packet()["context"]["operating_setup"]["current_execution"]["model"], "gpt-xhard-test")
        calls = len(f.provider.calls)
        retained = service._submit_worker({**request, "route": "xhard", "request_key": "xhard-worker", "principal": "xhard"})
        self.assertEqual(retained["outcome"], "replayed")
        self.assertEqual(len(f.provider.calls), calls)
        before = len(f.port.list_due())
        self.revise(ref, {**config, "changed": "new command requires readoption"})
        with self.assertRaisesRegex(ValueError, "stale"):
            service._submit_worker({**request, "request_key": "new-worker", "principal": "next-worker"})
        self.assertEqual(len(f.port.list_due()), before)
        self.assertEqual(len(f.provider.calls), 2)

    def test_required_source_missing_rejects_sparse_preparation_without_due_or_provider(self):
        missing = {"authority": self.f.actor.authority, "kind": "dat.content.document", "id": "missing-goal", "revision": "rev-1"}
        with self.assertRaisesRegex(ValueError, "supporting context.*missing"):
            self.role(sources=[missing])
        self.assertEqual(self.f.provider.calls, [])
        self.assertFalse(any(d["role"] == "manager" for d in self.f.port.list_due()))

    def test_missing_config_has_no_silent_model_or_instruction_fallback(self):
        with self.assertRaisesRegex(ValueError, "adopted role configuration"):
            self.role(sources=[])
        self.assertEqual(self.f.provider.calls, [])

    def test_goal_plan_skill_or_run_revision_rejects_future_delivery_before_claim(self):
        for kind in ("goal", "plan", "skill", "run_configuration"):
            with self.subTest(kind=kind):
                # Each variant has a separate fixture because role identities
                # are durable, not disposable retries of the same request key.
                case = RoleContextTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                ref = case.document(kind, case.configuration())
                _manager, schedule, _request = case.role(sources=[ref])
                case.revise(ref, {**case.configuration(), "changed": kind})
                result = case.f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "partial", result)
                self.assertIn("stale", result["error"]["message"])
                self.assertIsNone((case.f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))
                self.assertEqual(case.f.provider.calls, [])

    def test_current_binding_cannot_be_overridden_by_admission_or_recipient_prose(self):
        _manager, schedule, _request = self.role()
        due = self.f.app._resources(self.f.app._read(schedule))
        changed = replace(due, target={**due.target, "native_id": "foreign-session"},
                          host_evidence={**(due.host_evidence or {}), "gateway_attempt": {"delivery_admission": {"physical_session_id": "foreign-session"}}})
        self.f.port.save_due(schedule, changed.to_dict(), request_id="wrong-native", expected_version=due.version)
        decision = evaluate_setup(self.f.app.runtime, self.f.project.ref.to_dict(), self.setup({"manager": schedule}))
        self.assertFalse(decision["ready"])
        self.assertIn("current assignment binding", json.dumps(decision["blockers"]))
        due = self.f.app._read(schedule)
        self.f.port.save_due(schedule, replace(due, target={**due.target, "native_id": "manager-session"},
            recipient="name-in-prose").to_dict(), request_id="wrong-recipient", expected_version=due.version)
        decision = evaluate_setup(self.f.app.runtime, self.f.project.ref.to_dict(), self.setup({"manager": schedule}))
        self.assertFalse(decision["ready"])
        self.assertIn("canonical principal", json.dumps(decision["blockers"]))
        self.assertEqual(self.f.provider.calls, [])

    def test_enabled_advisor_pairing_and_all_role_packets_use_actual_conversations(self):
        f = self.f
        configuration = self.document("run_configuration", self.configuration())
        manager, manager_schedule, _ = self.role(sources=[configuration])
        orchestrator, help_schedule, _ = self.role("orchestrator", sources=[configuration])
        advisor, advisor_schedule, _ = self.role("project_advisor", sources=[configuration])
        pool = LimitService(f.store).create_pool(ResourceRef(f.actor.authority, "limit", "context-advisor"),
            capacity_units=1, cumulative_allowance_units=2, logical_request_key="context-advisor-pool", actor=f.actor)
        due = f.app._read(advisor_schedule)
        f.port.save_due(advisor_schedule, replace(due, allowance_ref=pool.ref.to_dict()).to_dict(),
                       request_id="bind-advisor-allowance", expected_version=due.version)
        setup = self.setup({"manager": manager_schedule, "orchestrator": help_schedule,
                            "project_advisor": advisor_schedule}, advisor=True)
        prepared = f.app.prepare_operating_setup(project_ref=f.project.ref.to_dict(), setup=setup, request_key="all-roles")
        self.assertEqual(prepared["outcome"], "prepared", prepared)
        pairing = prepared["readiness"]["advisor_pairing"]
        self.assertEqual(pairing["manager_ref"], manager.ref.to_dict())
        self.assertEqual(pairing["advisor_ref"], advisor.ref.to_dict())
        for role, schedule in setup["roles"].items():
            result = f.app.start(schedule_id=schedule)
            self.assertEqual(result["outcome"], "succeeded", {k: result.get(k) for k in ("stage", "error", "next_action")})
            packet = self.packet()
            self.assertEqual(packet["operating_core"]["introduction"]["role"], role)
            context = packet["context"]["operating_setup"]
            self.assertEqual(context["advisor_pairing"], pairing)
            self.assertEqual(context["roles"][role]["conversation_id"], role + "-session")
        self.assertEqual(len(f.provider.calls), 3)
        f.app.assignments.assign(f.project.ref, role="manager", principal="replacement",
            manager="manager", session="replacement-session", logical_request_key="duplicate-manager", actor=f.actor)
        decision = evaluate_setup(f.app.runtime, f.project.ref.to_dict(), setup)
        self.assertFalse(decision["ready"])
        self.assertIn("exactly one active manager", json.dumps(decision["blockers"]))

    def test_continuation_receives_same_adopted_policy_and_current_occurrence(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        assignment, schedule, _ = self.role(sources=[config])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        first_packet = self.packet()
        before = f.port.read_due(schedule)
        f.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": f.project.ref.to_dict(),
             "task_alias": "task", "continue_requested": True, "next_action": "Review the next worker result",
             "logical_request_key": "context-next", "recorded_at": f.app._now()},
            expected_generation=1, logical_request_key="context-progress", actor=f.actor)
        continued = f.app.continue_manager(schedule_id=schedule)
        self.assertEqual(continued["outcome"], "succeeded", continued.get("error"))
        packet = self.packet()
        self.assertEqual(packet["operating_core"]["operating_contract"], first_packet["operating_core"]["operating_contract"])
        self.assertEqual(packet["context"]["selected_configuration"]["ref"], config)
        self.assertEqual(packet["context"]["operating_setup"]["current_execution"]["selection"],
                         first_packet["context"]["operating_setup"]["current_execution"]["selection"])
        self.assertEqual(f.port.read_due(schedule), before)
        self.assertEqual(continued["result"]["physical_session_id"], "manager-session")
        self.assertEqual(len(f.provider.calls), 2)

    def test_explicit_source_adoption_refreshes_future_packet_and_preserves_admitted_turn(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        goal = self.document("goal", {"text": "Original adopted goal"})
        assignment, schedule, request = self.role(sources=[config, goal])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        original_packet = self.packet()
        original_due = f.port.read_due(schedule)
        goal = self.revise(goal, {"text": "Amended adopted goal"})
        guide = original_due["context_refs"][0]
        content = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(guide))["content"]
        content = {**content, "supporting_refs": [config, goal]}
        guide = self.revise(guide, content)
        assignment = f.app.assignments.adopt_resources(assignment.ref,
            resources=[{"resource_ref": guide, "resource_name": content["name"],
                        "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=assignment.revision, expected_generation=1, logical_request_key="adopt-amended-goal", actor=f.actor)
        old_mandate = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        mandate = self.document("mandate", {**old_mandate, "assignment_ref": assignment.ref.to_dict()})
        prepared = f.app.prepare_role(**{**request, "assignment_ref": assignment.ref.to_dict(),
            "mandate_ref": mandate, "request_key": "amended-future-turn"})
        self.assertEqual(prepared["outcome"], "committed", prepared)
        future = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(future["outcome"], "succeeded", future.get("error"))
        packet = self.packet()
        self.assertEqual(packet["context"]["supporting_context"][1]["content"]["text"], "Amended adopted goal")
        self.assertEqual(packet["operating_core"]["introduction"]["mandate_ref"], mandate)
        self.assertEqual(f.port.read_due(schedule), original_due)
        self.assertEqual(self.packet(0), original_packet)
        self.assertEqual(len(f.provider.calls), 2)

    def test_task_goal_mandate_and_assignment_changes_reject_unadmitted_turn(self):
        for kind in ("task", "project", "mandate", "assignment"):
            with self.subTest(kind=kind):
                case = RoleContextTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                f = case.f
                assignment, schedule, request = case.role()
                if kind in {"task", "project"}:
                    record = getattr(f, kind)
                    f.owner.graph.revise(record.ref, title="Amended canonical " + kind,
                                         logical_request_key="amend-" + kind, actor=f.actor)
                elif kind == "mandate":
                    raw = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
                    case.revise(request["mandate_ref"], {**raw, "brief": {"role": "manager", "mandate": "Amended mandate"}})
                else:
                    f.app.assignments.reassign(assignment.ref, principal="replacement", session="replacement-session",
                        expected_generation=1, logical_request_key="replace-manager", actor=f.actor)
                result = f.app.start(schedule_id=schedule)
                self.assertEqual(result["outcome"], "partial", result.get("error"))
                self.assertEqual(f.provider.calls, [])
                self.assertIsNone((f.port.read_due(schedule)["host_evidence"] or {}).get("gateway_attempt"))

    def test_replacement_packet_uses_current_generation_principal_and_conversation(self):
        f = self.f
        config = self.document("run_configuration", self.configuration())
        assignment, schedule, request = self.role(sources=[config])
        first = f.app.start(schedule_id=schedule)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        before = f.port.read_due(schedule)
        replacement = f.app.assignments.reassign(assignment.ref, principal="replacement",
            session="replacement-session", expected_generation=1, logical_request_key="current-replacement", actor=f.actor)
        old = f.app.portfolio.operations.content_port.read(ResourceRef.from_dict(request["mandate_ref"]))["content"]
        contract = old["instruction_contract"]
        mandate = self.document("mandate", {**old, "assignment_ref": replacement.ref.to_dict(),
            "generation": replacement.generation, "instruction_contract": {**contract,
                "authority": {**contract["authority"], "owner_actor": "replacement"}}})
        prepared = f.app.prepare_role(**{**request, "assignment_ref": replacement.ref.to_dict(),
            "generation": replacement.generation, "mandate_ref": mandate, "request_key": "replacement-packet"})
        self.assertEqual(prepared["outcome"], "committed", prepared)
        result = f.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        intro = self.packet()["operating_core"]["introduction"]
        self.assertEqual(intro["principal"], "replacement")
        self.assertEqual(intro["generation"], 2)
        self.assertEqual(intro["assignment_ref"], replacement.ref.to_dict())
        self.assertEqual(result["result"]["physical_session_id"], "replacement-session")
        self.assertEqual(f.port.read_due(schedule), before)

    def test_context_race_rejects_packet_even_when_reader_reuses_a_mutable_mapping(self):
        from otto.agents.orchestrator_route import prepare_canonical_assignment_role_brief
        f = self.f
        _assignment, schedule, _request = self.role()
        due = f.app._read(schedule)
        target, runtime = due.target, f.app.runtime
        observed = {"revision": 0}
        def context():
            observed["revision"] += 1
            return observed
        with self.assertRaisesRegex(ValueError, "role context changed"):
            prepare_canonical_assignment_role_brief(role="manager", project_ref=target["project_ref"],
                task_ref=target["task_ref"], assignment_ref=due.assignment_ref, mandate_ref=target["mandate_ref"],
                expected_generation=1, lifecycle="resume", as_of=due.anchor,
                project_reader=runtime._project_reader(target["project_ref"]),
                task_reader=runtime._task_reader(target["project_ref"], target["task_ref"]),
                assignment_reader=runtime._assignment_reader(due.assignment_ref),
                mandate_reader=runtime._mandate_reader(target["project_ref"], target["mandate_ref"]),
                resource_reader=runtime.operations.content_port, operating_context_reader=context)
        self.assertEqual(f.provider.calls, [])

    def test_existing_explicit_preparation_identity_replays_without_new_provenance(self):
        f = self.f
        _assignment, schedule, request = self.role()
        due = f.app._read(schedule)
        original = [due.role, due.target["project_ref"], due.target["task_ref"], due.assignment_ref,
                    due.generation, due.target["mandate_ref"], due.context_refs, due.instruction,
                    due.requested_model, due.requested_reasoning, due.profile, due.target["native_id"],
                    due.timeout_seconds, due.allowance_ref]
        digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(due.invocation_identity, request["request_key"] + ":" + digest)
        # A pre-S02 occurrence has the same semantic identity and no selection
        # projection. Replaying it must preserve that existing target.
        target = {key: value for key, value in due.target.items() if key != "execution_selection"}
        f.port.save_due(schedule, replace(due, target=target).to_dict(), request_id="legacy-role-target", expected_version=due.version)
        replay = f.app.prepare_role(**{**request, "instruction": due.instruction,
            "context_refs": due.context_refs, "native_session_id": due.target["native_id"]})
        self.assertEqual(replay["schedule_id"], schedule)
        self.assertNotIn("execution_selection", f.app._read(schedule).target)
        self.assertEqual(f.provider.calls, [])

    def test_pre_s02_retained_worker_packet_settles_without_provider_replay(self):
        from unittest.mock import patch
        from otto.agents import orchestrator_route
        f = self.f
        prepared = f.app.assign_worker(**f.request())
        current = orchestrator_route.prepare_canonical_assignment_role_brief
        def legacy_packet(**kwargs):
            return current(**{**kwargs, "include_role_context": False, "operating_context_reader": None})
        with patch.object(orchestrator_route, "prepare_canonical_assignment_role_brief", legacy_packet):
            first = f.app.start(schedule_id=prepared["schedule_id"], settle=False)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        self.assertNotIn("introduction", self.packet()["operating_core"])
        self.assertNotIn("supporting_context", self.packet()["context"])
        before = ((f.port.read_due(prepared["schedule_id"])["host_evidence"] or {})["gateway_attempt"])
        settled = f.app.recover(schedule_id=prepared["schedule_id"], execute=False)
        self.assertEqual(settled["outcome"], "succeeded", settled.get("error"))
        after = ((f.port.read_due(prepared["schedule_id"])["host_evidence"] or {})["gateway_attempt"])
        self.assertEqual(after["result"], before["result"])
        self.assertEqual(after["delivery_authorization"], before["delivery_authorization"])
        self.assertEqual(len(f.provider.calls), 1)


if __name__ == "__main__":
    unittest.main()

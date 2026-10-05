"""Evolving owner state through the maintained application, not a test join.

Only the external Codex binding and clock are substituted. Native transcript
evidence is parsed by the real host parser, adapter, gateway and owner runtime.
"""
from datetime import datetime, timezone, timedelta
import json
import hashlib
from pathlib import Path
import tempfile
import socket
import threading
import time
import unittest

from herzchen.adapters.host import _native_host_context, _owner_delivery_appendix
from herzchen.contracts import HostIdentity, HostOutcome, HostReceipt, ResourceRef
from herzchen.content import domain_contribution as content_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.domains.assessment import contribution as assessment_contribution, AssessmentModule
from herzchen.domains.work import Lifecycle, WorkGraph, contributions
from herzchen.kernel.store import Store
from otto.attention import due_record_contribution, issue_store_due_record_port
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.advisor_execution import AdvisorExecution
from otto.portfolio.advisor_delivery import AdvisorDeliveryPorts, ExactSessionDelivery, AdvisorDeliveryError
from otto.host_bridge import DeterministicHostExecutor
from otto.portfolio.advisor_pairing import establish_pairing
from otto.attention import DueRecord, DurableAttention
from herzchen.content.instructions import validate_instruction_content
from herzchen.kernel.limits import LimitService

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def line(kind, payload):
    return json.dumps({"type": kind, "payload": payload}, separators=(",", ":"))


class Provider:
    def __init__(self):
        self.calls = []
        self.contexts = {}
        self.unknown = False
        self.work_started = None
        self.work_release = None

    def binding(self, **kwargs):
        return ProviderBinding(self, kwargs)


class ProviderBinding:
    def __init__(self, provider, options):
        self.provider, self.options = provider, options

    def supports(self, operation):
        return operation.value in {"invoke", "resume"}

    def execute(self, request):
        options = self.options
        session = request.identity.physical_session_id or "provider-session-" + str(len(self.provider.calls) + 1)
        identity = HostIdentity(request.identity.logical_agent_id, session)
        receipt = HostReceipt(request.operation, HostOutcome.SUCCEEDED, identity,
                              identity.logical_agent_id, request.requested_profile)
        if not options.get("delivered_brief"):
            return receipt, {"delivery_state": "done", "host_evidence": {"invocation_turn_verified": True}}
        authorization = options["recipient_authorizer"](request)
        brief = options["delivered_brief"]
        prompt = options["prompt"] + _owner_delivery_appendix(authorization, request.requested_profile)
        self.provider.calls.append(prompt)
        if self.provider.work_started is not None:
            self.provider.work_started.set()
            if not self.provider.work_release.wait(10):
                raise RuntimeError("provider fixture was not released")
        turn = "provider-turn-" + str(len(self.provider.calls))
        callback = options.get("native_start_callback")
        if callback:
            callback(turn, NOW.isoformat())
        if self.provider.unknown:
            return HostReceipt(request.operation, HostOutcome.UNKNOWN, identity,
                               identity.logical_agent_id, request.requested_profile), {"delivery_state": "unknown"}
        lines = [
            line("session_meta", {"session_id": session}),
            line("turn_context", {"turn_id": turn, "model": options["model"],
                "collaboration_mode": {"settings": {"reasoning_effort": options["reasoning"]}},
                "sandbox_policy": {"type": request.requested_profile, "writable_roots": [options["worktree"]]},
                "approval_policy": "never"}),
            line("event_msg", {"type": "item_completed", "turn_id": turn, "thread_id": session,
                "item": {"type": "UserMessage", "id": "input", "content": [{"type": "Text", "text": prompt}]}}),
        ]
        commands = (("test-failed", "failed", 1), ("repair", "completed", 0), ("test-passed", "completed", 0))
        if request.requested_profile == "read-only":
            commands = (("read-context", "completed", 0),)
        for ident, status, code in commands:
            lines.append(line("event_msg", {"type": "item_completed", "turn_id": turn, "thread_id": session,
                "item": {"type": "CommandExecution", "id": ident, "command": ["zsh", "-lc", ident],
                         "cwd": options["worktree"], "parsed_cmd": [{"type": "unknown", "cmd": ident}]
                            if request.requested_profile == "workspace-write" else
                            [{"type": "read", "path": options["worktree"] + "/input.txt"}],
                         "status": status, "exit_code": code, "stdout": ident + "\n", "stderr": "",
                         "aggregated_output": ident + "\n"}}))
        lines.extend([
            line("event_msg", {"type": "item_completed", "turn_id": turn, "thread_id": session,
                "started_at_ms": 100, "completed_at_ms": 110,
                "item": {"type": "AgentMessage", "id": "final", "phase": "final_answer",
                         "content": [{"type": "Text", "text": "Repair complete; tests pass."}]}}),
            line("event_msg", {"type": "task_complete", "turn_id": turn, "completed_at": 1}),
        ])
        context = _native_host_context(lines, request=request, session_id=session, turn_id=turn,
            observed_model=options["model"], observed_reasoning=options["reasoning"],
            worker_content=[], delivered_brief=brief, delivered_authorization=authorization)
        self.provider.contexts[(session, turn)] = context
        return receipt, {"delivery_state": "done", "host_evidence": {
            "turn_id": turn, "otto_host_turn_context": context}, "worker_content": ["Repair complete; tests pass."]}


class ExecutionApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(str(Path(self.temporary.name).resolve())) / "owner.sqlite"
        self.domains = tuple((*contributions(include_assignment_resources=True), content_contribution(),
            packet_contribution(), authoring_contribution(), assessment_contribution(), due_record_contribution()))
        self.store = Store.create(self.path, authority="execution-owner")
        self.store.register_domain_handler(self.domains)
        self.binding = HerzchenBindingConfig("execution-owner", "credential")
        self.actor = self.binding.authenticated_actor("manager")
        graph = WorkGraph(self.store, actor=self.actor)
        self.project = graph.create_project(title="Useful project", logical_request_key="project")
        self.task = graph.create_task(self.project.ref, title="Repair useful task", logical_request_key="task")
        self.provider = Provider()
        self.compose()
        self.addCleanup(lambda: self.store.close())

    def compose(self, owner_actor="manager", manager_actor=None):
        issuer = self.binding.authenticated_actor(owner_actor)
        owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor=owner_actor,
            project_read_grant=ProjectReadGrant(issuer, (self.project.id,), "test-host", "v1"))
        self.port = issue_store_due_record_port(self.store.domain_handler((due_record_contribution(),)), issuer)
        adapter = HerzchenCodexAdapter(owner="worker", source=str(Path(self.temporary.name).resolve()), worktree=str(Path(self.temporary.name).resolve()),
            launcher="provider-fixture", requested_model="gpt-test", requested_reasoning="high",
            require_host_context=True, binding_factory=self.provider.binding,
            turn_context_reader=lambda session, turn: self.provider.contexts.get((session, turn)))
        self.app = owner.execution_application(due_port=self.port, adapter=adapter, clock=lambda: NOW, manager_actor=manager_actor)
        self.owner = owner

    def request(self):
        return dict(project_ref=self.project.ref.to_dict(), task_ref=self.task.ref.to_dict(),
            principal="worker", request_key="first-worker", instructions="Repair task; run a focused check; return changed files.",
            model="gpt-test", reasoning="high",
            brief={"role": "worker", "mandate": "Repair useful task", "links": []},
            instruction_contract={"task_ref": self.task.ref.to_dict(), "objective": "Repair useful task",
                "bounded_operation": "Repair and test the task", "allowed_operations": ["read_project_context", "edit_candidate_workspace", "run_focused_tests", "return_progress"],
                "acceptance_criteria": ["Tests pass and changed paths are reported"],
                "authority": {"source": "canonical_owner", "owner_actor": "worker", "gateway_claim_required": True,
                    "owner_write": False, "dispatch": False, "effect_profile": "workspace-write-worker",
                    "workspace_roots": [str(Path(self.temporary.name).resolve())],
                    "permitted_effects": ["read_delivered_context", "read_linked_sources", "file_write_in_workspace", "return_result"],
                    "forbidden_effects": ["owner_write", "publication", "package_adoption", "remote_push", "release", "deployment"]}})

    def test_assign_run_repair_publish_restart_and_same_request_duplicate(self):
        result = self.app.assign_and_start(**self.request())
        self.assertEqual(result["outcome"], "succeeded", result)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertIn(self.request()["instructions"], self.provider.calls[0])
        due = self.port.read_due(result["schedule_id"])
        self.assertEqual(due["completion_state"], "succeeded")
        records = self.app.assignments.list_observations(ResourceRef.from_dict(result["assignment_ref"]), kind="result")
        self.assertEqual(len(records), 1)
        self.assertIn("test-failed", json.dumps(records[0].value))
        self.store.close()
        self.store = Store.open(self.path, authority="execution-owner", expected_domains=tuple(sorted(self.domains, key=lambda d: d.domain_id)))
        self.compose()
        duplicate = self.app.assign_and_start(**self.request())
        self.assertEqual(duplicate["outcome"], "replayed")
        self.assertEqual(len(self.provider.calls), 1)

    def test_worker_preparation_reads_document_revision_when_response_omits_record(self):
        original = self.app.portfolio.create_document

        def without_record(*args, **kwargs):
            result = original(*args, **kwargs)
            result.pop("record", None)
            return result

        self.app.portfolio.create_document = without_record
        prepared = self.app.assign_worker(**self.request())
        self.assertEqual(prepared["outcome"], "committed", prepared)
        self.assertEqual(prepared["guide_ref"]["revision"], "rev-1")
        self.assertEqual(prepared["mandate_ref"]["revision"], "rev-1")
        self.assertEqual(self.provider.calls, [])

    def test_inspected_worker_result_closes_task_through_public_manager_acceptance(self):
        result = self.app.assign_and_start(**self.request())
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        observations = self.app.assignments.list_observations(ResourceRef.from_dict(result["assignment_ref"]), kind="result")
        manager, _guide, _mandate = self.role_handles("manager", "manager", "manager-session")
        assessment = AssessmentModule(self.store, actor=self.actor)
        scope = assessment.declare_scope("worker-completion-gate", parent_obligation=self.task.ref,
            protocol="focused-verification", criteria=[{"id": "worker-result-tested", "definition": "Failed command repaired and focused checks passed"}],
            designated_approver="manager", policy={"required_for_completion": True}, logical_request_key="worker-gate-scope")
        packet = assessment.freeze_input(scope.ref, packet={"result": observations[0].value},
            consumed_refs=[observations[0].ref], logical_request_key="worker-gate-input")
        limits = LimitService(self.store)
        pool = limits.create_pool(ResourceRef("execution-owner", "limit", "worker-review-pool"),
            capacity_units=1, cumulative_allowance_units=1, logical_request_key="worker-review-allowance", actor=self.actor)
        reviewed = assessment.assess(scope.ref, candidate=observations[0].ref, criterion=scope.criterion_refs[0],
            input_packet=packet.ref, verdict="PASS", limit_pool=pool.ref, logical_request_key="worker-inspected-review")
        decision = assessment.accept(reviewed.ref, rationale="Inspected-failure-repair-and-passing-checks",
            evidence_refs=[observations[0].ref], logical_request_key="manager-accept-worker-review")
        digest = hashlib.sha256(json.dumps(observations[0].value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        request = dict(actor="manager", request_id="accept-inspected-worker", expected_generation=1,
            expected_project_revision=self.project.revision, expected_task_revision=self.task.revision,
            disposition="accepted", evidence_refs=[observations[0].ref.to_dict()], evidence_hashes={"native-result": digest},
            gate_refs=[decision.ref.to_dict()], candidate_ref=observations[0].ref.to_dict())
        accepted = self.app.portfolio.complete_task(self.project.ref.to_dict(), self.task.ref.to_dict(),
            manager.ref.to_dict(), **request)
        self.assertEqual(accepted["outcome"], "completed", accepted)
        self.assertEqual(accepted["completion"]["assessment_gate_check"]["blockers"], [])
        replay = self.app.portfolio.complete_task(self.project.ref.to_dict(), self.task.ref.to_dict(),
            manager.ref.to_dict(), **request)
        self.assertEqual(replay["outcome"], "replayed", replay)
        record = self.app.portfolio.operations.reader.get_record(ResourceRef(self.task.ref.authority,self.task.ref.kind,self.task.id))
        self.assertEqual(record.payload["lifecycle"], "completed")
        self.assertEqual(len(self.provider.calls), 1)

    def test_prepared_instruction_is_durable_and_cannot_change_after_native_effect(self):
        prepared = self.app.assign_worker(**self.request())
        self.app.prepare_instruction(schedule_id=prepared["schedule_id"], request_key="final-worker-prompt",
            instruction="Inspect preserved edits, repair the remaining failure, and return exact paths.")
        self.compose()
        result = self.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        self.assertIn("Inspect preserved edits", self.provider.calls[0])
        with self.assertRaisesRegex(ValueError, "cannot be changed"):
            self.app.prepare_instruction(schedule_id=prepared["schedule_id"], request_key="late-change",
                instruction="Different operation after delivery")
        self.assertEqual(len(self.provider.calls), 1)

    def test_unknown_provider_effect_is_durable_and_not_replayed(self):
        self.provider.unknown = True
        result = self.app.assign_and_start(**self.request())
        self.assertNotEqual(result["outcome"], "succeeded")
        recovered = self.app.recover(schedule_id=result["schedule_id"], execute=True)
        self.assertNotEqual(recovered["outcome"], "succeeded")
        self.assertEqual(len(self.provider.calls), 1)

    def test_changed_input_on_same_request_is_rejected_before_provider(self):
        result = self.app.assign_worker(**self.request())
        self.assertEqual(result["outcome"], "committed", result)
        changed = {**self.request(), "instructions": "Different task intent"}
        with self.assertRaisesRegex(ValueError, "changed worker input"):
            self.app.assign_and_start(**changed)
        self.assertEqual(self.provider.calls, [])

    def test_partial_preparation_reuses_committed_assignment_after_clock_failure(self):
        def interrupted_clock():
            raise RuntimeError("owner interrupted after mandate commit")
        self.app.clock = interrupted_clock
        partial = self.app.assign_worker(**self.request())
        self.assertEqual(partial["outcome"], "partial")
        self.assertEqual(partial["stage"], "due")
        self.assertIn("assignment_ref", partial)
        self.assertIn("mandate_ref", partial)
        self.assertEqual(self.provider.calls, [])
        self.compose()
        repaired = self.app.assign_and_start(**self.request())
        self.assertEqual(repaired["outcome"], "succeeded", repaired.get("error"))
        self.assertEqual(repaired["assignment_ref"], partial["assignment_ref"])
        self.assertEqual(len(self.provider.calls), 1)

    def test_correction_resumes_exact_native_session_and_delivers_fresh_delta(self):
        first = self.app.assign_and_start(**self.request())
        corrected = self.app.correct_worker(schedule_id=first["schedule_id"],
            request_key="correction-1", instruction="Add the missing boundary case and return fresh checks.")
        self.assertEqual(corrected["outcome"], "succeeded", corrected.get("error"))
        self.assertEqual(corrected["result"]["physical_session_id"], first["result"]["physical_session_id"])
        self.assertIn("Add the missing boundary case", self.provider.calls[-1])
        duplicate = self.app.correct_worker(schedule_id=first["schedule_id"],
            request_key="correction-1", instruction="Add the missing boundary case and return fresh checks.")
        self.assertEqual(duplicate["outcome"], "replayed")
        self.assertEqual(len(self.provider.calls), 2)

    def test_parent_finishes_while_child_keeps_command_status_and_result_custody(self):
        self.provider.work_started, self.provider.work_release = threading.Event(), threading.Event()
        directory = Path(str(Path(self.temporary.name).resolve())) / "ipc"
        results = []
        def handle(request):
            if request["command"] == "status":
                return {"outcome": "active", "occurrences": len(self.port.list_due())}
            return self.app.assign_and_start(**self.request())
        host = ExecutionHost(directory=directory, handler=handle, owner_path=directory / "owner.json")
        host.start()
        host.retain(name="useful-child", operation=lambda: results.append(handle({"command": "run"})))
        self.assertTrue(self.provider.work_started.wait(5))
        closing = threading.Thread(target=host.close)
        closing.start()
        try:
            (directory / "request-abc123.json").write_text(json.dumps({"command": "status"}))
            deadline = time.monotonic() + 5
            response = directory / "response-abc123.json"
            while not response.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(json.loads(response.read_text())["outcome"], "active")
            self.assertTrue(closing.is_alive())
        finally:
            self.provider.work_release.set()
            closing.join(10)
        self.assertFalse(closing.is_alive())
        self.assertEqual(results[0]["outcome"], "succeeded", results[0].get("error"))
        self.assertFalse((directory / "owner.json").exists())

    def test_restarted_file_host_recovers_pending_same_request_without_provider_replay(self):
        first = self.app.assign_and_start(**self.request())
        directory = Path(str(Path(self.temporary.name).resolve())) / "ipc"
        directory.mkdir()
        (directory / "request-abc123.json").write_text(json.dumps({"command": "run"}))
        with ExecutionHost(directory=directory, handler=lambda _request: self.app.assign_and_start(**self.request())):
            deadline = time.monotonic() + 5
            response = directory / "response-abc123.json"
            while not response.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            result = json.loads(response.read_text())
        self.assertEqual(result["schedule_id"], first["schedule_id"])
        self.assertEqual(result["outcome"], "replayed")
        self.assertEqual(len(self.provider.calls), 1)

    def role_handles(self, role, principal, session):
        prepared = self.app.assign_worker(**self.request())
        guide = ResourceRef.from_dict(prepared["guide_ref"])
        content = self.owner.content.read(guide)["content"]
        assignments = self.owner.assignments.command_port
        base = assignments.assign(self.project.ref, role=role, principal=principal,
            manager="manager", session=session, pins=[guide], logical_request_key=role + ":assign", actor=self.actor)
        assigned = assignments.adopt_resources(base.ref,
            resources=[{"resource_ref": guide.to_dict(), "resource_name": content["name"],
                        "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=base.revision, expected_generation=base.generation,
            logical_request_key=role + ":adopt", actor=self.actor)
        contract = self.request()["instruction_contract"]
        contract["authority"]["owner_actor"] = principal
        if role == "manager":
            contract["authority"]["effect_profile"] = "workspace-write-manager"
            contract["allowed_operations"].append("canonical_manager_commands")
            contract["authority"]["permitted_effects"].append("canonical_manager_commands")
        else:
            contract["read_scope"] = "linked_context"
            contract["allowed_operations"] = ["read_project_context", "return_advice"]
            contract["authority"].pop("effect_profile")
            contract["authority"].pop("workspace_roots")
            contract["authority"]["permitted_effects"] = ["read_delivered_context", "read_linked_sources", "return_advice"]
            contract["authority"]["forbidden_effects"].append("file_write")
        mandate = self.app.portfolio.create_document(self.project.ref.to_dict(), actor="manager",
            request_id=role + ":mandate", document_id=role + "-mandate", role="mandate",
            content={"role": role, "scope_ref": self.project.ref.to_dict(), "status": "active",
                "dispatch_enabled": True, "task_ref": self.task.ref.to_dict(),
                "assignment_ref": assigned.ref.to_dict(), "generation": assigned.generation,
                "brief": {"role": role, "mandate": "Advance useful project"}, "instruction_contract": contract})
        return assigned, guide.to_dict(), mandate["record"]["payload"]["current_revision"]

    def test_manager_continuation_is_rebuilt_from_canonical_report_after_restart(self):
        assignment, guide, mandate = self.role_handles("manager", "manager", "manager-session")
        prepared = self.app.prepare_role(role="manager", project_ref=self.project.ref.to_dict(),
            task_ref=self.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="manager-turn",
            instruction="Inspect the worker result and select the next task.", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        first = self.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        self.app.assignments.append_report(assignment.ref,
            {"schema": "otto.manager-progress.v1", "project_ref": self.project.ref.to_dict(),
             "task_alias": "task", "continue_requested": True, "next_action": "Start the next useful task from its current brief.",
             "logical_request_key": "manager-next", "recorded_at": NOW.isoformat()},
            expected_generation=1, logical_request_key="manager-report", actor=self.actor)
        self.compose()
        callback = self.app.continue_manager(schedule_id=first["schedule_id"], execute=False)
        self.assertEqual(callback["outcome"], "committed", callback)
        self.compose()
        continued = self.app.continue_manager(schedule_id=first["schedule_id"])
        self.assertEqual(continued["outcome"], "succeeded", continued.get("error"))
        self.assertEqual(continued["result"]["physical_session_id"], "manager-session")
        self.assertIn("Start the next useful task", self.provider.calls[-1])
        replay = self.app.continue_manager(schedule_id=first["schedule_id"])
        self.assertEqual(replay["schedule_id"], continued["schedule_id"])
        self.assertEqual(len(self.provider.calls), 2)

    def test_retained_manager_settlement_uses_the_same_normalized_contract_as_admission(self):
        original = self.app.portfolio.create_document
        def authored_whitespace(*args, **kwargs):
            content = kwargs.get("content")
            if isinstance(content, dict) and content.get("role") == "manager":
                kwargs = {**kwargs, "content": {**content, "instruction_contract": {
                    **content["instruction_contract"],
                    "bounded_operation": content["instruction_contract"]["bounded_operation"] + "\n"}}}
            return original(*args, **kwargs)
        self.app.portfolio.create_document = authored_whitespace
        assignment, guide, mandate = self.role_handles("manager", "manager", "manager-session")
        prepared = self.app.prepare_role(role="manager", project_ref=self.project.ref.to_dict(),
            task_ref=self.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="raw-manager-contract",
            instruction="Record useful progress and return", model="gpt-test", reasoning="high",
            profile="workspace-write", native_session_id="manager-session")
        result = self.app.start(schedule_id=prepared["schedule_id"], settle=False)
        self.assertEqual(result["outcome"], "succeeded", result)
        before = self.port.read_due(prepared["schedule_id"])
        retained = before["host_evidence"]["gateway_attempt"]["result"]
        self.assertEqual(before["completion_state"], "none")
        self.assertTrue(self.owner.content.read(ResourceRef.from_dict(mandate))["content"]
            ["instruction_contract"]["bounded_operation"].endswith("\n"))
        self.assertFalse(retained["resource_evidence"]["brief"]["instruction_contract"]
            ["bounded_operation"].endswith("\n"))
        self.compose()
        settled = self.app.recover(schedule_id=prepared["schedule_id"], execute=False)
        self.assertEqual(settled["outcome"], "succeeded", settled)
        after = self.port.read_due(prepared["schedule_id"])
        self.assertEqual(after["host_evidence"]["gateway_attempt"]["result"], retained)
        self.assertEqual(after["stop_state"], "completed")
        self.assertEqual(self.app.recover(schedule_id=prepared["schedule_id"], execute=False)["outcome"], "replayed")
        self.assertEqual(len(self.provider.calls), 1)

    def advisor_fixture(self):
        manager, _guide, _mandate = self.role_handles("manager", "manager", "manager-session")
        advisor, guide, mandate = self.role_handles("project_advisor", "advisor", "advisor-session")
        def pairing(_project):
            values = [self.app.assignments.get(value.ref) for value in (manager, advisor)]
            return establish_pairing(self.project.ref.to_dict(),
                [{**dict(value.payload), "ref": value.ref.to_dict()} for value in values],
                manager_conversation_ref={"host": "local", "native_id": "manager-session"},
                advisor_conversation_ref={"host": "local", "native_id": "advisor-session"})
        current = pairing(None)
        attention = DurableAttention(self.owner.shared_attention_port(due_port=self.port),
            due_port=self.port, clock=lambda: NOW, host_mode="awaited")
        attention.schedule(DueRecord(schedule_id="existing-advisor-followup", recipient="advisor",
            instruction="Inspect the delivered effect", profile="read-only", anchor=NOW.isoformat(),
            due_at=NOW.isoformat(), last_covered_slot=-1, invocation_identity="existing-advisor-followup-v1",
            project_ref=self.project.id, manager_ref="manager", assignment_ref=advisor.ref.to_dict(), generation=1,
            target={"host": "local", "native_id": "advisor-session", "assignment_ref": advisor.ref.to_dict(),
                    "role": "project_advisor", "principal": "advisor"},
            role="project_advisor", purpose="advisor-effect-followup", lifecycle_owner="manager"), request_id="schedule-followup")
        limits = LimitService(self.store)
        pool = limits.create_pool(ResourceRef("execution-owner", "limit", "adopted-advisor-pool"),
            capacity_units=1, cumulative_allowance_units=3, logical_request_key="adopt-allowance", actor=self.actor)
        for index in range(2):
            reservation = limits.reserve(pool.ref, "prior-turn-" + str(index), 1,
                logical_request_key="prior-reserve-" + str(index), actor=self.actor)
            limits.settle(reservation, 1, logical_request_key="prior-settle-" + str(index), actor=self.actor)
        ports = AdvisorDeliveryPorts(assignments=self.app.assignments, attention=attention,
            authenticate=self.binding.authenticated_actor, current_pairing=pairing,
            reports_for_project=lambda _project: [], role_delivery=lambda _delivery: None, now=lambda: NOW)
        integration = AdvisorExecution(execution=self.app, ports=ports, allowance=limits,
                                       allowance_ref=pool.ref.to_dict())
        prepared = integration.prepare_scheduled(pairing=current, schedule_id="existing-advisor-followup",
            task_ref=self.task.ref.to_dict(), mandate_ref=mandate, context_refs=(guide, mandate),
            prompt="Inspect decision effect independently using fresh source and manager reports.",
            model="gpt-test", reasoning="high", profile="read-only")
        self.assertEqual(prepared["outcome"], "reconfigured", prepared)
        return integration, current, advisor, limits, pool

    def test_scheduled_advisor_joins_real_attention_adoption_allowance_runtime_and_settlement(self):
        integration, current, advisor, limits, pool = self.advisor_fixture()
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 2)
        result = integration.wake_once(pairing=current, schedule_id="existing-advisor-followup",
            advisor_principal="advisor", lifecycle_owner="manager", reason="scheduled-effect-followup")
        self.assertEqual(result["outcome"], "returned", {k: result.get(k) for k in ("outcome", "error")})
        self.assertEqual(len(self.provider.calls), 1)
        final = self.port.read_due("existing-advisor-followup")
        self.assertEqual(final["assignment_ref"], advisor.ref.to_dict())
        self.assertEqual(final["completion_state"], "succeeded")
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 3)
        self.assertEqual(limits.get_pool(pool.ref).held_units, 0)
        self.assertEqual(len(self.owner.shared_attention_port(due_port=self.port).list_attention("advisor")), 1)
        replay = integration.wake_once(pairing=current, schedule_id="existing-advisor-followup",
            advisor_principal="advisor", lifecycle_owner="manager", reason="scheduled-effect-followup")
        self.assertFalse(replay["runtime_called"])
        self.assertEqual(len(self.provider.calls), 1)

    def test_ordinary_advisor_launch_resume_and_replay_share_one_allowance_owner(self):
        advisor, guide, mandate = self.role_handles("project_advisor", "advisor", None)
        limits = LimitService(self.store)
        pool = limits.create_pool(ResourceRef("execution-owner", "limit", "ordinary-advisor-pool"),
            capacity_units=1, cumulative_allowance_units=2, logical_request_key="ordinary-pool", actor=self.actor)
        integration = AdvisorExecution(execution=self.app, allowance=limits, allowance_ref=pool.ref.to_dict())
        request = dict(project_ref=self.project.ref.to_dict(), task_ref=self.task.ref.to_dict(),
            assignment_ref=advisor.ref.to_dict(), generation=1, mandate_ref=mandate,
            context_refs=(guide, mandate), request_key="ordinary-start", instruction="Inspect the useful project.",
            model="gpt-test", reasoning="high", profile="read-only")
        first = integration.prepare_and_start(**request)
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 1)
        self.compose()
        integration.execution = self.app
        duplicate = integration.prepare_and_start(**request)
        self.assertEqual(duplicate["outcome"], "replayed")
        self.assertEqual(len(self.provider.calls), 1)
        second = integration.prepare_and_start(**{**request, "request_key": "ordinary-followup",
            "instruction": "Inspect the newly reported manager effect.",
            "native_session_id": first["result"]["physical_session_id"], "binding_schedule_id": first["schedule_id"]})
        self.assertEqual(second["outcome"], "succeeded", second.get("error"))
        self.assertEqual(second["result"]["physical_session_id"], first["result"]["physical_session_id"])
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 2)
        self.assertEqual(limits.get_pool(pool.ref).held_units, 0)
        self.assertEqual(len(self.provider.calls), 2)

    def test_retained_native_advisor_binding_survives_adoption_but_rejects_reassignment(self):
        advisor, guide, mandate = self.role_handles("project_advisor", "advisor", None)
        prepared = self.app.prepare_role(role="project_advisor", project_ref=self.project.ref.to_dict(),
            task_ref=self.task.ref.to_dict(), assignment_ref=advisor.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key="binding-start",
            instruction="Inspect the current source.", model="gpt-test", reasoning="high", profile="read-only")
        first = self.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(first["outcome"], "succeeded", first.get("error"))
        due = self.port.read_due(prepared["schedule_id"])
        due["host_evidence"]["gateway_attempt"].pop("delivery_admission", None)
        self.port.save_due(prepared["schedule_id"], due, request_id="retain-legacy-native-format", expected_version=due["version"])
        current = self.app.assignments.adopt_resources(advisor.ref,
            resources=advisor.payload["resource_adoptions"], expected_revision=advisor.revision,
            expected_generation=1, logical_request_key="refresh-advisor-instructions", actor=self.actor)
        self.assertNotEqual(current.ref, advisor.ref)
        content = self.owner.content.read(ResourceRef.from_dict(mandate))["content"]
        content["assignment_ref"] = current.ref.to_dict()
        updated = self.app.portfolio.create_document(self.project.ref.to_dict(), actor="manager",
            request_id="refresh-advisor-mandate", document_id="refreshed-advisor-mandate", role="mandate", content=content)
        new_mandate = updated["record"]["payload"]["current_revision"]
        request = dict(role="project_advisor", project_ref=self.project.ref.to_dict(), task_ref=self.task.ref.to_dict(),
            assignment_ref=current.ref.to_dict(), generation=1, mandate_ref=new_mandate,
            context_refs=(guide, new_mandate), request_key="binding-after-adoption", instruction="Inspect the revised instructions.",
            model="gpt-test", reasoning="high", profile="read-only", native_session_id=first["result"]["physical_session_id"],
            binding_schedule_id=prepared["schedule_id"])
        resumed = self.app.prepare_role(**request)
        result = self.app.start(schedule_id=resumed["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        reassigned = self.app.assignments.reassign(current.ref, principal="different-advisor", expected_generation=1,
            logical_request_key="replace-advisor", actor=self.actor)
        with self.assertRaisesRegex(ValueError, "binding"):
            self.app.prepare_role(**{**request, "assignment_ref": reassigned.ref.to_dict(),
                "generation": reassigned.generation, "request_key": "stale-native-binding"})
        self.assertEqual(len(self.provider.calls), 2)

    def test_advisor_unknown_effect_retains_allowance_through_restart_and_does_not_repeat(self):
        integration, current, _advisor, limits, pool = self.advisor_fixture()
        self.provider.unknown = True
        result = integration.wake_once(pairing=current, schedule_id="existing-advisor-followup",
            advisor_principal="advisor", lifecycle_owner="manager", reason="scheduled-effect-followup")
        self.assertNotEqual(result["outcome"], "returned", result)
        self.assertEqual(limits.get_pool(pool.ref).held_units, 1)
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 2)
        self.compose()
        integration.execution = self.app
        for _ in range(2):
            integration.reconcile_allowance(schedule_id="existing-advisor-followup")
        replay = integration.wake_once(pairing=current, schedule_id="existing-advisor-followup",
            advisor_principal="advisor", lifecycle_owner="manager", reason="scheduled-effect-followup")
        self.assertFalse(replay["runtime_called"])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(limits.get_pool(pool.ref).held_units, 1)

    def test_advisor_stale_recipient_is_rejected_before_provider_or_allowance(self):
        integration, current, _advisor, limits, pool = self.advisor_fixture()
        with self.assertRaisesRegex(AdvisorDeliveryError, "recipient_mismatch"):
            integration.wake_once(pairing=current, schedule_id="existing-advisor-followup",
                advisor_principal="foreign-advisor", lifecycle_owner="manager", reason="scheduled-effect-followup")
        self.assertEqual(len(self.provider.calls), 0)
        self.assertEqual(limits.get_pool(pool.ref).held_units, 0)
        self.assertEqual(limits.get_pool(pool.ref).cumulative_used_units, 2)

    def test_owner_custody_is_distinct_from_assignment_manager(self):
        self.compose(owner_actor="custodian", manager_actor="manager")
        prepared = self.app.assign_worker(**self.request())
        self.assertEqual(prepared["outcome"], "committed", prepared.get("error"))
        current = self.app.assignments.get(ResourceRef.from_dict(prepared["assignment_ref"]))
        self.assertEqual(current.payload["manager"], "manager")
        due = self.port.read_due(prepared["schedule_id"])
        self.assertEqual(due["lifecycle_owner"], "custodian")
        result = self.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))

    def test_compatible_socket_host_retains_service_and_refuses_a_competing_owner(self):
        directory = Path(self.temporary.name) / "socket-command-ipc"
        socket_path = Path(self.temporary.name) / "service.sock"
        host = ExecutionHost(directory=directory, socket_path=socket_path,
            handler=lambda request: {"outcome": "read", "command": request["command"]})
        with self.assertRaisesRegex(RuntimeError, "must be started"):
            host.retain(name="unserved-child", operation=lambda: None)
        host.start()
        try:
            unused = ExecutionHost(directory=directory, handler=lambda request: {})
            unused.close()
            self.assertTrue(host.owner_path.exists())
            competing = ExecutionHost(directory=directory, socket_path=socket_path, handler=lambda request: {})
            with self.assertRaisesRegex(RuntimeError, "another execution host"):
                competing.start()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(socket_path))
                client.sendall(b'{"command":"status"}\n')
                response = json.loads(client.recv(4096))
            self.assertEqual(response["outcome"], "read")
        finally:
            host.close()
        self.assertFalse(socket_path.exists())
        self.assertFalse(host.owner_path.exists())

    def test_manager_message_uses_exact_native_admission_and_restart_identity(self):
        assignment, guide, mandate = self.role_handles("manager", "manager", "manager-session")
        delivery = {"delivery_id": "canonical-advisor-decision", "logical_request_key": "decision-delivery",
            "physical_session_id": "manager-session", "recipient": {"host": "local", "native_id": "manager-session"},
            "message": {"decision_id": "decision", "text": "Apply the inspected repair and report its effect."}}
        def prepare(value):
            return self.app.prepare_manager_delivery(delivery=value, project_ref=self.project.ref.to_dict(),
                task_ref=self.task.ref.to_dict(), assignment_ref=assignment.ref.to_dict(), generation=1,
                mandate_ref=mandate, context_refs=(guide, mandate), model="gpt-test", reasoning="high")
        prepared = prepare(delivery)
        self.assertEqual(prepared["outcome"], "committed", prepared)
        self.compose()
        self.app.clock = lambda: NOW + timedelta(minutes=5)
        result = self.app.start(schedule_id=prepared["schedule_id"])
        self.assertEqual(result["outcome"], "succeeded", result.get("error"))
        due = self.port.read_due(prepared["schedule_id"])
        self.assertEqual(due["delivered_at"], NOW.isoformat())
        self.assertNotEqual(due["delivered_at"], due["completed_at"])
        self.assertIn(delivery["message"]["text"], self.provider.calls[0])
        admission = due["host_evidence"]["gateway_attempt"]["delivery_admission"]
        exact = ExactSessionDelivery(continue_session=lambda _request: {"delivery_admission": admission},
            read_session_delivery=lambda _id: {"delivery_admission": admission})
        sent = exact.send(delivery)
        self.assertEqual(sent["state"], "sent", sent)
        self.compose()
        replay = prepare(delivery)
        self.app.start(schedule_id=replay["schedule_id"])
        self.assertEqual(len(self.provider.calls), 1)
        changed = {**delivery, "message": {"text": "Changed input"}}
        with self.assertRaisesRegex(ValueError, "differs"):
            prepare(changed)

    def test_host_trigger_pause_restart_and_stop_preserve_canonical_identity(self):
        integration, _current, _advisor, _limits, _pool = self.advisor_fixture()
        attention = integration.loop.ports.attention
        schedule = "existing-advisor-followup"
        due = self.port.read_due(schedule)
        automation = {"id": "existing-automation", "name": "Advisor followup", "kind": "heartbeat",
            "prompt": "Inspect the current advisor schedule and dispatch only its authorized occurrence.",
            "rrule": "FREQ=HOURLY;INTERVAL=1", "status": "ACTIVE", "targetThreadId": "owner-native-thread"}
        due["target"]["automation"] = automation
        self.port.save_due(schedule, due, request_id="adopt-existing-host-target", expected_version=due["version"])
        settings, mutations = {}, []
        def update(request):
            mutations.append(request)
            settings.clear()
            settings.update(request)
            return {"id": request["id"]}
        def executor():
            return DeterministicHostExecutor(update, lambda effect, _response: {**settings, "state": settings["status"].lower()},
                lambda effect, observation: attention.acknowledge_host(effect.schedule_id,
                    request_id=effect.request_id, observed=observation, actor="manager"))
        first = ExecutionHost.reconcile_trigger(attention=attention, executor=executor(), schedule_id=schedule,
            request_id="pause-existing", actor="manager", desired_state="paused")
        self.assertEqual(first["outcome"], "reconciled", first)
        self.assertEqual(self.port.read_due(schedule)["host_state"], "paused")
        replay = ExecutionHost.reconcile_trigger(attention=attention, executor=executor(), schedule_id=schedule,
            request_id="pause-existing", actor="manager", desired_state="paused")
        self.assertEqual(replay["outcome"], "reconciled", replay)
        self.assertEqual(len(mutations), 1)
        active = ExecutionHost.reconcile_trigger(attention=attention, executor=executor(), schedule_id=schedule,
            request_id="resume-existing", actor="manager")
        self.assertEqual(active["outcome"], "reconciled", active)
        self.assertEqual(len(mutations), 2)
        foreign = ExecutionHost.reconcile_trigger(attention=attention, executor=executor(), schedule_id=schedule,
            request_id="foreign-pause", actor="foreign", desired_state="paused")
        self.assertEqual(foreign["outcome"], "rejected")
        stopped = attention.stop(schedule, request_id="stop-existing")
        self.assertEqual(stopped["outcome"], "stopped", stopped)
        self.assertEqual(self.port.read_due(schedule)["stop_state"], "stopped")
        terminal = ExecutionHost.reconcile_trigger(attention=attention, executor=executor(), schedule_id=schedule,
            request_id="reactivate-stopped", actor="manager")
        self.assertEqual(terminal["outcome"], "rejected")
        self.assertEqual(terminal["error"]["code"], "schedule_stopped")
        self.assertEqual(len(self.provider.calls), 0)


if __name__ == "__main__":
    unittest.main()

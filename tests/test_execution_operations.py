from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from otto.attention import DueRecord

from otto.portfolio.execution_operations import (
    OccurrencePreparationError,
    build_manager_callback_due,
    compact_operation_status,
    compact_project_status,
    commit_local_checkpoint,
    derive_manager_continuation_request,
    prepare_current_assignment_occurrence,
    recheck_execution_admission,
    read_project_progress_reports,
    validate_owner_timeout_seconds,
)


REF = {"authority": "owner", "kind": "wrk.assignment", "id": "a", "revision": "rev-2"}
BASE = {**REF, "revision": "rev-1"}


@dataclass(frozen=True)
class Due:
    schedule_id: str = "due-1"
    assignment_ref: dict | None = None
    target: dict | None = None
    execution_mode: str = "continue_existing"
    role: str = "worker"
    timeout_seconds: int = 1200
    def to_dict(self): return vars(self)


class Ref:
    def __init__(self, value): self.value = value
    def to_dict(self): return dict(self.value)


class Assignment:
    ref = Ref(REF)
    payload = {"resource_adoption_base_ref": BASE}
    manager = "manager"
    principal = "worker"


class PayloadOwnedAssignment:
    ref = Ref(REF)
    payload = {"resource_adoption_base_ref": BASE, "manager": "manager", "principal": "advisor"}
    manager = None
    principal = "advisor"


class PayloadOwnedAssignments:
    def get(self, ref): return PayloadOwnedAssignment()


class Assignments:
    def get(self, ref): return Assignment()


class Binding:
    def authenticated_actor(self, actor): return type("Actor", (), {"actor": actor})()


class DuePort:
    def __init__(self, fail=False): self.fail, self.saved = fail, 0
    def save_due(self, schedule, value, **kwargs):
        self.saved += 1
        return {"version": 1}
    def reconcile_assignment_resources(self, schedule, **kwargs):
        if self.fail: raise RuntimeError("stale current assignment")
        return {"version": 2}


class Tests(unittest.TestCase):
    def due(self): return Due(assignment_ref=BASE, target={"assignment_ref": BASE, "native_id": "session"})

    def _worker_admission_fixture(self, *, admitted=True, revision_available=True,
                                  project_dependency=None, task_blocked=False):
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import authoring_stamp

        project_ref = {"authority": "owner", "kind": "work.project", "id": "p", "revision": "p-2"}
        task_ref = {"authority": "owner", "kind": "work.task", "id": "t", "revision": "t-2"}
        portfolio_ref = {"authority": "owner", "kind": "wrk.portfolio", "id": "portfolio"}
        upstream_ref = {"authority": "owner", "kind": "work.project", "id": "upstream", "revision": "u-1"}
        gate_ref = {"authority": "owner", "kind": "work.gate", "id": "gate", "revision": "g-1"}

        class Record:
            def __init__(self, ref, payload):
                self.ref, self.payload = ResourceRef.from_dict(ref), payload

        dependencies = [gate_ref] if project_dependency == "gate" else (
            [upstream_ref] if project_dependency == "project" else [])
        project = Record(project_ref, {"dependencies": dependencies, "metadata": {"otto_orchestrator": {
            "portfolio_ref": portfolio_ref, "project_ref": project_ref,
        }}})
        upstream = Record(upstream_ref, {"dependencies": [], "lifecycle": "active",
            "metadata": {"otto_orchestrator": {"portfolio_ref": portfolio_ref,
                "project_ref": upstream_ref}}})
        gate = Record(gate_ref, {"project_ref": upstream_ref, "lifecycle": "active"})
        task_payload = {"project_ref": project_ref,
            "dependencies": [gate_ref] if task_blocked else [], "title": "admitted task"}
        task_payload["metadata_namespaces"] = {
            "work.admission": authoring_stamp("t-1", task_payload, "reviewer")}
        if not admitted:
            task_payload["title"] = "changed after admission"
        task = Record(task_ref, task_payload)
        reviewed = Record({**task_ref, "revision": "t-1"}, task_payload)

        class Reader:
            def get_record(self, ref):
                if ref.id == "p": return project
                if ref.id == "upstream": return upstream
                if ref.id == "gate": return gate
                if ref.id == "t": return task
                return None
            def get_revision(self, ref):
                return reviewed if revision_available and ref.id == "t" and ref.revision == "t-1" else None

        class Graph:
            def list(self, **kwargs): return []

        current = SimpleNamespace(ref=SimpleNamespace(to_dict=lambda: REF), payload={})
        binding = SimpleNamespace(authenticated_actor=lambda actor: actor)
        operations = SimpleNamespace(_owner_reader=Reader(), port=Graph(), dependency_owner_actor=None)
        app = SimpleNamespace(
            _current=lambda ref, generation: current,
            portfolio=SimpleNamespace(operations=operations),
            binding=binding, actor="manager",
        )
        due = SimpleNamespace(
            role="worker", schedule_id="worker-due", generation=1,
            assignment_ref=REF,
            target={"project_ref": project_ref, "task_ref": task_ref},
        )
        return app, due, project, task

    def test_last_moment_worker_admission_rechecks_current_assignment_and_dependencies(self):
        app, due, _, _ = self._worker_admission_fixture()
        snapshot = recheck_execution_admission(app, due)
        self.assertEqual(snapshot["worker_readiness"], "ready")
        self.assertEqual(snapshot["task_ref"]["id"], "t")

        for options, message in (({"admitted": False}, "admission"),
                                 ({"revision_available": False}, "admission"),
                                 ({"project_dependency": "project"}, "dependencies"),
                                 ({"project_dependency": "gate"}, "dependencies"),
                                 ({"task_blocked": True}, "dependencies")):
            app, due, _, _ = self._worker_admission_fixture(**options)
            with self.assertRaisesRegex(OccurrencePreparationError, message):
                recheck_execution_admission(app, due)

    def test_host_final_gate_blocks_fresh_resume_and_retry_on_stale_task_admission(self):
        from otto.portfolio.execution_host import ExecutionHost

        with tempfile.TemporaryDirectory() as root:
            for mode in ("fresh", "resume", "retry"):
                app, due, _, _ = self._worker_admission_fixture(admitted=False)
                due.schedule_id = "worker-" + mode
                due.project_ref = "project-p"
                due.profile = "workspace-write"
                due.host_evidence = {"gateway_attempt": {"physical_session_id": "session-" + mode}}
                app.runtime = SimpleNamespace(adapter=SimpleNamespace(
                    owner_transport_only=True, worktree=root,
                ))
                app._read = lambda schedule, due=due: due
                host = ExecutionHost(directory=Path(root) / mode, handler=lambda request: None,
                                     bounded_transports=True)
                calls = []
                with self.assertRaises(OccurrencePreparationError):
                    completion = host._owned(lambda: host.admit_execution(
                        app, due, lambda: calls.append(mode),
                    ))
                    host._owned(host._start_ready_executions)
                    if completion.error is not None:
                        raise completion.error
                self.assertEqual(calls, [])

    def test_host_final_gate_rechecks_state_changed_after_queue_selection(self):
        from otto.portfolio.execution_host import ExecutionHost

        with tempfile.TemporaryDirectory() as root:
            app, due, _, task = self._worker_admission_fixture()
            due.project_ref = "project-p"
            due.profile = "workspace-write"
            due.host_evidence = {"gateway_attempt": {"physical_session_id": "queued-session"}}
            app.runtime = SimpleNamespace(adapter=SimpleNamespace(
                owner_transport_only=True, worktree=root,
            ))
            app._read = lambda schedule: due
            host = ExecutionHost(directory=Path(root) / "ipc", handler=lambda request: None,
                                 bounded_transports=True)
            calls = []
            completion = host._owned(lambda: host.admit_execution(app, due, lambda: calls.append("launched")))
            original_ensure = host.capacity.ensure_turn
            used_before = host.capacity.snapshot()["pool"]["cumulative_used_units"]

            def mutate_after_selection(*args, **kwargs):
                value = original_ensure(*args, **kwargs)
                task.payload["title"] = "changed while queued"
                return value

            host.capacity.ensure_turn = mutate_after_selection
            host._owned(host._start_ready_executions)
            self.assertIsInstance(completion.error, OccurrencePreparationError)
            self.assertEqual(calls, [])
            self.assertEqual(host.capacity.snapshot()["turns"]["reserved"], 0)
            self.assertEqual(host.capacity.snapshot()["pool"]["cumulative_used_units"], used_before)

    def test_final_admission_gate_does_not_apply_worker_task_rules_to_managers(self):
        due = SimpleNamespace(role="manager", schedule_id="manager-due",
                              assignment_ref={"id": "manager"}, generation=2)
        current = Mock()
        self.assertEqual(recheck_execution_admission(
            SimpleNamespace(_current=current), due)["worker_readiness"], "not_applicable")
        current.assert_called_once_with(due.assignment_ref, 2)

    def test_worker_done_reaches_its_own_assignment(self):
        from herzchen.fleet.tools import CHECK, DONE, FeedbackLedger, TokenBook, ToolSpec
        from otto.portfolio.execution_host import ExecutionHost

        calls = []
        service = SimpleNamespace(
            check=lambda lab, task: calls.append(("check", lab, task)) or {"feedback": True},
            done=lambda lab, task, **pins: calls.append(("done", lab, task, pins)) or {"landed": True},
        )
        due = SimpleNamespace(role="worker", assignment_ref=REF, generation=7)
        book = TokenBook()
        token = book.issue(REF["id"], "worker")
        app = SimpleNamespace(_current=lambda ref, generation: self.assertEqual((ref, generation), (REF, 7)))
        facade = ExecutionHost.worker_facade_for_occurrence(
            app=app, due=due, token=token, token_book=book,
            tools=(ToolSpec("check", CHECK, "worker-check", args=("lab_name", "task_id")),
                   ToolSpec("done", DONE, "worker-done", args=("summary",))),
            roles={"worker": ("check", "done")},
            assignment_context=lambda assignment: {
                "service": service, "lab_name": "owned-lab", "task_id": assignment,
                "candidate": "candidate", "criterion": "criterion",
            },
            ledger=FeedbackLedger(),
        )
        self.assertTrue(facade.call(token, "check", {"lab_name": "other", "task_id": "foreign"})["feedback"])
        self.assertTrue(facade.call(token, "done", {"summary": "ready"})["submitted"])
        self.assertEqual(calls[0], ("check", "owned-lab", REF["id"]))
        self.assertEqual(calls[1][0:3], ("done", "owned-lab", REF["id"]))

        foreign = book.issue("foreign-assignment", "worker")
        with self.assertRaises(PermissionError):
            ExecutionHost.worker_facade_for_occurrence(
                app=app, due=due, token=foreign, token_book=book,
                tools=(ToolSpec("check", CHECK, "worker-check"),),
                roles={"worker": ("check",)},
                assignment_context=lambda assignment: {"service": service, "lab_name": "owned-lab", "task_id": assignment},
            )

    def test_current_assignment_is_reconciled_from_public_base(self):
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(), assignments=Assignments(), binding=Binding(), due=self.due(),
            assignment_ref=REF, assignment_owner="manager", operation="resume", lifecycle="resume",
            request_key="resume-v1",
        )
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["assignment_base_ref"], BASE)
        self.assertEqual(result["assignment_current_ref"], REF)
        self.assertEqual(result["due_version"], 2)

    def test_fresh_project_advisor_uses_generic_bounded_role_mode(self):
        due = replace(
            self.due(), role="project_advisor", execution_mode="fresh_bounded_role",
            target={"assignment_ref": BASE},
        )
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(), assignments=Assignments(), binding=Binding(), due=due,
            assignment_ref=REF, assignment_owner="manager", operation="invoke", lifecycle="launch",
            request_key="advisor-start-v1",
        )
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["execution_mode"], "fresh_bounded_role")

    def test_assignment_payload_manager_can_prepare_role_occurrence(self):
        due = replace(self.due(), role="project_advisor", execution_mode="fresh_bounded_role",
                      target={"assignment_ref": BASE})
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(), assignments=PayloadOwnedAssignments(), binding=Binding(), due=due,
            assignment_ref=REF, assignment_owner="manager", operation="invoke", lifecycle="launch",
            request_key="advisor-payload-owner-v1",
        )
        self.assertEqual(result["outcome"], "committed")

    def test_fresh_project_advisor_due_requires_exact_readonly_owner_pins(self):
        project = {"authority": "owner", "kind": "work.project", "id": "p", "revision": "rev-1"}
        task = {"authority": "owner", "kind": "work.task", "id": "t", "revision": "rev-1"}
        mandate = {"authority": "owner", "kind": "cnt.document", "id": "m", "revision": "rev-1"}
        guide = {"authority": "owner", "kind": "cnt.document", "id": "g", "revision": "rev-1"}
        due = DueRecord(
            schedule_id="advisor-start", recipient="advisor", instruction="Answer once.",
            profile="read-only", anchor="2026-10-03T00:00:00Z", due_at="2026-10-03T00:00:00Z",
            last_covered_slot=0, invocation_identity="advisor-start-v1", project_ref="p", manager_ref="owner",
            assignment_ref=REF, generation=1, role="project_advisor", lifecycle_owner="owner",
            target={"host": "local", "project_ref": project, "task_ref": task,
                    "assignment_ref": REF, "mandate_ref": mandate, "role": "project_advisor",
                    "principal": "advisor", "requested_model": "gpt-6-astra",
                    "requested_reasoning": "high", "requested_profile": "read-only"},
            execution_mode="fresh_bounded_role", requested_model="gpt-6-astra",
            requested_reasoning="high", context_refs=(guide, mandate), timeout_seconds=1200,
        )
        self.assertEqual(due.role, "project_advisor")
        self.assertEqual(due.execution_mode, "fresh_bounded_role")
        with self.assertRaisesRegex(ValueError, "must not fabricate"):
            replace(due, target={**due.target, "native_id": "made-up"})

    def test_partial_success_names_committed_due(self):
        result = prepare_current_assignment_occurrence(
            due_port=DuePort(fail=True), assignments=Assignments(), binding=Binding(), due=self.due(),
            assignment_ref=REF, assignment_owner="manager", operation="resume", lifecycle="resume",
            request_key="resume-v2",
        )
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["stage"], "due_created")
        self.assertEqual(result["schedule_id"], "due-1")

    def test_owner_and_mode_are_rejected_before_write(self):
        with self.assertRaises(OccurrencePreparationError):
            prepare_current_assignment_occurrence(
                due_port=DuePort(), assignments=Assignments(), binding=Binding(),
                due=replace(self.due(), execution_mode="fresh_bounded_worker"), assignment_ref=REF,
                assignment_owner="outsider", operation="resume", lifecycle="resume", request_key="resume-v3",
            )

    def test_timeout_policy_is_derived_and_rejected_before_write(self):
        self.assertEqual(validate_owner_timeout_seconds(1200), 1200)
        self.assertEqual(validate_owner_timeout_seconds(1800), 1800)
        port = DuePort()
        with self.assertRaisesRegex(OccurrencePreparationError, "between 61 and 1800"):
            prepare_current_assignment_occurrence(
                due_port=port, assignments=Assignments(), binding=Binding(),
                due=replace(self.due(), timeout_seconds=2700), assignment_ref=REF,
                assignment_owner="manager", operation="resume", lifecycle="resume",
                request_key="resume-invalid-timeout",
            )
        self.assertEqual(port.saved, 0)

    def test_local_checkpoint_commits_only_selected_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "selected.txt").write_text("one\n")
            (root / "other.txt").write_text("outside\n")
            result = commit_local_checkpoint(root, ["selected.txt"], message="Selected checkpoint")
            self.assertEqual(result["outcome"], "committed")
            self.assertEqual(result["paths"], ["selected.txt"])
            self.assertEqual(
                subprocess.run(["git", "-C", str(root), "status", "--short"],
                               check=True, capture_output=True, text=True).stdout,
                "?? other.txt\n",
            )
            self.assertEqual(
                commit_local_checkpoint(root, ["selected.txt"], message="Selected checkpoint")["outcome"],
                "replayed",
            )

    def test_local_checkpoint_rejects_escape_and_foreign_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "selected.txt").write_text("one\n")
            (root / "foreign.txt").write_text("two\n")
            subprocess.run(["git", "-C", str(root), "add", "foreign.txt"], check=True)
            with self.assertRaisesRegex(OccurrencePreparationError, "outside the request"):
                commit_local_checkpoint(root, ["selected.txt"], message="Selected checkpoint")
            with self.assertRaisesRegex(OccurrencePreparationError, "escapes"):
                commit_local_checkpoint(root, ["../outside.txt"], message="Invalid checkpoint")

    def test_local_checkpoint_accepts_a_linked_git_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repository = parent / "repository"
            linked = parent / "linked"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            (repository / "baseline.txt").write_text("baseline\n")
            subprocess.run(["git", "-C", str(repository), "add", "baseline.txt"], check=True)
            subprocess.run([
                "git", "-C", str(repository), "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-q", "-m", "baseline",
            ], check=True)
            subprocess.run(["git", "-C", str(repository), "worktree", "add", "-q", str(linked)], check=True)
            self.assertTrue((linked / ".git").is_file())
            (linked / "selected.txt").write_text("linked checkpoint\n")

            result = commit_local_checkpoint(linked, ["selected.txt"], message="Linked checkpoint")

            self.assertEqual(result["outcome"], "committed")
            self.assertEqual(result["paths"], ["selected.txt"])

    def test_compact_status_joins_task_report_and_native_handle(self):
        task_ref = {"authority": "owner", "kind": "work.task", "id": "task-1", "revision": "rev-2"}
        view = {
            "project": {"ref": {"id": "project-1"}, "observed": {
                "lifecycle": "active", "readiness": {"status": "ready"},
            }},
            "tasks": [{
                "ref": task_ref,
                "authored": {"title": "One", "lifecycle": "pending"},
                "observed": {
                    "lifecycle": "active", "readiness": {"status": "ready"},
                    "assignments": [{"ref": {"id": "assignment-1"}, "payload": {
                        "principal": "worker-1", "generation": 2, "status": "queued",
                    }}],
                },
            }],
        }
        report = {"ref": {"id": "report-1"}, "value": {
            "task_alias": "PA01", "recorded_at": "2026-10-03T12:00:00Z",
            "summary": "implemented", "next_action": "review",
        }}
        occurrence = {
            "schedule_id": "worker-1", "version": 4, "target": {"task_ref": task_ref},
            "delivery_state": "ready", "host_state": "active", "completion_state": "none",
            "host_evidence": {"gateway_attempt": {"physical_session_id": "session-1"}},
        }
        value = compact_project_status(
            view, task_refs={"PA01": task_ref}, reports=[report], occurrences=[occurrence],
        )
        self.assertEqual(value["tasks"]["PA01"]["lifecycle"], "active")
        self.assertEqual(value["tasks"]["PA01"]["latest_report"]["ref"], {"id": "report-1"})
        self.assertEqual(value["tasks"]["PA01"]["occurrence"]["physical_session_id"], "session-1")
        self.assertEqual(value["tasks"]["PA01"]["execution"]["result_refs"], [])
        self.assertEqual(value["tasks"]["PA01"]["review"]["acceptance_exists"]["state"], "unknown")
        self.assertIsNone(value["tasks"]["PA01"]["review"]["acceptance_exists"]["value"])
        self.assertEqual(value["writes_performed"], 0)
        self.assertIsNone(value["acceptance_exists"])

    def test_compact_status_keeps_acceptance_distinct_from_uncertain_history(self):
        task_ref = {"authority": "owner", "kind": "work.task", "id": "task-1", "revision": "rev-2"}
        view = {
            "project": {"ref": {"id": "project-1"}, "observed": {"lifecycle": "active"}},
            "tasks": [{
                "ref": task_ref,
                "authored": {"title": "One", "lifecycle": "active"},
                "observed": {
                    "lifecycle": "active", "decisions": [{
                        "ref": {"id": "decision-1"}, "accepted": True,
                    }],
                    "results": [{"ref": {"id": "result-1"}}],
                },
            }],
        }
        occurrences = [
            {"schedule_id": "old", "version": 1, "anchor": "2026-10-01T10:00:00Z",
             "delivery_state": "unknown", "completion_state": "unknown", "target": {"task_ref": task_ref}},
            {"schedule_id": "new", "version": 2, "anchor": "2026-10-02T10:00:00Z",
             "delivery_state": "returned", "completion_state": "succeeded",
             "last_result": {"outcome": "returned"}, "target": {"task_ref": task_ref}},
        ]
        value = compact_project_status(project_view=view, task_refs={"PA01": task_ref}, occurrences=occurrences)
        task = value["tasks"]["PA01"]
        self.assertEqual(task["execution"]["result_refs"], [{"id": "result-1"}])
        self.assertTrue(task["review"]["acceptance_exists"]["value"])
        self.assertEqual(len(task["historical_occurrences"]), 2)
        self.assertEqual(len(value["historical_uncertain_effects"]), 1)
        self.assertTrue(value["acceptance_exists"])
        self.assertEqual(value["writes_performed"], 0)

    def test_operation_status_keeps_transport_review_settlement_and_project_close_distinct(self):
        value = compact_operation_status(
            {"schedule_id": "op-1", "delivery_state": "returned", "completion_state": "none",
             "stop_state": "active", "role": "manager"},
            accepted_review={"state": "known", "value": True, "source_refs": [{"id": "gate-1"}]},
            canonical_project={"lifecycle": "active", "project_completion_recorded": False,
                               "reconciliation": {"status": "pending"}},
            required_scope={"task_aliases": ["PA01"]},
            blockers=[],
            pending_help={"state": "known", "status": "pending", "destination": {"id": "orch"}},
            instruction_provenance={"mandate_ref": {"id": "mandate-1"}},
        )
        self.assertEqual(value["transport_completion"]["state"], "completed")
        self.assertTrue(value["transport_completion"]["completed"])
        self.assertTrue(value["accepted_review"]["value"])
        self.assertEqual(value["task_settlement"]["state"], "pending")
        self.assertFalse(value["canonical_project_completion"]["project_completion_recorded"])
        self.assertEqual(value["pending_help"]["status"], "pending")
        self.assertEqual(value["instruction_provenance"]["value"]["mandate_ref"]["id"], "mandate-1")
        self.assertEqual(value["supported_next_remedy"]["command"], "read-help")
        unknown = compact_operation_status()
        self.assertIsNone(unknown["canonical_project_completion"]["project_completion_recorded"])

    def test_pre_effect_partial_reason_is_exposed_without_claiming_native_failure(self):
        failure={'stage':'runtime','error':{'code':'OccurrencePreparationError','message':'prepared anchor differs'},
            'next_action':'Correct exact prepared binding; no replay'}
        value=compact_operation_status({'schedule_id':'callback','role':'manager','stop_state':'active',
            'completion_state':'none','pre_effect_runtime_failure':failure})
        self.assertTrue(value['blocked_operation'])
        self.assertEqual(value['blockers'][0]['error'],failure['error'])
        self.assertFalse(value['blockers'][0]['effects_started'])
        self.assertEqual(value['supported_next_remedy']['operation'],'owner-correct-prepared-binding')
        attempted=compact_operation_status({'schedule_id':'callback','role':'manager','stop_state':'active',
            'completion_state':'unknown','pre_effect_runtime_failure':failure,
            'host_evidence':{'gateway_attempt':{'state':'claimed'}}})
        self.assertFalse(attempted['blocked_operation'])
        self.assertNotEqual(attempted['supported_next_remedy']['operation'],'owner-correct-prepared-binding')

    def test_pending_manager_remedy_uses_transport_handle_never_schedule_id(self):
        operation = {"schedule_id": "manager-finish-callback-name", "role": "manager",
            "delivery_state": "returned", "completion_state": "none", "stop_state": "active"}
        for handle, command in ((None, "status"), ("manager-finish-callback-name", "status"),
                                ("8f" * 32, "command-status --request-id " + "8f" * 32)):
            with self.subTest(handle=handle):
                value = compact_operation_status({**operation, "retained_handle": handle})
                self.assertEqual(value["supported_next_remedy"]["command"], command)

    def test_project_status_exposes_current_layers_without_globalizing_old_unknown(self):
        task_ref = {"authority": "owner", "kind": "work.task", "id": "task-1", "revision": "rev-2"}
        view = {"project": {"ref": {"id": "project-1"}, "observed": {
            "lifecycle": "active", "readiness": {"blockers": []},
        }}, "tasks": [{"ref": task_ref, "authored": {"title": "One", "lifecycle": "active"},
            "observed": {"lifecycle": "active", "decisions": [{"ref": {"id": "gate-1"}, "accepted": True}]}}]}
        value = compact_project_status(
            view, task_refs={"PA01": task_ref},
            occurrences=[{"schedule_id": "old", "anchor": "2026-10-01T10:00:00Z",
                          "delivery_state": "unknown", "completion_state": "unknown",
                          "target": {"task_ref": task_ref}},
                         {"schedule_id": "new", "anchor": "2026-10-02T10:00:00Z",
                          "delivery_state": "returned", "completion_state": "none",
                          "stop_state": "active", "target": {"task_ref": task_ref}}],
            help_issues=[{"issue_id": "help-1", "state": "open", "purpose": "operational_help",
                          "current_owner_ref": {"id": "orch"},
                          "deliveries": [{"delivery_id": "delivery-1", "state": "pending"}]}],
            instruction_provenance={"mandate_ref": {"id": "mandate-1"}},
        )
        self.assertEqual(value["transport_completion"]["state"], "completed")
        self.assertEqual(value["task_settlement"]["state"], "pending")
        self.assertTrue(value["accepted_review"]["value"])
        self.assertEqual(value["pending_help"]["destination"]["id"], "orch")
        self.assertEqual(len(value["historical_uncertain_effects"]), 1)
        self.assertFalse(value["blocked_operation"])

    def test_continuation_is_recovered_from_report_without_projection_file(self):
        due = {
            "schedule_id": "manager-v2", "stop_state": "completed",
            "completion_state": "succeeded", "in_flight_request": None,
            "delivery_state": "returned", "anchor": "2026-10-03T10:00:00Z",
            "completed_at": "2026-10-03T10:05:00Z", "assignment_ref": REF,
            "last_result": {"physical_session_id": "session", "observed_turn_id": "turn"},
        }
        reports = ({
            "kind": "report", "assignment": REF, "ref": {"id": "report-1"},
            "value": {
                "schema": "otto.manager-progress.v1", "task_alias": "PA03",
                "next_action": "begin PA05", "continue_requested": True,
                "logical_request_key": "pa03-accepted", "recorded_at": "2026-10-03T10:04:00Z",
            },
        },)
        result = derive_manager_continuation_request(due, reports)
        self.assertEqual(result["next_action"], "begin PA05")
        self.assertEqual(result["settled_schedule_id"], "manager-v2")
        self.assertEqual(result["physical_session_id"], "session")

    def test_continuation_ignores_prior_turn_and_nonrequest_reports(self):
        due = {
            "schedule_id": "manager-v2", "stop_state": "completed",
            "completion_state": "succeeded", "in_flight_request": None,
            "delivery_state": "returned", "anchor": "2026-10-03T10:00:00Z",
            "completed_at": "2026-10-03T10:05:00Z", "assignment_ref": REF,
            "last_result": {"physical_session_id": "session", "observed_turn_id": "turn"},
        }
        reports = (
            {"kind": "report", "assignment": REF, "ref": {"id": "old"}, "value": {
                "schema": "otto.manager-progress.v1", "continue_requested": True,
                "recorded_at": "2026-10-03T09:59:00Z"}},
            {"kind": "report", "assignment": REF, "ref": {"id": "current"}, "value": {
                "schema": "otto.manager-progress.v1", "continue_requested": False,
                "recorded_at": "2026-10-03T10:04:00Z"}},
        )
        self.assertIsNone(derive_manager_continuation_request(due, reports))

    def test_progress_reports_use_public_event_reader(self):
        class Subject:
            kind, id = "wrk.report", "report-1"
        class Event:
            subject = Subject()
        class RecordRef:
            def to_dict(self): return {"authority": "owner", "kind": "wrk.report", "id": "report-1", "revision": "rev-1"}
        class Record:
            ref = RecordRef()
            payload = {
                "observation_kind": "report", "assignment": REF,
                "value": {"project_ref": {"authority": "owner", "kind": "work.project", "id": "p"}},
            }
        class Reader:
            def list_events(self): return (Event(), Event())
            def get_record(self, subject): return Record()
        result = read_project_progress_reports(
            Reader(), {"authority": "owner", "kind": "work.project", "id": "p"}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ref"]["id"], "report-1")

    def test_progress_streams_preserve_project_reports_across_assignments_and_generations(self):
        from tests.test_execution_application import ExecutionApplicationTests
        from herzchen.contracts import ResourceRef
        f = ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        port = f.owner.assignments.command_port
        first = port.assign(f.project.ref, role="manager", principal="manager", manager="manager",
            session="old-session", pins=[], logical_request_key="progress-old", actor=f.actor)
        other = port.assign(f.project.ref, role="orchestrator", principal="manager", manager="manager",
            session="root-session", pins=[], logical_request_key="progress-root", actor=f.actor)
        retained = []
        for assignment, label in ((first, "old-manager"), (other, "root-note")):
            retained.append(port.append_report(assignment.ref,
                {"project_ref": f.project.ref.to_dict(), "summary": label},
                expected_generation=assignment.generation, logical_request_key="report-" + label, actor=f.actor))
        current = port.reassign(first.ref, principal="manager", expected_generation=first.generation,
            logical_request_key="progress-reassignment", actor=f.actor)
        retained.append(port.append_report(current.ref,
            {"project_ref": f.project.ref.to_dict(), "summary": "new-manager"},
            expected_generation=current.generation, logical_request_key="report-new-manager", actor=f.actor))
        # Project attribution must still filter out a foreign linked project
        # even when its report is on one of the selected assignment streams.
        port.append_report(other.ref, {"project_ref": {**f.project.ref.to_dict(), "id": "foreign"}},
            expected_generation=other.generation, logical_request_key="report-foreign", actor=f.actor)
        reader = f.store.consumer()
        expected = read_project_progress_reports(reader, f.project.ref.to_dict())
        streams = []
        class ExactReader:
            def list_events(self, *, stream=None):
                if stream is None: raise AssertionError("global event hydration is forbidden")
                streams.append(stream)
                return reader.list_events(stream=stream)
            def get_record(self, ref): return reader.get_record(ref)
        observed = read_project_progress_reports(ExactReader(), f.project.ref.to_dict(),
            assignment_refs=[current.ref.to_dict(), first.ref.to_dict(), other.ref.to_dict()])
        self.assertEqual(observed, expected)
        self.assertEqual({row["ref"]["id"] for row in observed}, {row.ref.id for row in retained})
        self.assertEqual(streams, sorted({"report:" + first.ref.id, "report:" + other.ref.id}))
        self.assertEqual({row["value"]["summary"] for row in observed}, {"old-manager", "root-note", "new-manager"})
        # The current assignment locator addresses its immutable stream, which
        # retains same-manager reports written before the assignment revision.
        streams.clear()
        current_only = read_project_progress_reports(ExactReader(), f.project.ref.to_dict(),
            assignment_refs=[current.ref.to_dict()])
        self.assertEqual({row["value"]["summary"] for row in current_only}, {"old-manager", "new-manager"})
        self.assertEqual(streams, ["report:" + current.ref.id])
        self.assertEqual(read_project_progress_reports(ExactReader(), f.project.ref.to_dict(), assignment_refs=[]), [])
        with self.assertRaises(OccurrencePreparationError):
            read_project_progress_reports(ExactReader(), f.project.ref.to_dict(),
                assignment_refs=[{**first.ref.to_dict(), "authority": "foreign"}])
        self.assertEqual(f.provider.calls, [])

    def test_settled_manager_builds_same_session_callback(self):
        project = {"authority":"owner","kind":"work.project","id":"p","revision":"rev-1"}
        task = {"authority":"owner","kind":"work.task","id":"t","revision":"rev-1"}
        mandate = {"authority":"owner","kind":"dat.content.document","id":"m","revision":"rev-1"}
        guide = {**mandate,"id":"g"}
        prior = DueRecord(schedule_id="old", recipient="manager", instruction="Inspect task",
            profile="workspace-write", anchor="2026-10-03T00:00:00Z",due_at="2026-10-03T00:00:00Z",
            last_covered_slot=1,invocation_identity="old", project_ref="p",manager_ref="owner",
            assignment_ref=BASE,generation=1,role="manager",lifecycle_owner="owner",
            target={"host":"local","project_ref":project,"task_ref":task,"assignment_ref":BASE,
                "mandate_ref":mandate,"native_id":"session","role":"manager","principal":"manager",
                "requested_model":"gpt-test","requested_reasoning":"high","requested_profile":"workspace-write"},
            execution_mode="continue_existing",requested_model="gpt-test",requested_reasoning="high",
            context_refs=(guide,mandate),timeout_seconds=1200,stop_state="completed",completion_state="succeeded",
            delivery_state="returned",last_result={"physical_session_id":"session"})
        result = build_manager_callback_due(
            prior, schedule_id="next", request_key="callback-v1", assignment_ref=REF,
            guide_ref=guide, mandate_ref=mandate,
            due_at="2026-10-03T00:00:00Z", timeout_seconds=1200,
        )
        self.assertEqual(result.schedule_id, "next")
        self.assertEqual(result.target["native_id"], "session")
        self.assertEqual(result.in_flight_request, "callback-v1")
        self.assertEqual(result.completion_state, "none")


if __name__ == "__main__": unittest.main()

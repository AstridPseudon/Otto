from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import subprocess
import tempfile
import unittest

from otto.portfolio.execution_operations import (
    OccurrencePreparationError,
    build_manager_callback_due,
    compact_project_status,
    commit_local_checkpoint,
    derive_manager_continuation_request,
    prepare_current_assignment_occurrence,
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

    def test_settled_manager_builds_same_session_callback(self):
        prior = type("ManagerDue", (), {
            "stop_state": "completed", "completion_state": "succeeded",
            "in_flight_request": None, "delivery_state": "returned",
            "target": {"native_id": "session", "assignment_ref": BASE},
            "last_result": {"physical_session_id": "session"},
        })()
        # dataclasses.replace is the production mechanism; use a real flexible
        # dataclass in this focused fixture.
        @dataclass(frozen=True)
        class ManagerDue:
            schedule_id: str = "old"
            instruction: str = "old"
            anchor: str = "old"
            due_at: str = "old"
            last_covered_slot: int = 1
            invocation_identity: str = "old"
            in_flight_request: str | None = None
            delivery_state: str = "returned"
            assignment_ref: dict | None = None
            target: dict | None = None
            purpose: str = "old"
            host_state: str = "active"
            execution_mode: str = "continue_existing"
            context_refs: tuple = ()
            timeout_seconds: int = 1
            stop_state: str = "completed"
            last_completed_request: str | None = "old"
            last_result: dict | None = None
            delivered_at: str | None = "old"
            delivery_evidence: dict | None = None
            completed_at: str | None = "old"
            completion_state: str = "succeeded"
            completion_evidence: dict | None = None
            host_evidence: dict | None = None
        prior = ManagerDue(target={"native_id": "session"}, last_result={"physical_session_id": "session"})
        result = build_manager_callback_due(
            prior, schedule_id="next", request_key="callback-v1", assignment_ref=REF,
            guide_ref={"id": "guide"}, mandate_ref={"id": "mandate"},
            due_at="2026-10-03T00:00:00Z", timeout_seconds=1200,
        )
        self.assertEqual(result.schedule_id, "next")
        self.assertEqual(result.target["native_id"], "session")
        self.assertEqual(result.in_flight_request, "callback-v1")
        self.assertEqual(result.completion_state, "none")


if __name__ == "__main__": unittest.main()

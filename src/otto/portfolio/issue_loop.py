"""Typed check-in and issue composition over existing assignment reports.

This module deliberately owns no records.  It composes the existing
ResponsibilityAssignments report port, a DueRecord port, read-only current
scope resolvers, and an optional host delivery port.  Reports are the durable
issue/response/outcome history; DueRecord is the occurrence acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Optional, Sequence


class IssueLoopError(ValueError):
    """A malformed or unauthorized AP-3 request."""


def _json(value: Any, name: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise IssueLoopError(f"{name} must contain only JSON values") from exc


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IssueLoopError(f"{name} must be non-blank text")
    return value.strip()


def _ref(value: Any, name: str = "ref") -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, str):
        value = {"id": value}
    if not isinstance(value, Mapping) or not isinstance(value.get("id"), str) or not value["id"].strip():
        raise IssueLoopError(f"{name} must be a reference with a non-blank id")
    return _json(dict(value), name)


def _ref_id(value: Any) -> str:
    try:
        return _ref(value)["id"]
    except IssueLoopError:
        return ""


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _principal(value: Any) -> str:
    candidate = _field(value, "principal", value)
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, Mapping):
        return str(candidate.get("id") or candidate.get("principal") or "")
    return str(_field(candidate, "id", ""))


def _stamp(value: Optional[datetime] = None) -> str:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise IssueLoopError("now must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat()


def _stable(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return prefix + "-" + sha256(encoded.encode("utf-8")).hexdigest()[:28]


@dataclass(frozen=True)
class IssueLoopPorts:
    """Owner-issued capabilities; resolver callables remain on the trusted side."""

    assignments: Any
    due_records: Any
    authenticate: Callable[[str], Any]
    current_manager: Callable[[Mapping[str, Any]], Any]
    current_supervisor: Callable[[Mapping[str, Any]], Any]
    current_facts: Callable[[Mapping[str, Any], Any, str], Mapping[str, Any]]
    reports_for_project: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    due_records_for_project: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    delivery: Any = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    current_advisor: Any = None
    recipient_conversation: Any = None


class IssueLoop:
    """The manager-facing, finite AP-3 operations over existing owner records."""

    def __init__(self, ports: IssueLoopPorts) -> None:
        required = (ports.assignments, ports.due_records, ports.authenticate,
                    ports.current_manager, ports.current_supervisor, ports.current_facts,
                    ports.reports_for_project, ports.due_records_for_project)
        if any(value is None for value in required):
            raise ValueError("assignment, DueRecord, authentication, and current-scope ports are required")
        self.ports = ports

    def _recipient(self, project: Mapping[str, Any], purpose: str) -> Any:
        if purpose == "advice":
            if not callable(self.ports.current_advisor):
                raise IssueLoopError("current advisor route is unavailable")
            return self.ports.current_advisor(project)
        if purpose != "operational_help":
            raise IssueLoopError("purpose must be advice or operational_help")
        return self.ports.current_supervisor(project)

    @staticmethod
    def _due_proves(due: Any, identity: Any) -> bool:
        if not isinstance(identity, Mapping):
            return False
        for proof in getattr(due, "accepted_checkins", ()):
            if (isinstance(proof, Mapping)
                    and proof.get("schema") == "otto.checkin.accepted-proof.v1"
                    and proof.get("schedule_id") == due.schedule_id
                    and proof.get("project_ref") == due.project_ref
                    and proof.get("schedule_id") == identity.get("schedule_id")
                    and proof.get("generation") == identity.get("generation")
                    and proof.get("expected_slot") == identity.get("expected_slot")
                    and proof.get("deadline") == identity.get("deadline")
                    and isinstance(proof.get("occurrence_id"), str)
                    and isinstance(proof.get("report_ref"), Mapping)):
                return True
        return False

    def _project_due_proves(self, project: Mapping[str, Any], identity: Any) -> bool:
        from otto.attention import DueRecord
        if not isinstance(identity, Mapping):
            return False
        for raw in self.ports.due_records_for_project(project):
            due = DueRecord.from_dict(raw)
            if due.project_ref == project.get("id") and self._due_proves(due, identity):
                return True
        return False

    def _persist_accepted_proof(self, schedule_id: str, due: Any,
                                proof: Mapping[str, Any]) -> bool:
        """CAS an accepted proof into a legacy DueRecord after validating its old ack."""
        from otto.attention import DueRecord
        current = due
        for attempt in range(3):
            if proof in current.accepted_checkins:
                return True
            history = tuple(current.accepted_checkins) + (dict(proof),)
            updated = DueRecord.from_dict({**current.to_dict(),
                "accepted_checkins": history, "version": current.version + 1})
            request_id = f"otto-checkin-proof-recovery:{proof['occurrence_id']}:{current.version}"
            try:
                self.ports.due_records.save_due(schedule_id, updated.to_dict(),
                    request_id=request_id, expected_version=current.version)
                return True
            except Exception:
                latest = self.ports.due_records.read_due(schedule_id)
                if not isinstance(latest, Mapping):
                    return False
                current = DueRecord.from_dict(latest)
        return proof in current.accepted_checkins

    def _assignment(self, ref: Any) -> Any:
        target = _ref(ref, "assignment_ref")
        assignment = self.ports.assignments.get(target)
        if _ref_id(_field(assignment, "ref")) != target["id"]:
            raise IssueLoopError("assignment reference is not current")
        return assignment

    def _manager(self, project_ref: Mapping[str, Any], assignment_ref: Any, actor: str,
                 generation: int) -> Any:
        assignment = self._assignment(assignment_ref)
        current = self.ports.current_manager(project_ref)
        if _ref_id(_field(current, "ref")) != _ref_id(_field(assignment, "ref")):
            raise IssueLoopError("assignment is not the current project manager")
        if _principal(assignment) != actor:
            raise IssueLoopError("actor is not the assigned manager")
        current_generation = _field(assignment, "generation")
        if isinstance(current_generation, bool) or current_generation != generation:
            raise IssueLoopError("assignment generation is stale")
        if str(_field(assignment, "role", "")).lower() != "manager":
            raise IssueLoopError("current assignment is not a manager role")
        status = _field(assignment, "status", "active")
        status = str(getattr(status, "value", status)).lower()
        if status not in {"active", "running", "assigned", "queued", "reassigned", "in-flight"}:
            raise IssueLoopError("manager assignment is not active")
        return assignment

    @staticmethod
    def _observation(value: Any) -> dict[str, Any]:
        ref = _field(value, "ref")
        return {"ref": _ref(ref, "report_ref"), "kind": _field(value, "kind", "report"),
                "generation": _field(value, "generation"), "value": _json(_field(value, "value"), "report")}

    def _append(self, assignment: Any, body: Mapping[str, Any], *, key: str, actor: str,
                generation: int) -> dict[str, Any]:
        observation = self.ports.assignments.append_report(
            _field(assignment, "ref"), dict(body), expected_generation=generation,
            logical_request_key=key, actor=self.ports.authenticate(actor),
        )
        return self._observation(observation)

    def _append_issue_record(self, project: Mapping[str, Any], assignment: Any,
                             body: Mapping[str, Any], *, request_id: str, actor: str,
                             generation: int) -> dict[str, Any]:
        """Replay a previously committed issue report before deriving new facts."""
        request_id = _text(request_id, "request_id")
        for report in self._issue_reports(project):
            value = report.get("value")
            if not isinstance(value, Mapping) or value.get("request_id") != request_id:
                continue
            previous, expected = dict(value), dict(body)
            for field in ("observed_at", "issue_version", "current_owner_ref", "routing_state", "routing_repair_owner"):
                previous.pop(field, None)
                expected.pop(field, None)
            if previous != expected:
                raise IssueLoopError("request_id was reused with changed issue input")
            return {"ref": _ref(report.get("ref"), "report_ref"),
                    "kind": report.get("kind", "report"),
                    "generation": report.get("generation"), "value": dict(value)}
        return self._append(assignment, body, key=request_id, actor=actor, generation=generation)

    def _next_issue_version(self, project: Mapping[str, Any], issue_id: str) -> int:
        versions = []
        for item in self._issue_reports(project):
            value = item.get("value")
            if isinstance(value, Mapping) and value.get("issue_id") == issue_id:
                candidate = value.get("issue_version", 0)
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    versions.append(candidate)
        return max(versions, default=0) + 1

    def submit_checkin(self, *, project_ref: Any, assignment_ref: Any, schedule_id: str,
                       occurrence_id: str, generation: int, actor: str,
                       commentary: str = "") -> dict[str, Any]:
        """Append a validated manager report, then acknowledge that DueRecord occurrence.

        The same deterministic report key makes report-then-ack replay safe if
        the acknowledgement was lost. A rejected/stale occurrence has no write.
        """
        project = _ref(project_ref, "project_ref")
        assignment_ref = _ref(assignment_ref, "assignment_ref")
        actor = _text(actor, "actor")
        schedule_id = _text(schedule_id, "schedule_id")
        occurrence_id = _text(occurrence_id, "occurrence_id")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise IssueLoopError("generation must be a positive integer")
        commentary = _text(commentary, "commentary") if commentary else ""
        assignment = self._manager(project, assignment_ref, actor, generation)
        facts = self.ports.current_facts(project, assignment, actor)
        if not isinstance(facts, Mapping):
            raise IssueLoopError("current owner read did not return check-in facts")
        facts_value = _json(dict(facts), "facts")
        stored = self.ports.due_records.read_due(schedule_id)
        if not isinstance(stored, Mapping):
            raise IssueLoopError("check-in occurrence is not present in DueRecord")
        from otto.attention import DueRecord
        due = DueRecord.from_dict(stored)
        if (due.project_ref != project["id"] or due.manager_ref != assignment_ref["id"]
                or due.generation != generation):
            raise IssueLoopError("check-in occurrence, current manager, or generation does not match DueRecord")
        if (due.last_completed_request == occurrence_id and due.completion_state == "succeeded"
                and isinstance(due.completion_evidence, Mapping)
                and due.completion_evidence.get("kind") == "otto.checkin.v1"
                and due.completion_evidence.get("occurrence_id") == occurrence_id):
            prior_ref = due.completion_evidence.get("report_ref")
            proof_matches = any(isinstance(proof, Mapping)
                and proof.get("schema") == "otto.checkin.accepted-proof.v1"
                and proof.get("project_ref") == project["id"]
                and proof.get("occurrence_id") == occurrence_id
                and proof.get("schedule_id") == schedule_id
                and proof.get("generation") == generation
                and proof.get("report_ref") == prior_ref for proof in due.accepted_checkins)
            if isinstance(prior_ref, Mapping):
                prior_report = next((item for item in self._issue_reports(project)
                    if _ref_id(item.get("ref")) == _ref_id(prior_ref)), None)
                prior_value = prior_report.get("value") if prior_report else None
                prior_deadline = None
                due_deadline = None
                if due.interval_seconds is None:
                    parsed_due = datetime.fromisoformat((due.due_at or due.anchor).replace("Z", "+00:00"))
                    if parsed_due.tzinfo is None:
                        parsed_due = parsed_due.replace(tzinfo=timezone.utc)
                    due_deadline = parsed_due.astimezone(timezone.utc).isoformat()
                    raw_deadline = prior_value.get("deadline") if isinstance(prior_value, Mapping) else None
                    if isinstance(raw_deadline, str):
                        try:
                            parsed_report = datetime.fromisoformat(raw_deadline.replace("Z", "+00:00"))
                            if parsed_report.tzinfo is None:
                                parsed_report = parsed_report.replace(tzinfo=timezone.utc)
                            prior_deadline = parsed_report.astimezone(timezone.utc).isoformat()
                        except ValueError:
                            pass
                if (not proof_matches and isinstance(prior_value, Mapping)
                        and prior_value.get("schema") == "otto.checkin.v1"
                        and prior_value.get("schedule_id") == schedule_id
                        and prior_value.get("occurrence_id") == occurrence_id
                        and prior_value.get("generation") == generation
                        and _ref_id(prior_value.get("assignment_ref")) == assignment_ref["id"]
                        and _ref_id(prior_value.get("project_ref")) == project["id"]
                        and prior_value.get("expected_slot") == (due.last_covered_slot if due.interval_seconds is not None else None)
                        and prior_deadline == due_deadline):
                    recovered_proof = {"schema": "otto.checkin.accepted-proof.v1",
                        "project_ref": project["id"],
                        "schedule_id": schedule_id, "generation": generation,
                        "occurrence_id": occurrence_id,
                        "expected_slot": prior_value.get("expected_slot"),
                        "deadline": prior_deadline, "report_ref": dict(prior_ref)}
                    proof_matches = self._persist_accepted_proof(schedule_id, due, recovered_proof)
                if proof_matches and prior_report is not None:
                    try:
                        self._record_accepted_checkin(project, assignment, prior_report,
                                                      actor=actor, generation=generation)
                    except Exception:
                        pass
                    return {"outcome": "accepted", "report_ref": dict(prior_ref),
                            "occurrence_id": occurrence_id, "recovered": True}
                if not proof_matches:
                    return {"outcome": "pending", "report_ref": dict(prior_ref),
                            "occurrence_id": occurrence_id,
                            "recovery": "accepted_proof_recovery_unknown"}
        if due.in_flight_request != occurrence_id:
            raise IssueLoopError("check-in occurrence is not the current in-flight DueRecord request")
        key = "otto-checkin:" + occurrence_id
        one_shot_deadline = due.due_at or due.anchor
        if due.interval_seconds is None:
            parsed_deadline = datetime.fromisoformat(one_shot_deadline.replace("Z", "+00:00"))
            if parsed_deadline.tzinfo is None:
                raise IssueLoopError("DueRecord one-shot deadline must be timezone-aware")
            one_shot_deadline = parsed_deadline.astimezone(timezone.utc).isoformat()
        body = {"schema": "otto.checkin.v1", "project_ref": project,
                "assignment_ref": assignment_ref, "generation": generation,
                "occurrence_id": occurrence_id,
                "schedule_id": schedule_id,
                "expected_slot": due.last_covered_slot if due.interval_seconds is not None else None,
                "deadline": one_shot_deadline if due.interval_seconds is None else None,
                "reported_at": due.delivered_at or due.due_at or due.anchor,
                "facts": facts_value, "commentary": commentary,
                "return_condition": "current owner facts reconciled and next operation recorded"}
        prior_checkin = next((item for item in self._issue_reports(project)
            if isinstance(item.get("value"), Mapping)
            and item["value"].get("schema") == "otto.checkin.v1"
            and item["value"].get("occurrence_id") == occurrence_id
            and item["value"].get("assignment_ref") == assignment_ref
            and item["value"].get("generation") == generation), None)
        report = ({"ref": _ref(prior_checkin.get("ref"), "report_ref"), "kind": "report",
                   "generation": generation, "value": dict(prior_checkin["value"])}
                  if prior_checkin else self._append(assignment, body, key=key, actor=actor, generation=generation))
        evidence = {"kind": "otto.checkin.v1", "report_ref": report["ref"],
                    "occurrence_id": occurrence_id, "assignment_ref": assignment_ref,
                    "generation": generation}
        proof = {"schema": "otto.checkin.accepted-proof.v1", "project_ref": project["id"],
            "schedule_id": schedule_id,
            "generation": generation, "occurrence_id": occurrence_id,
            "expected_slot": body["expected_slot"], "deadline": body["deadline"],
            "report_ref": report["ref"]}
        accepted_history = tuple(item for item in due.accepted_checkins
            if not (isinstance(item, Mapping) and item.get("occurrence_id") == occurrence_id)) + (proof,)
        updated = DueRecord.from_dict({**due.to_dict(), "in_flight_request": None,
            "delivery_state": "returned", "last_completed_request": occurrence_id,
            "completed_at": _stamp(self.ports.now()), "completion_evidence": evidence,
            "completion_state": "succeeded", "last_result": {"report_ref": report["ref"]},
            "accepted_checkins": accepted_history,
            "version": due.version + 1})
        try:
            acknowledged = self.ports.due_records.save_due(
                schedule_id, updated.to_dict(), request_id="otto-checkin-ack:" + occurrence_id,
                expected_version=due.version)
            try:
                self._record_accepted_checkin(project, assignment, report, actor=actor,
                                              generation=generation)
            except Exception:
                # The acknowledgement and durable proof already committed in
                # DueRecord; the secondary human-readable report is advisory.
                pass
            return {"outcome": "accepted", "report_ref": report["ref"],
                    "occurrence_id": occurrence_id, "recovered": False,
                    "acknowledgement": _json(dict(acknowledged), "acknowledgement")}
        except Exception as exc:
            # A retry finds the idempotent report above, then checks if this exact
            # report has already been linked. It never creates a new occurrence.
            latest = self.ports.due_records.read_due(schedule_id)
            if isinstance(latest, Mapping):
                latest_due = DueRecord.from_dict(latest)
                linked = latest_due.completion_evidence or {}
                if (latest_due.last_completed_request == occurrence_id
                        and linked.get("report_ref") == report["ref"]
                        and proof in latest_due.accepted_checkins):
                    try:
                        self._record_accepted_checkin(project, assignment, report, actor=actor,
                                                      generation=generation)
                    except Exception:
                        pass
                    return {"outcome": "accepted", "report_ref": report["ref"],
                            "occurrence_id": occurrence_id, "recovered": True}
            return {"outcome": "pending", "report_ref": report["ref"],
                    "occurrence_id": occurrence_id, "recovery": "report_exists_ack_unknown",
                    "error": {"code": "checkin_ack_unknown", "message": str(exc)}}

    def _record_accepted_checkin(self, project: Mapping[str, Any], assignment: Any,
                                 report: Mapping[str, Any], *, actor: str,
                                 generation: int) -> dict[str, Any]:
        """Persist proof only after the DueRecord accepted the occurrence."""
        value = report.get("value")
        if not isinstance(value, Mapping) or value.get("schema") != "otto.checkin.v1":
            raise IssueLoopError("accepted check-in report is malformed")
        receipt = {"schema": "otto.checkin.accepted.v1", "project_ref": dict(project),
            "assignment_ref": _field(assignment, "ref"), "generation": generation,
            "schedule_id": value.get("schedule_id"), "occurrence_id": value.get("occurrence_id"),
            "expected_slot": value.get("expected_slot"), "deadline": value.get("deadline"),
            "checkin_report_ref": report.get("ref")}
        key = "otto-checkin-accepted:" + str(value.get("occurrence_id"))
        prior = next((item for item in self._issue_reports(project)
            if isinstance(item.get("value"), Mapping)
            and item["value"].get("schema") == "otto.checkin.accepted.v1"
            and item["value"].get("occurrence_id") == value.get("occurrence_id")), None)
        if prior:
            if prior["value"] != receipt:
                raise IssueLoopError("accepted check-in receipt conflicts with its report")
            return dict(prior)
        return self._append(assignment, receipt, key=key, actor=actor, generation=generation)

    def _issue_reports(self, project: Mapping[str, Any]) -> list[dict[str, Any]]:
        values = self.ports.reports_for_project(project)
        return [dict(item) for item in values if isinstance(item, Mapping)]

    @staticmethod
    def derive_issues(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Derive issue state from validated issue-linked append-only reports."""
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for report in reports:
            value = report.get("value")
            if not isinstance(value, Mapping) or value.get("schema") not in {
                    "otto.issue.v1", "otto.issue.response.v1", "otto.issue.outcome.v1",
                    "otto.issue.delivery.v1"}:
                continue
            issue_id = value.get("issue_id")
            if isinstance(issue_id, str) and issue_id:
                grouped.setdefault(issue_id, []).append(report)
        result = []
        for issue_id, items in grouped.items():
            items.sort(key=lambda item: (
                int(item.get("value", {}).get("issue_version", 0) or 0)
                if isinstance(item.get("value"), Mapping) else 0,
                str(item.get("value", {}).get("observed_at", ""))
                if isinstance(item.get("value"), Mapping) else "",
                int(item.get("version", 0) or 0),
                str(item.get("ref", {}).get("id", "")) if isinstance(item.get("ref"), Mapping) else ""))
            opened = next((item for item in items if item.get("value", {}).get("schema") == "otto.issue.v1"), None)
            if opened is None:
                continue
            lifecycle = [item["value"] for item in items if item.get("value", {}).get("schema") in
                         {"otto.issue.v1", "otto.issue.outcome.v1"}]
            state = "resolved" if lifecycle and lifecycle[-1].get("schema") == "otto.issue.outcome.v1" and lifecycle[-1].get("disposition") == "resolved" else "open"
            # Delivery receipts describe transport, never semantic disposition.
            latest = next(item["value"] for item in reversed(items)
                          if item["value"].get("schema") != "otto.issue.delivery.v1")
            result.append({"issue_id": issue_id, "state": state,
                "purpose": opened["value"].get("purpose", "operational_help"),
                "project_ref": opened["value"].get("project_ref"),
                "origin_assignment_ref": opened["value"].get("origin_assignment_ref"),
                "current_owner_ref": latest.get("current_owner_ref") or opened["value"].get("origin_assignment_ref"),
                "awaiting": latest.get("awaiting", "manager"),
                "opened_record": dict(opened["value"]),
                "reports": [item.get("ref") for item in items if item.get("ref") is not None],
                "last_record": dict(latest)})
        return sorted(result, key=lambda item: item["issue_id"])

    def read_issues(self, *, project_ref: Any) -> dict[str, Any]:
        project = _ref(project_ref, "project_ref")
        reports = self._issue_reports(project)
        issues = self.derive_issues(reports)
        for issue in issues:
            opened = issue.get("opened_record", {})
            identity = opened.get("overdue_identity") if isinstance(opened, Mapping) else None
            if (issue.get("state") == "open"
                    and opened.get("origin") == "trusted_supervisor_observation"
                    and opened.get("problem") == "overdue_checkin"
                    and self._project_due_proves(project, identity)):
                issue["state"] = "resolved"
                issue["awaiting"] = "none"
                issue["reconciled_by"] = "accepted_checkin"
                continue
            if issue.get("state") != "open":
                continue
            try:
                owner = (self.ports.current_manager(project) if issue.get("awaiting") == "manager"
                         else self._recipient(project, issue["purpose"]))
            except Exception:
                owner = None
            if owner is not None:
                issue["current_owner_ref"] = _ref(_field(owner, "ref"))
            else:
                issue["current_owner_ref"] = None
                issue["routing_state"] = "unresolved"
        for issue in issues:
            deliveries = [item["value"] for item in reports
                if isinstance(item.get("value"), Mapping)
                and item["value"].get("schema") == "otto.issue.delivery.v1"
                and item["value"].get("issue_id") == issue["issue_id"]]
            issue["deliveries"] = deliveries
        return {"outcome": "read", "issues": issues,
                "read_side_effects": False, "dispatch": False, "launch": False}

    def _route_delivery(self, *, project: Mapping[str, Any], issue_id: str,
                        recipient_assignment: Any, actor: str, message: Mapping[str, Any],
                        request_key: str) -> dict[str, Any]:
        recipient = _ref(_field(recipient_assignment, "ref"), "recipient_assignment_ref")
        intent = {"schema": "otto.issue.delivery.v1", "issue_id": issue_id,
                  "project_ref": project, "recipient_assignment_ref": recipient,
                  "current_owner_ref": recipient, "awaiting": "recipient",
                  "delivery_id": _stable("delivery", issue_id, request_key),
                  "state": "intent", "message": dict(message)}
        intent["recipient_generation"] = _field(recipient_assignment, "generation")
        intent["recipient_principal"] = _principal(recipient_assignment)
        intent["recipient_conversation"] = _field(recipient_assignment, "session")
        if callable(self.ports.recipient_conversation):
            intent["recipient_conversation"] = self.ports.recipient_conversation(project, recipient_assignment)
        prior = [item.get("value") for item in self._issue_reports(project)
                 if isinstance(item.get("value"), Mapping)
                 and item["value"].get("schema") == "otto.issue.delivery.v1"
                 and item["value"].get("delivery_id") == intent["delivery_id"]]
        if prior:
            original = prior[0]
            if (original.get("recipient_assignment_ref") != recipient
                    or "recipient_generation" in original and original["recipient_generation"] != intent["recipient_generation"]
                    or "recipient_conversation" in original and original["recipient_conversation"] != intent["recipient_conversation"]):
                return {"state": "stale", "delivery_id": intent["delivery_id"],
                        "reason": "retained recipient differs; reconcile before routing again", "retry": False}
            terminal = next((item for item in reversed(prior) if item.get("state") in {"sent", "unknown", "pending", "prepared", "unsupported"}), None)
            if terminal is not None:
                return {"state": terminal["state"], "delivery_id": intent["delivery_id"],
                        "receipt": terminal.get("receipt"), "transport": terminal.get("transport"),
                        "retry": False}
            if self.ports.delivery is not None:
                return {"state": "unknown", "delivery_id": intent["delivery_id"],
                        "transport": "unknown", "reason": "intent_exists_without_receipt", "retry": False}
            return {"state": "prepared", "delivery_id": intent["delivery_id"],
                    "recipient_assignment_ref": recipient, "message": dict(message),
                    "transport": "unsupported", "acknowledgement": "pending"}
        self._append(recipient_assignment, intent, key="otto-issue-delivery:" + intent["delivery_id"],
                     actor=actor, generation=int(_field(recipient_assignment, "generation", 1)))
        if self.ports.delivery is None:
            return {"state": "prepared", "delivery_id": intent["delivery_id"],
                    "recipient_assignment_ref": recipient, "message": dict(message),
                    "transport": "unsupported", "acknowledgement": "pending"}
        # Provider is finite and owner-issued. A lost response is unknown and the
        # same stable delivery identity is returned; this path never resends.
        try:
            value = self.ports.delivery.send(dict(intent))
        except Exception as exc:
            result = {"state": "unknown", "transport": "unknown", "error": str(exc), "retry": False}
            self._append(recipient_assignment, {"schema": "otto.issue.delivery.v1", "issue_id": issue_id,
                "project_ref": project, "delivery_id": intent["delivery_id"], "state": "unknown",
                "transport": "unknown", "message": dict(message)},
                key="otto-issue-delivery-result:" + intent["delivery_id"], actor=actor,
                generation=int(_field(recipient_assignment, "generation", 1)))
            return {**result, "delivery_id": intent["delivery_id"]}
        if not isinstance(value, Mapping):
            value = {"state": "unknown", "transport": "unknown"}
        state = value.get("state")
        if state not in {"sent", "prepared", "pending", "unknown", "unsupported"}:
            state = "unknown"
        receipt = value.get("receipt")
        if state == "sent" and not isinstance(receipt, Mapping):
            state = "unknown"
        if state in {"sent", "unknown", "pending", "prepared", "unsupported"}:
            self._append(recipient_assignment, {"schema": "otto.issue.delivery.v1", "issue_id": issue_id,
                "project_ref": project, "delivery_id": intent["delivery_id"], "state": state,
                "transport": value.get("transport", state), "receipt": _json(receipt, "receipt") if receipt is not None else None,
                "message": dict(message)}, key="otto-issue-delivery-result:" + intent["delivery_id"],
                actor=actor, generation=int(_field(recipient_assignment, "generation", 1)))
        return {**dict(value), "state": state, "delivery_id": intent["delivery_id"],
                "retry": False}

    def recover_delivery(self, *, project_ref: Any, delivery_id: str) -> dict[str, Any]:
        """Read/reconcile one existing delivery identity without sending again."""
        project, delivery_id = _ref(project_ref, "project_ref"), _text(delivery_id, "delivery_id")
        reports = self._issue_reports(project)
        records = [item.get("value") for item in reports if isinstance(item.get("value"), Mapping)
                   and item["value"].get("schema") == "otto.issue.delivery.v1"
                   and item["value"].get("delivery_id") == delivery_id]
        if not records:
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "error": {"code": "delivery_intent_missing"}, "retry": False}
        recorded = records[-1]
        if recorded.get("state") == "sent":
            return {"outcome": "sent", "delivery_id": delivery_id,
                    "receipt": recorded.get("receipt"), "retry": False}
        readback = getattr(self.ports.delivery, "read_delivery", None) if self.ports.delivery is not None else None
        if not callable(readback):
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "transport": "unsupported", "retry": False}
        try:
            value = readback(delivery_id)
        except Exception as exc:
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "transport": "unknown", "error": str(exc), "retry": False}
        if not isinstance(value, Mapping):
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "transport": "unknown", "retry": False}
        return {**dict(value), "delivery_id": delivery_id,
                "outcome": value.get("outcome", "unknown"), "retry": False}

    def submit_issue(self, *, project_ref: Any, assignment_ref: Any, generation: int,
                     actor: str, issue_key: str, problem: str, evidence: Sequence[Any],
                     impact: str, requested_decision: str,
                     return_condition: str, request_id: str,
                     purpose: str = "operational_help") -> dict[str, Any]:
        project, assignment_ref = _ref(project_ref, "project_ref"), _ref(assignment_ref, "assignment_ref")
        actor, issue_key = _text(actor, "actor"), _text(issue_key, "issue_key")
        request_id = _text(request_id, "request_id")
        for name, value in (("problem", problem), ("impact", impact),
                            ("requested_decision", requested_decision), ("return_condition", return_condition)):
            _text(value, name)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise IssueLoopError("generation must be a positive integer")
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise IssueLoopError("evidence must be a sequence of references or facts")
        evidence_value = _json(list(evidence), "evidence")
        manager = self._manager(project, assignment_ref, actor, generation)
        if purpose == "advice":
            # Explicit disabled policy fails before appending or consuming allowance.
            supervisor = self._recipient(project, purpose)
            if supervisor is None:
                raise IssueLoopError("advisor is unavailable")
        else:
            if purpose != "operational_help":
                raise IssueLoopError("purpose must be advice or operational_help")
            try:
                supervisor = self._recipient(project, purpose)
            except Exception:
                supervisor = None
        issue_id = (_stable("issue", project.get("id"), issue_key) if purpose == "operational_help"
                    else _stable("issue", project.get("id"), purpose, issue_key))
        project_reports = self._issue_reports(project)
        existing = next((item for item in self.derive_issues(project_reports)
                         if item["issue_id"] == issue_id), None)
        prior_submission = next((item for item in project_reports
            if isinstance(item.get("value"), Mapping)
            and item["value"].get("schema") == "otto.issue.v1"
            and item["value"].get("issue_id") == issue_id
            and item["value"].get("request_id") == request_id), None)
        if existing is not None and existing["state"] == "open" and prior_submission is None:
            original = next(item for item in project_reports if isinstance(item.get("value"), Mapping)
                and item["value"].get("schema") == "otto.issue.v1" and item["value"].get("issue_id") == issue_id)
            original_ref = _ref(original["ref"])
            delivery = (self._route_delivery(project=project, issue_id=issue_id, recipient_assignment=supervisor,
                actor=actor, message={"type": "issue", "issue_id": issue_id, "report_ref": original_ref},
                request_key="submit:" + original_ref["id"]) if supervisor is not None
                else {"state": "pending", "transport": "unsupported", "retry": False})
            return {"outcome": "existing", "issue_id": issue_id,
                    "report_ref": original_ref, "delivery": delivery, "reopened": False}
        issue = {"schema": "otto.issue.v1", "issue_id": issue_id, "project_ref": project,
                 "origin_assignment_ref": (existing.get("origin_assignment_ref") if existing else assignment_ref),
                 "origin_generation": generation,
                 "current_owner_ref": (_ref(_field(supervisor, "ref"), "supervisor_assignment_ref")
                                       if supervisor is not None else None),
                 "problem": _text(problem, "problem"), "evidence": evidence_value,
                 "impact": _text(impact, "impact"),
                 "requested_decision": _text(requested_decision, "requested_decision"),
                 "return_condition": _text(return_condition, "return_condition"),
                 "awaiting": "advisor" if purpose == "advice" else "orchestrator", "observed_at": _stamp(self.ports.now()),
                 "routing_state": "resolved" if supervisor is not None else "unresolved",
                 "routing_repair_owner": None if supervisor is not None else "activating_owner",
                 "reopens": (bool(prior_submission["value"].get("reopens")) if prior_submission is not None
                             else bool(existing and existing["state"] == "resolved")),
                 "issue_version": self._next_issue_version(project, issue_id), "request_id": request_id}
        if purpose == "advice":
            issue["purpose"] = purpose
        report = self._append_issue_record(project, manager, issue, request_id=request_id,
                              actor=actor, generation=generation)
        if supervisor is None:
            return {"outcome": "submitted", "issue_id": issue_id, "report_ref": report["ref"],
                    "routing": {"state": "unresolved", "repair_owner": "activating_owner"},
                    "delivery": {"state": "pending", "transport": "unsupported"},
                    "reopened": issue["reopens"]}
        delivery = self._route_delivery(project=project, issue_id=issue_id, recipient_assignment=supervisor,
            actor=actor, message={"type": "issue", "issue_id": issue_id, "report_ref": report["ref"]},
            request_key="submit:" + report["ref"]["id"])
        return {"outcome": "submitted", "issue_id": issue_id, "report_ref": report["ref"],
                "delivery": delivery, "reopened": issue["reopens"]}

    def respond_to_issue(self, *, project_ref: Any, issue_id: str, actor: str,
                         authority_source: str, response: str, proposed_solution: str,
                         next_action: str, request_id: str,
                         user_decision: Optional[str] = None) -> dict[str, Any]:
        project, issue_id = _ref(project_ref, "project_ref"), _text(issue_id, "issue_id")
        actor, request_id = _text(actor, "actor"), _text(request_id, "request_id")
        issues = self.derive_issues(self._issue_reports(project))
        issue = next((item for item in issues if item["issue_id"] == issue_id), None)
        if issue is None:
            raise IssueLoopError("issue does not exist in this project")
        supervisor = self._recipient(project, issue["purpose"])
        if supervisor is None or _principal(supervisor) != actor:
            raise IssueLoopError("actor is not the current issue recipient")
        for name, value in (("authority_source", authority_source), ("response", response),
                            ("proposed_solution", proposed_solution), ("next_action", next_action)):
            _text(value, name)
        user_only = user_decision is not None
        if issue["purpose"] == "advice" and user_only:
            raise IssueLoopError("advisor suggestions cannot become owner decisions")
        decision_value = _text(user_decision, "user_decision") if user_only else None
        for prior in self._issue_reports(project):
            value = prior.get("value")
            if not isinstance(value, Mapping) or value.get("schema") != "otto.issue.response.v1" or value.get("request_id") != request_id:
                continue
            expected = {"schema": "otto.issue.response.v1", "issue_id": issue_id,
                "project_ref": project, "response": response.strip(),
                "authority_source": authority_source.strip(), "proposed_solution": proposed_solution.strip(),
                "next_action": next_action.strip(), "user_decision": decision_value,
                "awaiting": "user" if user_only else "manager", "request_id": request_id}
            if any(value.get(key) != expected_value for key, expected_value in expected.items()):
                raise IssueLoopError("request_id was reused with changed issue input")
            manager = self.ports.current_manager(project)
            if (value.get("current_owner_ref") != _ref(_field(supervisor if user_only else manager, "ref"))
                    or value.get("manager_generation", _field(manager, "generation")) != _field(manager, "generation")
                    or value.get("responding_assignment_ref", _ref(_field(supervisor, "ref"))) != _ref(_field(supervisor, "ref"))):
                raise IssueLoopError("retained response recipient is stale")
            delivery = self._route_delivery(project=project, issue_id=issue_id, recipient_assignment=manager,
                actor=actor, message={"type": "issue_response", "issue_id": issue_id, "report_ref": _ref(prior.get("ref"))},
                request_key="response:" + _ref(prior.get("ref"))["id"]) if not user_only else None
            return {"outcome": "awaiting_user" if user_only else "responded", "issue_id": issue_id,
                "report_ref": _ref(prior.get("ref"), "report_ref"),
                "current_owner_ref": value.get("current_owner_ref"),
                "delivery": delivery, "replayed": True}
        issues = self.derive_issues(self._issue_reports(project))
        issue = next((item for item in issues if item["issue_id"] == issue_id), None)
        if issue is None or issue["state"] != "open":
            raise IssueLoopError("issue is not currently open")
        origin = next(item for item in self._issue_reports(project)
                      if isinstance(item.get("value"), Mapping) and item["value"].get("issue_id") == issue_id
                      and item["value"].get("schema") == "otto.issue.v1")
        manager = self.ports.current_manager(project)
        current_manager_ref = _ref(_field(manager, "ref"), "manager_assignment_ref")
        body = {"schema": "otto.issue.response.v1", "issue_id": issue_id,
                "project_ref": project, "response": _text(response, "response"),
                "authority_source": _text(authority_source, "authority_source"),
                "proposed_solution": _text(proposed_solution, "proposed_solution"),
                "next_action": _text(next_action, "next_action"),
                "user_decision": decision_value,
                "awaiting": "user" if user_only else "manager", "request_id": request_id,
                "observed_at": _stamp(self.ports.now()),
                "issue_version": self._next_issue_version(project, issue_id),
                "responding_assignment_ref": _ref(_field(supervisor, "ref")),
                "responding_generation": _field(supervisor, "generation"),
                "manager_generation": _field(manager, "generation"),
                "authority_kind": "suggestion" if issue["purpose"] == "advice" else "operational_response",
                "current_owner_ref": (_ref(_field(supervisor, "ref")) if user_only else current_manager_ref),
                }
        report = self._append_issue_record(project, supervisor, body, request_id=request_id,
                              actor=actor, generation=int(_field(supervisor, "generation", 1)))
        if user_only:
            return {"outcome": "awaiting_user", "issue_id": issue_id, "report_ref": report["ref"],
                    "current_owner_ref": body["current_owner_ref"], "delivery": {"state": "pending", "transport": "unsupported"}}
        delivery = self._route_delivery(project=project, issue_id=issue_id, recipient_assignment=manager,
            actor=actor, message={"type": "issue_response", "issue_id": issue_id, "report_ref": report["ref"]},
            request_key="response:" + report["ref"]["id"])
        return {"outcome": "responded", "issue_id": issue_id, "report_ref": report["ref"], "delivery": delivery}

    def record_issue_outcome(self, *, project_ref: Any, assignment_ref: Any, generation: int,
                             actor: str, issue_id: str, disposition: str, evidence: Sequence[Any],
                             request_id: str, next_action: str = "") -> dict[str, Any]:
        project, assignment_ref = _ref(project_ref, "project_ref"), _ref(assignment_ref, "assignment_ref")
        actor, issue_id = _text(actor, "actor"), _text(issue_id, "issue_id")
        request_id = _text(request_id, "request_id")
        if disposition not in {"resolved", "reopen", "progress"}:
            raise IssueLoopError("disposition must be resolved, reopen, or progress")
        manager = self._manager(project, assignment_ref, actor, generation)
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise IssueLoopError("evidence must be a sequence")
        evidence_value = _json(list(evidence), "evidence")
        if disposition in {"resolved", "reopen"} and not evidence_value:
            raise IssueLoopError("resolution and reopen require evidence")
        # Recover an already committed result before checking its now-invalid
        # transition (for example, resolved -> resolve replay).
        for prior in self._issue_reports(project):
            value = prior.get("value")
            if not isinstance(value, Mapping) or value.get("schema") != "otto.issue.outcome.v1" or value.get("request_id") != request_id:
                continue
            expected = {"schema": "otto.issue.outcome.v1", "issue_id": issue_id,
                "project_ref": project, "disposition": disposition,
                "evidence": evidence_value,
                "next_action": _text(next_action, "next_action") if next_action else "",
                "request_id": request_id}
            if any(value.get(key) != expected_value for key, expected_value in expected.items()):
                raise IssueLoopError("request_id was reused with changed issue input")
            state = "resolved" if disposition == "resolved" else "open"
            return {"outcome": "recorded", "issue_id": issue_id, "state": state,
                "report_ref": _ref(prior.get("ref"), "report_ref"), "delivery": None, "replayed": True}
        issues = self.derive_issues(self._issue_reports(project))
        issue = next((item for item in issues if item["issue_id"] == issue_id), None)
        if issue is None:
            raise IssueLoopError("issue does not exist in this project")
        if disposition == "resolved" and issue["state"] != "open":
            raise IssueLoopError("only an open issue can be resolved")
        if disposition == "reopen" and issue["state"] != "resolved":
            raise IssueLoopError("only a resolved issue can be reopened")
        all_issue_reports = self._issue_reports(project)
        current_issue = next(item for item in issues if item["issue_id"] == issue_id)
        semantic = [item for item in all_issue_reports
            if isinstance(item.get("value"), Mapping)
            and item["value"].get("schema") in {"otto.issue.v1", "otto.issue.response.v1", "otto.issue.outcome.v1"}
            and item["value"].get("issue_id") == issue_id]
        semantic.sort(key=lambda item: (
            int(item["value"].get("issue_version", 0) or 0),
            str(item["value"].get("observed_at", "")),
            int(item.get("version", 0) or 0)))
        latest = semantic[-1]["value"] if semantic else {}
        response_record = next((item for item in reversed(all_issue_reports)
            if isinstance(item.get("value"), Mapping)
            and item["value"].get("schema") == "otto.issue.response.v1"
            and item["value"].get("issue_id") == issue_id
            and item["value"] == latest), None)
        current_manager_ref = _ref(_field(manager, "ref"), "manager_assignment_ref")
        if (disposition == "resolved" and (current_issue.get("awaiting") != "manager"
                or latest.get("schema") != "otto.issue.response.v1"
                or latest.get("awaiting") != "manager"
                or _ref_id(latest.get("current_owner_ref")) != current_manager_ref["id"])):
            raise IssueLoopError("resolution requires the current authorized manager response")
        if disposition == "resolved" and response_record is None:
            raise IssueLoopError("resolution requires an authorized response to apply")
        if disposition == "progress":
            if issue["state"] != "open":
                raise IssueLoopError("only an open issue can record progress; use reopen with evidence")
            if (current_issue.get("awaiting") != "manager"
                    or latest.get("schema") != "otto.issue.response.v1"
                    or latest.get("awaiting") != "manager"
                    or _ref_id(latest.get("current_owner_ref")) != current_manager_ref["id"]
                    or response_record is None):
                raise IssueLoopError("progress requires the current authorized manager response")
        supervisor = self._recipient(project, issue["purpose"])
        if supervisor is None:
            raise IssueLoopError("current accountable orchestrator is unresolved")
        if disposition in {"resolved", "progress"} and latest.get("responding_assignment_ref") is not None:
            if (latest["responding_assignment_ref"] != _ref(_field(supervisor, "ref"))
                    or latest.get("responding_generation") != _field(supervisor, "generation")
                    or latest.get("manager_generation") != generation):
                raise IssueLoopError("response recipient or manager generation is stale")
        body = {"schema": "otto.issue.outcome.v1", "issue_id": issue_id,
                "project_ref": project, "disposition": disposition,
                "evidence": evidence_value, "next_action": _text(next_action, "next_action") if next_action else "",
                "applied_response_ref": response_record.get("ref") if response_record is not None else None,
                "manager_assignment_ref": current_manager_ref, "manager_generation": generation,
                "current_owner_ref": _ref(_field(supervisor, "ref")),
                "awaiting": "orchestrator" if disposition != "resolved" else "none",
                "request_id": request_id, "observed_at": _stamp(self.ports.now()),
                "issue_version": self._next_issue_version(project, issue_id)}
        report = self._append_issue_record(project, manager, body, request_id=request_id,
                              actor=actor, generation=generation)
        if disposition == "reopen":
            delivery = self._route_delivery(project=project, issue_id=issue_id,
                recipient_assignment=supervisor, actor=actor,
                message={"type": "issue_reopened", "issue_id": issue_id, "report_ref": report["ref"]},
                request_key="reopen:" + report["ref"]["id"])
        else:
            delivery = None
        return {"outcome": "recorded", "issue_id": issue_id,
                "state": "resolved" if disposition == "resolved" else "open", "report_ref": report["ref"],
                "delivery": delivery}

    def _record_supervisor_observation(self, *, project_ref: Any, candidate: Mapping[str, Any],
                                       request_id: str) -> dict[str, Any]:
        """Trusted owner-only path from a fresh selector result into issue history.

        No actor/origin argument is accepted from the caller. The current
        supervision binding supplies the authenticated supervisor identity.
        """
        project = _ref(project_ref, "project_ref")
        request_id = _text(request_id, "request_id")
        selected = self.select_supervision(projects=[project])
        issue_id = candidate.get("issue_id")
        current = next((item for item in selected if item.get("issue_id") == issue_id
                        and item.get("kind") == candidate.get("kind")), None)
        if current is None:
            raise IssueLoopError("supervisor observation is no longer selected from current owner evidence")
        supervisor = self.ports.current_supervisor(project)
        if supervisor is None:
            return {"outcome": "pending", "issue_id": issue_id,
                    "routing": {"state": "unresolved", "repair_owner": "activating_owner"},
                    "delivery": {"state": "unsupported", "retry": False}}
        actor = _principal(supervisor)
        if not actor:
            raise IssueLoopError("current supervisor principal is unavailable")
        supervisor_ref = _ref(_field(supervisor, "ref"), "supervisor_assignment_ref")
        issue = {"schema": "otto.issue.v1", "issue_id": issue_id,
            "project_ref": project, "origin": "trusted_supervisor_observation",
            "origin_assignment_ref": current.get("assignment_ref"),
            "origin_generation": current.get("generation", 1),
            "source_ref": current.get("cause_ref"), "current_owner_ref": supervisor_ref,
            "problem": current.get("kind", "actionable owner observation"),
            "evidence": [current.get("cause_ref")] if current.get("cause_ref") is not None else [],
            "impact": "requires accountable orchestrator review",
            "requested_decision": "review observation and assign the next authorized action",
            "return_condition": "record a response and evidence-backed outcome",
            "awaiting": "orchestrator", "routing_state": "resolved",
            "overdue_identity": current.get("overdue_identity"),
            "request_id": request_id, "observed_at": _stamp(self.ports.now()),
            "issue_version": self._next_issue_version(project, str(issue_id))}
        report = self._append_issue_record(project, supervisor, issue,
            request_id=request_id, actor=actor,
            generation=int(_field(supervisor, "generation", 1)))
        delivery = self._route_delivery(project=project, issue_id=str(issue_id),
            recipient_assignment=supervisor, actor=actor,
            message={"type": "supervisor_observation", "issue_id": issue_id,
                     "report_ref": report["ref"]}, request_key="supervision:" + str(issue_id))
        return {"outcome": "observed", "origin": "trusted_supervisor_observation",
                "issue_id": issue_id, "report_ref": report["ref"], "delivery": delivery}

    def reconcile_supervision(self, *, projects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Owner lifecycle entry: persist fresh exceptions without repeated pings."""
        results = []
        for candidate in self.select_supervision(projects=projects):
            if candidate["kind"] == "open_issue":
                results.append({"outcome": "already_open", "issue_id": candidate["issue_id"]})
                continue
            results.append(self._record_supervisor_observation(
                project_ref=candidate["project_ref"], candidate=candidate,
                request_id="otto-supervision:" + candidate["issue_id"],
            ))
        return results

    def select_supervision(self, *, projects: Sequence[Mapping[str, Any]],
                           reports_by_project: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
                           now: Optional[datetime] = None, grace_seconds: int = 600) -> list[dict[str, Any]]:
        """Select independent exceptions; ordinary task dependency waits stay quiet."""
        if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or grace_seconds < 0:
            raise IssueLoopError("grace_seconds must be a non-negative integer")
        observed_at = now or self.ports.now()
        if observed_at.tzinfo is None:
            raise IssueLoopError("now must be timezone-aware")
        selected: dict[str, dict[str, Any]] = {}
        for raw_project in projects:
            project = _ref(raw_project, "project_ref")
            reports = list((reports_by_project or {}).get(project["id"], self._issue_reports(project)))
            existing_issues = self.derive_issues(reports)
            # A successful accepted check-in closes only the exact overdue
            # episode whose schedule/generation/slot (or one-shot deadline)
            # it proves. This is derived from existing reports and stays
            # read-only; unrelated supervisor issues remain open.
            due_values = self.ports.due_records_for_project(project)
            from otto.attention import DueRecord
            accepted_checkins = []
            for raw in due_values:
                completed_due = DueRecord.from_dict(raw)
                accepted_checkins.extend(proof for proof in completed_due.accepted_checkins
                    if isinstance(proof, Mapping) and self._due_proves(completed_due, proof))
            def report_proves(identity: Any) -> bool:
                if not isinstance(identity, Mapping):
                    return False
                for checkin in accepted_checkins:
                    if (checkin.get("schedule_id") == identity.get("schedule_id")
                            and checkin.get("generation") == identity.get("generation")
                            and checkin.get("expected_slot") == identity.get("expected_slot")
                            and checkin.get("deadline") == identity.get("deadline")):
                        return True
                return False
            if any(item["state"] == "open" for item in existing_issues):
                for issue in existing_issues:
                    if issue["state"] == "open":
                        issue_value = issue.get("opened_record", {})
                        if (issue_value.get("origin") == "trusted_supervisor_observation"
                                and issue_value.get("problem") == "overdue_checkin"
                                and report_proves(issue_value.get("overdue_identity"))):
                            continue
                        selected[issue["issue_id"]] = {"kind": "open_issue", **issue}
            for raw in due_values:
                from otto.attention import DueRecord
                due = DueRecord.from_dict(raw)
                if due.stop_state != "active":
                    continue
                if (due.interval_seconds is None and due.completion_state == "succeeded"
                        and isinstance(due.completion_evidence, Mapping)
                        and due.completion_evidence.get("kind") == "otto.checkin.v1"):
                    # A completed one-shot is terminal; do not manufacture a
                    # synthetic next occurrence for its old deadline.
                    continue
                if (due.completion_state == "succeeded" and isinstance(due.completion_evidence, Mapping)
                        and due.completion_evidence.get("kind") == "otto.checkin.v1"):
                    completed_occurrence = due.completion_evidence.get("occurrence_id")
                else:
                    completed_occurrence = None
                if due.in_flight_request:
                    admitted_occurrence = due.in_flight_request
                    if due.interval_seconds is not None:
                        anchor = datetime.fromisoformat(due.anchor.replace("Z", "+00:00"))
                        deadline = anchor + timedelta(seconds=due.last_covered_slot * due.interval_seconds)
                        expected_slot = due.last_covered_slot
                    else:
                        deadline = (datetime.fromisoformat(due.due_at.replace("Z", "+00:00"))
                                    if due.due_at else datetime.fromisoformat(due.anchor.replace("Z", "+00:00")))
                        expected_slot = None
                elif due.interval_seconds is not None:
                    slot = due.last_covered_slot + 1
                    anchor = datetime.fromisoformat(due.anchor.replace("Z", "+00:00"))
                    elapsed = (observed_at.astimezone(timezone.utc) - anchor.astimezone(timezone.utc)).total_seconds()
                    if int(elapsed // due.interval_seconds) < slot:
                        continue
                    deadline = anchor + timedelta(seconds=slot * due.interval_seconds)
                    admitted_occurrence = None
                    expected_slot = slot
                elif due.due_at:
                    deadline = datetime.fromisoformat(due.due_at.replace("Z", "+00:00"))
                    admitted_occurrence = None
                    expected_slot = None
                else:
                    continue
                deadline_identity = deadline.astimezone(timezone.utc).isoformat()
                identity = {"schedule_id": due.schedule_id, "generation": due.generation,
                    "expected_slot": expected_slot,
                    "deadline": None if due.interval_seconds is not None else deadline_identity}
                occurrence = _stable("overdue-episode", due.schedule_id, due.generation,
                    expected_slot if expected_slot is not None else deadline_identity)
                if admitted_occurrence is not None and admitted_occurrence == completed_occurrence:
                    continue
                if observed_at.astimezone(timezone.utc) <= deadline.astimezone(timezone.utc) + timedelta(seconds=grace_seconds):
                    continue
                assignment_ref = ({"authority": project.get("authority"), "kind": "work.assignment", "id": due.manager_ref}
                                  if due.manager_ref else {})
                report = next((item for item in accepted_checkins
                    if item.get("schedule_id") == due.schedule_id
                    and item.get("expected_slot") == expected_slot
                    and item.get("deadline") == identity["deadline"]
                    and item.get("generation") == due.generation), None)
                if report:
                    continue
                key = _stable("overdue", project["id"], due.schedule_id, due.generation,
                    expected_slot if expected_slot is not None else deadline_identity)
                try:
                    supervisor = self.ports.current_supervisor(project)
                except Exception:
                    supervisor = None
                selected.setdefault(key, {"issue_id": key, "kind": "overdue_checkin",
                    "project_ref": project, "assignment_ref": assignment_ref,
                    "generation": due.generation, "due_at": deadline.isoformat(),
                    "occurrence_id": occurrence, "admitted_occurrence_id": admitted_occurrence,
                    "overdue_identity": identity,
                    "cause_ref": {"authority": project.get("authority"), "kind": "otto.due-record", "id": due.schedule_id},
                    "current_owner_ref": _ref(_field(supervisor, "ref")) if supervisor is not None else None,
                    "routing_state": "resolved" if supervisor is not None else "unresolved"})
            # Rejected/error observations are actionable. Dependency waits are
            # deliberately not selected by themselves.
            for report in reports:
                value = report.get("value")
                if not isinstance(value, Mapping) or value.get("observation_kind") not in {"result", "report"}:
                    continue
                state = str(value.get("status", value.get("outcome", ""))).lower()
                if state not in {"rejected", "blocked", "error", "failed"}:
                    continue
                correction_failed = value.get("correction_failed") is True
                actionable_manager = (value.get("manager_actionable") is True
                    or value.get("actionable_manager_issue") is True
                    or value.get("issue_class") in {"authority", "resource", "decision", "failed_correction"})
                if value.get("dependency_wait") is True and not correction_failed:
                    continue
                if value.get("manager_correction") is True and not correction_failed:
                    continue
                if not actionable_manager and not correction_failed:
                    continue
                ref = report.get("ref")
                key = _stable("actionable", project["id"], ref)
                try:
                    supervisor = self.ports.current_supervisor(project)
                except Exception:
                    supervisor = None
                selected.setdefault(key, {"issue_id": key, "kind": "actionable_observation",
                    "project_ref": project, "cause_ref": ref, "status": state,
                    "current_owner_ref": _ref(_field(supervisor, "ref")) if supervisor is not None else None,
                    "routing_state": "resolved" if supervisor is not None else "unresolved"})
        return [selected[key] for key in sorted(selected)]


__all__ = ["IssueLoop", "IssueLoopError", "IssueLoopPorts"]

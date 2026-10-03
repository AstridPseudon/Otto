"""One-shot project-advisor wake, decision delivery, and effect follow-up.

This module composes existing owner records and host/runtime ports.  Assignment
reports remain the decision/delivery history, ``DueRecord`` remains the wake
and follow-up record, and the canonical role runtime remains the only execution
path.  No transport, scheduler, or second issue ledger is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Optional, Sequence

from ..attention import DueRecord, DurableAttention
from .advisor_pairing import AdvisorPairing, conversation_for, validate_recipient


class AdvisorDeliveryError(ValueError):
    """A wake, delivery, or observation is stale or outside the pairing."""


def _json(value: Any, field: str) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise AdvisorDeliveryError(f"{field} must contain JSON values") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AdvisorDeliveryError(f"{field} must be non-blank text")
    return value.strip()


def _ref(value: Any, field: str) -> dict[str, Any]:
    value = _json(value, field)
    if not isinstance(value, Mapping):
        raise AdvisorDeliveryError(f"{field} must be a reference")
    for key in ("authority", "kind", "id", "revision"):
        _text(value.get(key), f"{field}.{key}")
    return {key: value[key] for key in ("authority", "kind", "id", "revision")}


def _stable(prefix: str, *parts: Any) -> str:
    wire = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + "-" + sha256(wire.encode("utf-8")).hexdigest()[:28]


def _stamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AdvisorDeliveryError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


def _observed_stamp(value: Any, field: str) -> str:
    """Return one native observation timestamp in normalized UTC form."""

    value = _text(value, field)
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdvisorDeliveryError(f"{field} must be an ISO-8601 timestamp") from exc
    if observed.tzinfo is None:
        raise AdvisorDeliveryError(f"{field} must be timezone-aware")
    return _stamp(observed)


def _seconds(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdvisorDeliveryError(f"{field} must be a positive integer")
    return value


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
        payload = value.get("payload")
        return payload.get(name, default) if isinstance(payload, Mapping) else default
    return getattr(value, name, default)


def _principal(value: Any) -> str:
    value = _field(value, "principal", value)
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("principal")
    return value if isinstance(value, str) else ""


_SESSION_KEYS = (
    "native_id", "physical_session_id", "conversation_id", "thread_id", "session_id", "id",
)


def _session_identity(value: Any, field: str) -> str:
    """Return one unambiguous native-session identity from a conversation."""

    if not isinstance(value, Mapping):
        raise AdvisorDeliveryError(f"{field} must be a conversation reference")
    identities = {
        item.strip() for key in _SESSION_KEYS
        if isinstance((item := value.get(key)), str) and item.strip()
    }
    if len(identities) != 1:
        raise AdvisorDeliveryError(f"{field} must identify one exact native session")
    return next(iter(identities))


def _exact_consumption_receipt(
    value: Any, *, recipient: Mapping[str, Any], delivery_id: str,
) -> Optional[dict[str, Any]]:
    """Accept only a receipt proving consumption by the pinned native session."""

    if not isinstance(value, Mapping) or value.get("state") != "sent":
        return None
    receipt = value.get("receipt")
    if not isinstance(receipt, Mapping):
        return None
    try:
        expected_session = _session_identity(recipient, "recipient")
    except AdvisorDeliveryError:
        return None
    if (
        receipt.get("schema") != "otto.exact-session-consumption.v1"
        or receipt.get("delivery_id") != delivery_id
        or receipt.get("physical_session_id") != expected_session
        or receipt.get("transport") != "owner-host-continuation"
        or receipt.get("consumed") is not True
        or not isinstance(receipt.get("observed_turn_id"), str)
        or not receipt["observed_turn_id"].strip()
    ):
        return None
    result = _json(dict(receipt), "receipt")
    observed_at = result.get("observed_at")
    if observed_at is not None:
        try:
            result["observed_at"] = _observed_stamp(observed_at, "receipt.observed_at")
        except AdvisorDeliveryError:
            return None
    return result


@dataclass(frozen=True)
class ExactSessionDelivery:
    """Adapt existing host continuation/readback operations to delivery.

    The continuation operation remains responsible for authorization, native
    execution, and its durable occurrence.  This adapter creates no ledger: it
    requires either a native message/turn admission or a successful result from
    the exact requested session, with the native turn identity and observation
    timestamp, before reporting consumption.
    """

    continue_session: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    read_session_delivery: Callable[[str], Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not callable(self.continue_session) or not callable(self.read_session_delivery):
            raise TypeError("exact-session delivery requires continuation and readback operations")

    @staticmethod
    def _result(value: Any, *, delivery_id: str, session_id: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {"state": "unknown", "retry": False}
        if isinstance(value.get("result"), Mapping):
            result = value["result"]
        elif isinstance(value.get("last_result"), Mapping):
            result = value["last_result"]
        else:
            result = value
        outcome = result.get("outcome", value.get("outcome"))
        if (outcome is None and value.get("completion_state") == "succeeded"
                and value.get("delivery_state") == "returned"):
            outcome = "succeeded"
        admission = result.get("delivery_admission")
        if not isinstance(admission, Mapping):
            admission = value.get("delivery_admission")
        if not isinstance(admission, Mapping):
            admission = {}
        observed_session = (
            admission.get("physical_session_id") or admission.get("native_session_id")
            or result.get("physical_session_id") or result.get("native_session_id")
        )
        turn_id = (
            admission.get("observed_turn_id") or admission.get("turn_id")
            or result.get("observed_turn_id") or result.get("turn_id")
        )
        observed_at = next((item for item in (
            admission.get("observed_at"), admission.get("message_admitted_at"),
            admission.get("turn_started_at"), result.get("message_admitted_at"),
            result.get("turn_started_at"), result.get("observed_turn_started_at"),
            value.get("message_admitted_at"), value.get("turn_started_at"),
            value.get("observed_turn_started_at"),
        ) if isinstance(item, str) and item.strip()), None)
        admitted = (
            outcome in {"succeeded", "returned"}
            or admission.get("message_admitted") is True
            or admission.get("native_turn_started") is True
            or admission.get("state") in {"message_admitted", "turn_started"}
            or result.get("message_admitted") is True
            or result.get("native_turn_started") is True
        )
        try:
            observed_at = _observed_stamp(observed_at, "delivery_admission.observed_at")
        except AdvisorDeliveryError:
            observed_at = None
        if admitted and observed_session == session_id \
                and isinstance(turn_id, str) and turn_id.strip() and observed_at is not None:
            return {
                "state": "sent",
                "receipt": {
                    "schema": "otto.exact-session-consumption.v1",
                    "delivery_id": delivery_id,
                    "physical_session_id": session_id,
                    "observed_turn_id": turn_id.strip(),
                    "observed_at": observed_at,
                    "consumed": True,
                    "transport": "owner-host-continuation",
                },
                "sent_at": observed_at,
                "retry": False,
            }
        if outcome in {"started", "active", "pending"}:
            return {"state": "started", "retry": False}
        return {"state": "unknown", "retry": False}

    def send(self, value: Mapping[str, Any]) -> dict[str, Any]:
        delivery_id = _text(value.get("delivery_id"), "delivery_id")
        recipient = value.get("recipient") or value.get("target")
        session_id = _session_identity(recipient, "recipient")
        request = {
            "schema": "otto.exact-session-delivery.v1",
            "delivery_id": delivery_id,
            "logical_request_key": "otto-advisor-delivery:" + delivery_id,
            "operation": "resume",
            "physical_session_id": session_id,
            "recipient": dict(recipient),
            "message": _json(value.get("message"), "message"),
        }
        return self._result(
            self.continue_session(request), delivery_id=delivery_id, session_id=session_id,
        )

    def read_delivery(self, delivery_id: str) -> dict[str, Any]:
        delivery_id = _text(delivery_id, "delivery_id")
        value = self.read_session_delivery(delivery_id)
        if not isinstance(value, Mapping):
            return {"state": "unknown", "retry": False}
        recipient = value.get("recipient") or value.get("target")
        try:
            session_id = _session_identity(recipient, "readback.recipient")
        except AdvisorDeliveryError:
            return {"state": "unknown", "retry": False}
        return self._result(value, delivery_id=delivery_id, session_id=session_id)


@dataclass(frozen=True)
class AdvisorDeliveryPorts:
    """Finite owner/host capabilities used by :class:`AdvisorDeliveryLoop`."""

    assignments: Any
    attention: DurableAttention
    authenticate: Callable[[str], Any]
    current_pairing: Callable[[Mapping[str, Any]], AdvisorPairing]
    reports_for_project: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    role_delivery: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    delivery: Any = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class AdvisorDeliveryLoop:
    """Recoverable communication loop for one current manager/advisor pair."""

    def __init__(self, ports: AdvisorDeliveryPorts) -> None:
        if not isinstance(ports.attention, DurableAttention):
            raise TypeError("attention must be DurableAttention")
        for name in ("authenticate", "current_pairing", "reports_for_project", "role_delivery", "now"):
            if not callable(getattr(ports, name)):
                raise TypeError(f"{name} must be callable")
        if not callable(getattr(ports.assignments, "get", None)) or not callable(
            getattr(ports.assignments, "append_report", None)
        ):
            raise TypeError("assignments must expose get and append_report")
        self.ports = ports

    @staticmethod
    def _same_pairing(left: AdvisorPairing, right: AdvisorPairing) -> bool:
        left_value, right_value = left.to_dict(), right.to_dict()
        # The inspection cursor advances inside one valid conversation.  It is
        # context, not recipient authority, so only the identity/generation
        # and conversation bindings fence communication effects.
        left_value.pop("cursor", None)
        right_value.pop("cursor", None)
        return left_value == right_value

    def _current(self, expected: AdvisorPairing) -> AdvisorPairing:
        if not isinstance(expected, AdvisorPairing):
            raise TypeError("pairing must be AdvisorPairing")
        observed = self.ports.current_pairing(dict(expected.project_ref))
        if not isinstance(observed, AdvisorPairing) or not self._same_pairing(expected, observed):
            raise AdvisorDeliveryError("project advisor pairing is stale")
        return observed

    def _assignment(self, pairing: AdvisorPairing, role: str, actor: str) -> Any:
        ref = pairing.advisor_ref if role == "project_advisor" else pairing.manager_ref
        generation = pairing.advisor_generation if role == "project_advisor" else pairing.manager_generation
        validate_recipient(pairing, role=role, assignment_ref=ref, generation=generation)
        assignment = self.ports.assignments.get(ref)
        observed_ref = _field(assignment, "ref", _field(assignment, "assignment_ref"))
        if _ref(observed_ref, "assignment.ref") != dict(ref):
            raise AdvisorDeliveryError("current assignment differs from the pairing")
        observed_role = _field(assignment, "role")
        observed_generation = _field(assignment, "generation")
        if observed_role != role or observed_generation != generation:
            raise AdvisorDeliveryError("assignment role or generation is stale")
        if _principal(assignment) != _text(actor, "actor"):
            raise AdvisorDeliveryError("actor is not the paired assignment principal")
        return assignment

    def _reports(self, pairing: AdvisorPairing) -> list[dict[str, Any]]:
        values = self.ports.reports_for_project(dict(pairing.project_ref))
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise AdvisorDeliveryError("reports_for_project must return a sequence")
        result = []
        for item in values:
            if not isinstance(item, Mapping):
                continue
            value = item.get("value")
            if isinstance(value, Mapping):
                result.append({**dict(item), "value": dict(value)})
        return result

    def _append(self, assignment: Any, body: Mapping[str, Any], *, actor: str,
                generation: int, request_key: str) -> dict[str, Any]:
        observation = self.ports.assignments.append_report(
            _field(assignment, "ref", _field(assignment, "assignment_ref")),
            dict(body), expected_generation=generation,
            logical_request_key=_text(request_key, "request_key"),
            actor=self.ports.authenticate(_text(actor, "actor")),
        )
        ref = _field(observation, "ref")
        return {"ref": _ref(ref, "report_ref"), "value": dict(body)}

    def wake_once(
        self,
        *,
        pairing: AdvisorPairing,
        schedule_id: str,
        advisor_principal: str,
        lifecycle_owner: str,
        reason: str,
        request: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Claim one Due occurrence and resume only its exact advisor target.

        A replayed/in-flight claim is returned for reconciliation and never
        calls the runtime again.  An exception or unknown runtime result is
        persisted as unknown on the same occurrence, which likewise forbids a
        blind retry.
        """

        pairing = self._current(pairing)
        schedule_id = _text(schedule_id, "schedule_id")
        advisor_principal = _text(advisor_principal, "advisor_principal")
        lifecycle_owner = _text(lifecycle_owner, "lifecycle_owner")
        reason = _text(reason, "reason")
        resolved = self.ports.attention.resolve_recipient(
            schedule_id, recipient=advisor_principal, role="project_advisor",
            project_ref=pairing.project_ref["id"], manager_ref=pairing.manager_ref["id"],
            generation=pairing.advisor_generation, lifecycle_owner=lifecycle_owner,
            assignment_reader=self.ports.assignments,
        )
        if resolved.get("outcome") != "resolved":
            raise AdvisorDeliveryError(
                "advisor DueRecord recipient is not current: "
                + str((resolved.get("error") or {}).get("code", resolved.get("outcome")))
            )
        ready = self.ports.attention.check(
            schedule_id, due_reason=reason, project_ref=pairing.project_ref["id"],
            manager_ref=pairing.manager_ref["id"], generation=pairing.advisor_generation,
            lifecycle_owner=lifecycle_owner,
        )
        if ready.get("outcome") != "attention-ready" or ready.get("replayed"):
            return {"outcome": "reconcile" if ready.get("replayed") else ready.get("outcome"),
                    "wake": ready, "runtime_called": False, "retry": False}
        request_id = _text(ready.get("request_id"), "wake.request_id")
        delivery = {
            "schema": "otto.project-advisor-wake.v1",
            "role": "project_advisor",
            "project_ref": dict(pairing.project_ref),
            "assignment_ref": dict(pairing.advisor_ref),
            "generation": pairing.advisor_generation,
            "recipient": conversation_for(
                pairing, role="project_advisor", assignment_ref=pairing.advisor_ref,
                generation=pairing.advisor_generation,
            ),
            "schedule_id": schedule_id,
            "request_id": request_id,
            "reasons": list(ready.get("due_reasons", ())),
            "request": _json(dict(request or {}), "request"),
        }
        try:
            runtime = self.ports.role_delivery(delivery)
        except Exception as exc:
            completion = self.ports.attention.complete(
                schedule_id, request_id, outcome="unknown",
                completion_evidence={"kind": "otto.project-advisor-wake.v1", "error": str(exc)},
                project_ref=pairing.project_ref["id"], manager_ref=pairing.manager_ref["id"],
                generation=pairing.advisor_generation, lifecycle_owner=lifecycle_owner,
            )
            return {"outcome": "unknown", "wake": ready, "completion": completion,
                    "runtime_called": True, "retry": False}
        if not isinstance(runtime, Mapping):
            runtime = {"outcome": "unknown", "reason": "runtime result was not an object"}
        runtime = _json(dict(runtime), "runtime result")
        outcome = runtime.get("outcome")
        if outcome in {"unknown", "crashed"}:
            completion_outcome = "unknown"
        elif outcome in {"unsupported", "held", "prepared", "pending"}:
            return {"outcome": "held", "wake": ready, "runtime": runtime,
                    "runtime_called": True, "retry": False}
        else:
            completion_outcome = "returned"
        # Another DueRecord may have coalesced a coincident reason onto this
        # durable claim while the advisor was running.  Read the owner record
        # again so completion reports the full covered reason set.
        current_claim = self.ports.attention._read(schedule_id)
        covered_reasons = (list(current_claim.due_reasons) if current_claim is not None
                           else list(ready.get("due_reasons", ())))
        completion = self.ports.attention.complete(
            schedule_id, request_id, receipt=runtime, outcome=completion_outcome,
            completion_evidence={"kind": "otto.project-advisor-wake.v1", "runtime": runtime,
                                 "reasons": covered_reasons},
            project_ref=pairing.project_ref["id"], manager_ref=pairing.manager_ref["id"],
            generation=pairing.advisor_generation, lifecycle_owner=lifecycle_owner,
        )
        return {"outcome": "returned" if completion_outcome == "returned" else "unknown",
                "wake": ready, "runtime": runtime, "completion": completion,
                "runtime_called": True, "retry": False}

    @staticmethod
    def _decision_records(reports: Sequence[Mapping[str, Any]], decision_id: str) -> list[dict[str, Any]]:
        return [dict(item["value"]) for item in reports
                if isinstance(item.get("value"), Mapping)
                and item["value"].get("decision_id") == decision_id
                and str(item["value"].get("schema", "")).startswith("otto.advisor.")]

    @staticmethod
    def _latest_decision(records: Sequence[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
        """Return the latest append-only delivery intent for one decision."""

        return next((dict(item) for item in reversed(records)
                     if item.get("schema") == "otto.advisor.decision.v1"), None)

    @staticmethod
    def _delivery_projection(
        records: Sequence[Mapping[str, Any]], *, recipient: Mapping[str, Any], delivery_id: str,
    ) -> dict[str, Any]:
        """Project append-only delivery history, including later corrections."""

        projected: dict[str, Any] = {"state": "persisted", "receipt": None}
        invalid_sent_claims = 0
        for item in records:
            if item.get("delivery_id") != delivery_id:
                continue
            if item.get("schema") == "otto.advisor.delivery-correction.v1":
                projected = {"state": "unknown", "receipt": None, "correction": dict(item)}
                continue
            if item.get("schema") != "otto.advisor.delivery.v1":
                continue
            state = item.get("state")
            if state == "sent":
                receipt = _exact_consumption_receipt(
                    {"state": state, "receipt": item.get("receipt")},
                    recipient=recipient, delivery_id=delivery_id,
                )
                if receipt is None:
                    invalid_sent_claims += 1
                    projected = {"state": "unknown", "receipt": None,
                                 "invalid_sent_claim": dict(item)}
                else:
                    projected = {"state": "sent", "receipt": receipt,
                                 "sent_at": item.get("sent_at")}
            elif state in {"started", "unknown"}:
                projected = {"state": state, "receipt": None}
        projected["invalid_sent_claims"] = invalid_sent_claims
        return projected

    def deliver_decision(
        self,
        *,
        pairing: AdvisorPairing,
        advisor_actor: str,
        decision_id: str,
        action: str,
        rationale: str,
        evidence: Sequence[Any],
        expected_evidence: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Persist a decision intent, then send it to the exact current manager."""

        pairing = self._current(pairing)
        advisor = self._assignment(pairing, "project_advisor", advisor_actor)
        decision_id, request_id = _text(decision_id, "decision_id"), _text(request_id, "request_id")
        action, rationale = _text(action, "action"), _text(rationale, "rationale")
        expected_evidence = _text(expected_evidence, "expected_evidence")
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence) or not evidence:
            raise AdvisorDeliveryError("evidence must be a non-empty sequence")
        evidence_value = _json(list(evidence), "evidence")
        delivery_id = _stable("advisor-delivery", pairing.project_ref["id"], decision_id, request_id)
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        body = {
            "schema": "otto.advisor.decision.v1", "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref), "advisor_ref": dict(pairing.advisor_ref),
            "advisor_generation": pairing.advisor_generation,
            "manager_ref": dict(pairing.manager_ref), "manager_generation": pairing.manager_generation,
            "recipient": recipient, "action": action, "rationale": rationale,
            "evidence": evidence_value, "expected_evidence": expected_evidence,
            "delivery_id": delivery_id, "state": "persisted", "request_id": request_id,
        }
        records = self._decision_records(self._reports(pairing), decision_id)
        prior_intent = next((item for item in records if item.get("request_id") == request_id
                             and item.get("schema") == body["schema"]), None)
        if prior_intent is not None:
            expected = dict(body)
            if any(prior_intent.get(key) != value for key, value in expected.items()):
                raise AdvisorDeliveryError("request_id was reused with changed decision input")
            delivery_state = self._delivery_projection(
                records, recipient=recipient, delivery_id=delivery_id,
            )
            if delivery_state["state"] == "sent":
                return {"outcome": "sent", "decision_id": decision_id,
                        "delivery_id": delivery_id, "receipt": delivery_state.get("receipt"),
                        "sent_at": delivery_state.get("sent_at"), "retry": False,
                        "replayed": True}
            if delivery_state["state"] in {"started", "unknown"}:
                recovered = self.recover_delivery(
                    pairing=pairing, advisor_actor=advisor_actor, decision_id=decision_id,
                )
                return {**recovered, "replayed": True}
            report = next((item for item in self._reports(pairing)
                           if isinstance(item.get("value"), Mapping)
                           and item["value"].get("schema") == body["schema"]
                           and item["value"].get("request_id") == request_id), None)
            if report is None or not isinstance(report.get("ref"), Mapping):
                raise AdvisorDeliveryError("persisted decision report is unavailable")
        else:
            report = self._append(advisor, body, actor=advisor_actor,
                                  generation=pairing.advisor_generation, request_key=request_id)
        message = {"type": "project_advisor_decision", "decision_id": decision_id,
                   "report_ref": report["ref"], "action": action,
                   "rationale": rationale, "evidence": evidence_value,
                   "expected_evidence": expected_evidence, "recipient": recipient}
        if self.ports.delivery is None:
            return {"outcome": "prepared", "decision_id": decision_id,
                    "delivery_id": delivery_id, "report_ref": report["ref"],
                    "recipient": recipient, "message": message, "retry": False}
        started_body = {
            "schema": "otto.advisor.delivery.v1", "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref), "delivery_id": delivery_id,
            "recipient_assignment_ref": dict(pairing.manager_ref), "recipient": recipient,
            "state": "started", "receipt": None, "sent_at": None,
            "started_at": _stamp(self.ports.now()),
        }
        self._append(
            advisor, started_body, actor=advisor_actor, generation=pairing.advisor_generation,
            request_key="otto-advisor-delivery-started:" + delivery_id,
        )
        try:
            sent = self.ports.delivery.send({
                "schema": "otto.advisor.delivery.v1", "delivery_id": delivery_id,
                "project_ref": dict(pairing.project_ref), "recipient_assignment_ref": dict(pairing.manager_ref),
                "recipient": recipient, "message": message,
            })
        except Exception as exc:
            sent = {"state": "unknown", "error": str(exc)}
        if not isinstance(sent, Mapping):
            sent = {"state": "unknown"}
        receipt = _exact_consumption_receipt(
            sent, recipient=recipient, delivery_id=delivery_id,
        )
        state = "sent" if receipt is not None else (
            "started" if sent.get("state") == "started" else "unknown"
        )
        sent_at = None
        if receipt is not None:
            candidate = sent.get("sent_at") or receipt.get("observed_at")
            try:
                sent_at = _observed_stamp(candidate, "sent_at")
            except AdvisorDeliveryError:
                state, receipt = "unknown", None
        result_body = {
            "schema": "otto.advisor.delivery.v1", "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref), "delivery_id": delivery_id,
            "recipient_assignment_ref": dict(pairing.manager_ref), "recipient": recipient,
            "state": state, "receipt": receipt,
            "sent_at": sent_at,
        }
        result_report = self._append(
            advisor, result_body, actor=advisor_actor, generation=pairing.advisor_generation,
            request_key="otto-advisor-delivery-result:" + delivery_id,
        )
        return {"outcome": state, "decision_id": decision_id, "delivery_id": delivery_id,
                "report_ref": report["ref"], "delivery_report_ref": result_report["ref"],
                "receipt": result_body["receipt"], "sent_at": result_body["sent_at"],
                "retry": False}

    def recover_delivery(self, *, pairing: AdvisorPairing, advisor_actor: str,
                         decision_id: str) -> dict[str, Any]:
        """Reconcile one unknown delivery by readback; never resend it."""

        pairing = self._current(pairing)
        advisor = self._assignment(pairing, "project_advisor", advisor_actor)
        decision_id = _text(decision_id, "decision_id")
        records = self._decision_records(self._reports(pairing), decision_id)
        decision = self._latest_decision(records)
        if decision is None:
            return {"outcome": "unknown", "error": {"code": "decision_missing"}, "retry": False}
        delivery_id = decision["delivery_id"]
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        projection = self._delivery_projection(
            records, recipient=recipient, delivery_id=delivery_id,
        )
        if projection["state"] == "sent":
            return {"outcome": "sent", "delivery_id": delivery_id,
                    "receipt": projection.get("receipt"), "sent_at": projection.get("sent_at"),
                    "retry": False}
        read = getattr(self.ports.delivery, "read_delivery", None) if self.ports.delivery is not None else None
        if not callable(read):
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "transport": "unsupported", "retry": False}
        try:
            value = read(delivery_id)
        except Exception as exc:
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "error": str(exc), "retry": False}
        receipt = _exact_consumption_receipt(
            value, recipient=recipient, delivery_id=delivery_id,
        )
        if receipt is None:
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "readback": _json(value, "readback") if isinstance(value, Mapping) else None,
                    "retry": False}
        sent_at = value.get("sent_at") or receipt.get("observed_at")
        try:
            sent_at = _observed_stamp(sent_at, "sent_at")
        except AdvisorDeliveryError:
            return {"outcome": "unknown", "delivery_id": delivery_id,
                    "readback": _json(value, "readback"), "retry": False}
        body = {
            "schema": "otto.advisor.delivery.v1", "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref), "delivery_id": delivery_id,
            "recipient_assignment_ref": dict(pairing.manager_ref),
            "recipient": recipient, "state": "sent",
            "receipt": receipt, "sent_at": _text(sent_at, "sent_at"),
            "reconciled": True,
        }
        report = self._append(
            advisor, body, actor=advisor_actor, generation=pairing.advisor_generation,
            request_key="otto-advisor-delivery-recovered:" + delivery_id,
        )
        return {"outcome": "sent", "delivery_id": delivery_id, "receipt": body["receipt"],
                "sent_at": body["sent_at"], "report_ref": report["ref"],
                "reconciled": True, "retry": False}

    def schedule_effect_followup(
        self,
        *,
        pairing: AdvisorPairing,
        decision_id: str,
        advisor_principal: str,
        lifecycle_owner: str,
        profile: str,
        request_id: str,
        interval_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Schedule an independent follow-up from the known delivery time.

        ``interval_seconds`` is supplied by the adopted policy.  The default
        preserves Megado's current one-hour policy, while deterministic proof
        can use an accelerated interval without changing the delivery anchor.
        """

        pairing = self._current(pairing)
        decision_id = _text(decision_id, "decision_id")
        interval_seconds = _seconds(interval_seconds, "interval_seconds")
        records = self._decision_records(self._reports(pairing), decision_id)
        decision = self._latest_decision(records)
        if decision is None:
            raise AdvisorDeliveryError("advisor decision does not exist")
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        sent = self._delivery_projection(
            records, recipient=recipient, delivery_id=decision["delivery_id"],
        )
        if sent["state"] != "sent" or not isinstance(sent.get("sent_at"), str):
            raise AdvisorDeliveryError("effect follow-up requires known instruction delivery")
        try:
            delivered_at = datetime.fromisoformat(sent["sent_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdvisorDeliveryError("delivery time is invalid") from exc
        if delivered_at.tzinfo is None:
            raise AdvisorDeliveryError("delivery time must be timezone-aware")
        delivered_at = delivered_at.astimezone(timezone.utc)
        due_at = delivered_at + timedelta(seconds=interval_seconds)
        schedule_id = _stable("advisor-followup", pairing.project_ref["id"], decision_id)
        target = dict(pairing.advisor_conversation_ref)
        target.update({"role": "project_advisor", "principal": _text(advisor_principal, "advisor_principal"),
                       "assignment_ref": dict(pairing.advisor_ref)})
        record = DueRecord(
            schedule_id=schedule_id, recipient=advisor_principal,
            instruction="Inspect implementation evidence for advisor decision " + decision_id + ".",
            profile=_text(profile, "profile"), anchor=_stamp(delivered_at),
            due_at=_stamp(due_at), last_covered_slot=-1,
            invocation_identity=_stable(
                "advisor-followup-occurrence", schedule_id, decision["delivery_id"],
            ),
            project_ref=pairing.project_ref["id"], manager_ref=pairing.manager_ref["id"],
            assignment_ref=dict(pairing.advisor_ref), generation=pairing.advisor_generation,
            target=target, role="project_advisor", purpose="advisor-effect-followup",
            message="Check effect/adoption and suppress an unchanged nudge while useful repair is in progress.",
            lifecycle_owner=_text(lifecycle_owner, "lifecycle_owner"),
            execution_mode="continue_existing",
        )
        result = self.ports.attention.schedule(record, request_id=_text(request_id, "request_id"))
        return {"outcome": result.get("outcome"), "decision_id": decision_id,
                "delivery_id": decision["delivery_id"], "due_at": record.due_at,
                "schedule_id": schedule_id, "attention": result}

    def record_delivery_correction(
        self,
        *,
        pairing: AdvisorPairing,
        advisor_actor: str,
        decision_id: str,
        reason: str,
        evidence: Sequence[Any],
        request_id: str,
    ) -> dict[str, Any]:
        """Append a correction without rewriting a historical false sent claim."""

        pairing = self._current(pairing)
        advisor = self._assignment(pairing, "project_advisor", advisor_actor)
        decision_id = _text(decision_id, "decision_id")
        request_id = _text(request_id, "request_id")
        reason = _text(reason, "reason")
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence) or not evidence:
            raise AdvisorDeliveryError("correction evidence must be a non-empty sequence")
        records = self._decision_records(self._reports(pairing), decision_id)
        decision = self._latest_decision(records)
        if decision is None:
            raise AdvisorDeliveryError("advisor decision does not exist")
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        false_claim = next((item for item in reversed(records)
                            if item.get("schema") == "otto.advisor.delivery.v1"
                            and item.get("delivery_id") == decision["delivery_id"]
                            and item.get("state") == "sent"
                            and _exact_consumption_receipt(
                                {"state": "sent", "receipt": item.get("receipt")},
                                recipient=recipient, delivery_id=decision["delivery_id"],
                            ) is None), None)
        if false_claim is None:
            raise AdvisorDeliveryError("delivery correction requires a historical sent claim")
        body = {
            "schema": "otto.advisor.delivery-correction.v1",
            "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref),
            "delivery_id": decision["delivery_id"],
            "prior_state": "sent",
            "corrected_state": "unknown",
            "reason": reason,
            "evidence": _json(list(evidence), "evidence"),
            "observed_at": _stamp(self.ports.now()),
            "request_id": request_id,
        }
        report = self._append(
            advisor, body, actor=advisor_actor, generation=pairing.advisor_generation,
            request_key=request_id,
        )
        return {"outcome": "corrected", "decision_id": decision_id,
                "delivery_id": decision["delivery_id"], "report_ref": report["ref"],
                "retry": False}

    def schedule_baseline_cadence(
        self,
        *,
        pairing: AdvisorPairing,
        advisor_principal: str,
        lifecycle_owner: str,
        profile: str,
        request_id: str,
        anchor: Optional[datetime] = None,
        initial_offsets_seconds: Sequence[int],
        first_regular_offset_seconds: int,
        repeat_interval_seconds: int,
    ) -> dict[str, Any]:
        """Admit baseline checks as one-shots plus one anchored interval.

        The policy owns the offsets and interval.  This method only composes
        them into existing ``DueRecord`` instances, so missed slots, overlap,
        recovery and lifecycle stop behavior remain owned by ``DurableAttention``.
        """

        pairing = self._current(pairing)
        advisor_principal = _text(advisor_principal, "advisor_principal")
        lifecycle_owner = _text(lifecycle_owner, "lifecycle_owner")
        profile = _text(profile, "profile")
        request_id = _text(request_id, "request_id")
        if isinstance(initial_offsets_seconds, (str, bytes)) or not isinstance(initial_offsets_seconds, Sequence):
            raise AdvisorDeliveryError("initial_offsets_seconds must be a sequence")
        offsets = tuple(_seconds(value, "initial_offsets_seconds") for value in initial_offsets_seconds)
        if not offsets or tuple(sorted(set(offsets))) != offsets:
            raise AdvisorDeliveryError("initial_offsets_seconds must be strictly increasing")
        first_regular_offset_seconds = _seconds(first_regular_offset_seconds, "first_regular_offset_seconds")
        repeat_interval_seconds = _seconds(repeat_interval_seconds, "repeat_interval_seconds")
        if first_regular_offset_seconds <= offsets[-1]:
            raise AdvisorDeliveryError("first_regular_offset_seconds must follow initial offsets")
        baseline = anchor or self.ports.now()
        anchor_value = _stamp(baseline)
        target = dict(pairing.advisor_conversation_ref)
        target.update({"role": "project_advisor", "principal": advisor_principal,
                       "assignment_ref": dict(pairing.advisor_ref)})

        def record(
            schedule_id: str,
            *,
            record_anchor: str,
            due_at: Optional[str],
            interval: Optional[int],
            last_covered_slot: int,
            identity: str,
        ) -> DueRecord:
            return DueRecord(
                schedule_id=schedule_id, recipient=advisor_principal,
                instruction="Inspect current project work and evidence.", profile=profile,
                anchor=record_anchor, due_at=due_at, interval_seconds=interval,
                last_covered_slot=last_covered_slot, invocation_identity=identity,
                project_ref=pairing.project_ref["id"], manager_ref=pairing.manager_ref["id"],
                assignment_ref=dict(pairing.advisor_ref), generation=pairing.advisor_generation,
                target=target, role="project_advisor", purpose="advisor-baseline",
                message="Inspect current work and combine coincident baseline reasons.",
                lifecycle_owner=lifecycle_owner, execution_mode="continue_existing",
            )

        records = []
        for offset in offsets:
            schedule_id = _stable("advisor-baseline", pairing.project_ref["id"], "initial", offset)
            records.append(record(
                schedule_id,
                record_anchor=anchor_value,
                due_at=_stamp(baseline + timedelta(seconds=offset)), interval=None,
                last_covered_slot=-1,
                identity=_stable("advisor-baseline-occurrence", schedule_id),
            ))
        # The policy's recurring anchor is the second initial check.  Mark
        # that initial slot covered by the one-shot above so the interval's
        # first due slot is the policy's first regular offset (+9h in Megado).
        repeat_anchor = baseline + timedelta(seconds=offsets[-1])
        regular_slots = (first_regular_offset_seconds - offsets[-1]) // repeat_interval_seconds
        if offsets[-1] + regular_slots * repeat_interval_seconds != first_regular_offset_seconds:
            raise AdvisorDeliveryError("first_regular_offset_seconds must align with repeat_interval_seconds")
        schedule_id = _stable("advisor-baseline", pairing.project_ref["id"], "regular", first_regular_offset_seconds)
        records.append(record(
            schedule_id, record_anchor=_stamp(repeat_anchor), due_at=None,
            interval=repeat_interval_seconds, last_covered_slot=0,
            identity=_stable("advisor-baseline-occurrence", schedule_id),
        ))
        results = [self.ports.attention.schedule(
            item, request_id=f"{request_id}:{item.schedule_id}"
        ) for item in records]
        return {"outcome": "scheduled", "anchor": anchor_value,
                "schedule_ids": [item.schedule_id for item in records],
                "schedules": results}

    def record_manager_state(
        self,
        *,
        pairing: AdvisorPairing,
        manager_actor: str,
        decision_id: str,
        state: str,
        evidence: Sequence[Any],
        request_id: str,
    ) -> dict[str, Any]:
        """Persist acknowledgement, implementation, or observed effect distinctly."""

        if state not in {"acknowledged", "implemented", "effect_observed"}:
            raise AdvisorDeliveryError("state must be acknowledged, implemented, or effect_observed")
        pairing = self._current(pairing)
        manager = self._assignment(pairing, "manager", manager_actor)
        decision_id, request_id = _text(decision_id, "decision_id"), _text(request_id, "request_id")
        records = self._decision_records(self._reports(pairing), decision_id)
        decision = self._latest_decision(records)
        if decision is None:
            raise AdvisorDeliveryError("advisor decision does not exist")
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        sent = self._delivery_projection(
            records, recipient=recipient, delivery_id=decision["delivery_id"],
        )["state"] == "sent"
        observed_states = {item.get("state") for item in records
                           if item.get("schema") == "otto.advisor.manager-state.v1"}
        if not sent:
            raise AdvisorDeliveryError("manager state requires known instruction delivery")
        if state == "implemented" and "acknowledged" not in observed_states:
            raise AdvisorDeliveryError("implementation requires acknowledgement")
        if state == "effect_observed" and "implemented" not in observed_states:
            raise AdvisorDeliveryError("effect observation requires implementation evidence")
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise AdvisorDeliveryError("evidence must be a sequence")
        evidence_value = _json(list(evidence), "evidence")
        if state in {"implemented", "effect_observed"} and not evidence_value:
            raise AdvisorDeliveryError(state + " requires evidence")
        body = {
            "schema": "otto.advisor.manager-state.v1", "decision_id": decision_id,
            "project_ref": dict(pairing.project_ref), "manager_ref": dict(pairing.manager_ref),
            "manager_generation": pairing.manager_generation, "state": state,
            "evidence": evidence_value, "observed_at": _stamp(self.ports.now()),
            "request_id": request_id,
        }
        report = self._append(manager, body, actor=manager_actor,
                              generation=pairing.manager_generation, request_key=request_id)
        return {"outcome": "recorded", "decision_id": decision_id,
                "state": state, "report_ref": report["ref"]}

    def read_decision(self, *, pairing: AdvisorPairing, decision_id: str) -> dict[str, Any]:
        """Project the durable transition states without collapsing them."""

        pairing = self._current(pairing)
        decision_id = _text(decision_id, "decision_id")
        records = self._decision_records(self._reports(pairing), decision_id)
        decision = self._latest_decision(records)
        if decision is None:
            return {"outcome": "unknown", "decision_id": decision_id}
        manager_states = [item for item in records if item.get("schema") == "otto.advisor.manager-state.v1"]
        observed = {item.get("state") for item in manager_states}
        recipient = conversation_for(
            pairing, role="manager", assignment_ref=pairing.manager_ref,
            generation=pairing.manager_generation,
        )
        delivery = self._delivery_projection(
            records, recipient=recipient, delivery_id=decision["delivery_id"],
        )
        return {
            "outcome": "read", "decision_id": decision_id, "decision": decision,
            "persisted": True,
            "delivery_state": delivery["state"],
            "sent": delivery["state"] == "sent",
            "delivery_unknown": delivery["state"] == "unknown",
            "invalid_sent_claims": delivery["invalid_sent_claims"],
            "delivery_corrected": any(
                item.get("schema") == "otto.advisor.delivery-correction.v1"
                for item in records
            ),
            "acknowledged": "acknowledged" in observed,
            "implemented": "implemented" in observed,
            "effect_observed": "effect_observed" in observed,
            "reports": len(records), "read_side_effects": False,
        }


__all__ = [
    "AdvisorDeliveryError", "AdvisorDeliveryLoop", "AdvisorDeliveryPorts", "ExactSessionDelivery",
]

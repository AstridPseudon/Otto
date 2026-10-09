from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel.limits import LimitService
from herzchen.kernel.store import Store
from herzchen.adapters.host import CodexCliBinding, _select_admitted_turn, _select_invocation_turn
from otto.attention import (
    DueRecord,
    DurableAttention,
    InMemoryDueRecordPort,
    RecordingAttentionPort,
    StateConflictError,
    _DueRecordOwnerEngine,
    due_record_contribution,
)
from otto.agents.gateway import OwnerDueRecordAttemptCapture
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
from otto.portfolio import (
    AdvisorDeliveryError,
    AdvisorDeliveryLoop,
    AdvisorDeliveryPorts,
    ExactSessionDelivery,
    establish_pairing,
)


def ref(kind, ident, revision="rev-1"):
    return {"authority": "owner", "kind": kind, "id": ident, "revision": revision}


PROJECT = ref("work.project", "project-1")
MANAGER = ref("wrk.assignment", "manager-1", "rev-4")
ADVISOR = ref("wrk.assignment", "advisor-1", "rev-7")
MANAGER_CONVERSATION = {"host": "codex", "physical_session_id": "manager-session"}
ADVISOR_CONVERSATION = {"host": "codex", "physical_session_id": "advisor-session"}
NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def assignment(role, assignment_ref, principal, generation, manager):
    return {
        "ref": assignment_ref, "scope": PROJECT, "role": role,
        "principal": principal, "generation": generation,
        "status": "queued", "stored_manager": manager,
    }


class Assignments:
    def __init__(self, manager, advisor):
        self.values = {MANAGER["id"]: manager, ADVISOR["id"]: advisor}
        self.reports = []
        self.requests = {}

    def get(self, value):
        ident = value.get("id") if isinstance(value, dict) else value.id
        return self.values[ident]

    def append_report(self, assignment_ref, value, *, expected_generation,
                      logical_request_key, actor):
        prior = self.requests.get(logical_request_key)
        if prior is not None:
            return prior
        report = SimpleNamespace(
            ref=ref("wrk.report", "report-" + str(len(self.reports) + 1)),
            value=dict(value), generation=expected_generation,
        )
        self.reports.append({"ref": report.ref, "value": report.value,
                             "generation": expected_generation})
        self.requests[logical_request_key] = report
        return report


class Delivery:
    def __init__(self, state="sent"):
        self.state = state
        self.calls = []
        self.readback = None

    def send(self, value):
        self.calls.append(value)
        if self.state == "raise":
            raise RuntimeError("response lost")
        if self.state == "sent":
            return {"state": "sent", "receipt": {
                "schema": "otto.exact-session-consumption.v1",
                "delivery_id": value["delivery_id"],
                "physical_session_id": "manager-session",
                "observed_turn_id": "manager-turn-1",
                "observed_at": NOW.isoformat(),
                "transport": "owner-host-continuation",
                "consumed": True,
            }}
        return {"state": self.state}

    def read_delivery(self, delivery_id):
        return self.readback or {"state": "unknown"}


class AdvisorDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.manager = assignment("manager", MANAGER, "manager-principal", 1, "manager-principal")
        self.advisor = assignment("project_advisor", ADVISOR, "advisor-principal", 2, "manager-principal")
        self.pairing = establish_pairing(
            PROJECT, [self.manager, self.advisor],
            manager_conversation_ref=MANAGER_CONVERSATION,
            advisor_conversation_ref=ADVISOR_CONVERSATION,
        )
        self.assignments = Assignments(self.manager, self.advisor)
        self.due_port = InMemoryDueRecordPort()
        self.attention_port = RecordingAttentionPort()
        self.attention = DurableAttention(
            self.attention_port, due_port=self.due_port,
            clock=lambda: NOW, host_mode="durable-host",
        )
        self.runtime_calls = []
        self.delivery = Delivery()
        self.current = self.pairing
        self.loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=self.assignments, attention=self.attention,
            authenticate=lambda actor: actor,
            current_pairing=lambda project: self.current,
            reports_for_project=lambda project: list(self.assignments.reports),
            role_delivery=self._runtime,
            delivery=self.delivery, now=lambda: NOW,
        ))

    def _runtime(self, value):
        self.runtime_calls.append(value)
        return {"outcome": "succeeded", "physical_session_id": "advisor-session"}

    def _schedule_wake(self):
        record = DueRecord(
            schedule_id="advisor-wake", recipient="advisor-principal",
            instruction="Inspect current work once.", profile="advisor",
            anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
            invocation_identity="advisor-wake-1", project_ref=PROJECT["id"],
            manager_ref=MANAGER["id"], assignment_ref=ADVISOR, generation=2,
            target={**ADVISOR_CONVERSATION, "role": "project_advisor",
                    "principal": "advisor-principal", "assignment_ref": ADVISOR},
            role="project_advisor", purpose="one-shot", lifecycle_owner="owner-principal",
        )
        self.attention.schedule(record, request_id="schedule-advisor-wake")

    def _schedule_second_wake(self):
        record = DueRecord(
            schedule_id="advisor-followup", recipient="advisor-principal",
            instruction="Inspect the delivered decision.", profile="advisor",
            anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
            invocation_identity="advisor-followup-1", project_ref=PROJECT["id"],
            manager_ref=MANAGER["id"], assignment_ref=ADVISOR, generation=2,
            target={**ADVISOR_CONVERSATION, "role": "project_advisor",
                    "principal": "advisor-principal", "assignment_ref": ADVISOR},
            role="project_advisor", purpose="effect-followup", lifecycle_owner="owner-principal",
        )
        self.attention.schedule(record, request_id="schedule-advisor-followup")

    def test_one_shot_wakes_exact_advisor_once_and_persists_completion(self):
        self._schedule_wake()
        result = self.loop.wake_once(
            pairing=self.pairing, schedule_id="advisor-wake",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            reason="manager-question", request={"question": "What should change?"},
        )
        self.assertEqual(result["outcome"], "returned")
        self.assertEqual(len(self.runtime_calls), 1)
        self.assertEqual(self.runtime_calls[0]["recipient"], ADVISOR_CONVERSATION)
        self.assertEqual(result["completion"]["record"]["completion_state"], "succeeded")
        replay = self.loop.wake_once(
            pairing=self.pairing, schedule_id="advisor-wake",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            reason="manager-question",
        )
        self.assertEqual(len(self.runtime_calls), 1)
        self.assertFalse(replay["runtime_called"])

    def test_preprovider_runtime_error_is_unknown_not_returned(self):
        self._schedule_wake()
        loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=self.assignments, attention=self.attention,
            authenticate=lambda actor: actor,
            current_pairing=lambda project: self.current,
            reports_for_project=lambda project: list(self.assignments.reports),
            role_delivery=lambda delivery: {
                "outcome": "error",
                "error": {"code": "stale_claim", "message": "claim rejected"},
            },
            delivery=self.delivery, now=lambda: NOW,
        ))
        result = loop.wake_once(
            pairing=self.pairing, schedule_id="advisor-wake",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            reason="scheduled",
        )
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(result["completion"]["outcome"], "reconcile")
        stored = DueRecord.from_dict(self.due_port.read_due("advisor-wake"))
        self.assertEqual(stored.completion_state, "unknown")
        self.assertIsNotNone(stored.in_flight_request)

    def test_stale_pairing_is_rejected_before_runtime(self):
        self._schedule_wake()
        replacement = assignment("project_advisor", ref("wrk.assignment", "advisor-2"),
                                 "advisor-2", 3, "manager-principal")
        self.current = establish_pairing(
            PROJECT, [self.manager, replacement],
            manager_conversation_ref=MANAGER_CONVERSATION,
            advisor_conversation_ref={"host": "codex", "physical_session_id": "advisor-2-session"},
        )
        with self.assertRaisesRegex(AdvisorDeliveryError, "pairing is stale"):
            self.loop.wake_once(
                pairing=self.pairing, schedule_id="advisor-wake",
                advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
                reason="scheduled",
            )
        self.assertEqual(self.runtime_calls, [])

    def test_recipient_resolution_accepts_current_assignments_adoption_base(self):
        base = {**ADVISOR, "revision": "rev-6"}
        current = {**self.advisor, "payload": {"resource_adoption_base_ref": base}}
        assignments = SimpleNamespace(get=lambda _ref: current)
        record = DueRecord(
            schedule_id="advisor-adoption-base", recipient="advisor-principal",
            instruction="Inspect current effect.", profile="read-only",
            anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
            invocation_identity="advisor-adoption-base-v1", project_ref=PROJECT["id"],
            manager_ref="owner-principal", assignment_ref=base, generation=2,
            target={**ADVISOR_CONVERSATION, "role": "project_advisor",
                    "principal": "advisor-principal", "assignment_ref": base},
            role="project_advisor", lifecycle_owner="owner-principal",
        )
        self.attention.schedule(record, request_id="schedule-adoption-base")
        resolved = self.attention.resolve_recipient(
            record.schedule_id, recipient="advisor-principal", role="project_advisor",
            project_ref=PROJECT["id"], manager_ref="owner-principal", generation=2,
            lifecycle_owner="owner-principal", assignment_reader=assignments,
        )
        self.assertEqual(resolved["outcome"], "resolved")
        self.assertEqual(
            resolved["binding"]["canonical_assignment"]["current_assignment_ref"],
            ADVISOR,
        )

    def test_recipient_resolution_serializes_resource_ref_from_owner_assignment(self):
        base = {**ADVISOR, "revision": "rev-6"}
        current = SimpleNamespace(
            ref=ResourceRef.from_dict(ADVISOR), scope=PROJECT,
            role="project_advisor", status="queued", generation=2,
            principal="advisor-principal",
            payload={"resource_adoption_base_ref": base},
        )
        assignments = SimpleNamespace(get=lambda _ref: current)
        record = DueRecord(
            schedule_id="advisor-resource-ref", recipient="advisor-principal",
            instruction="Inspect current effect.", profile="read-only",
            anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
            invocation_identity="advisor-resource-ref-v1", project_ref=PROJECT["id"],
            manager_ref="owner-principal", assignment_ref=base, generation=2,
            target={**ADVISOR_CONVERSATION, "role": "project_advisor",
                    "principal": "advisor-principal", "assignment_ref": base},
            role="project_advisor", lifecycle_owner="owner-principal",
        )
        self.attention.schedule(record, request_id="schedule-resource-ref")
        resolved = self.attention.resolve_recipient(
            record.schedule_id, recipient="advisor-principal", role="project_advisor",
            project_ref=PROJECT["id"], manager_ref="owner-principal", generation=2,
            lifecycle_owner="owner-principal", assignment_reader=assignments,
        )
        self.assertEqual(resolved["outcome"], "resolved")
        self.assertEqual(
            resolved["binding"]["canonical_assignment"]["current_assignment_ref"],
            ADVISOR,
        )

    def test_cross_record_admission_coalesces_reasons_and_owner_cas_fences_race(self):
        self._schedule_wake()
        self._schedule_second_wake()
        first = self.attention.check("advisor-wake", due_reason="baseline")
        self.assertEqual(first["outcome"], "attention-ready")
        second = self.attention.check("advisor-followup", due_reason="effect-followup")
        self.assertEqual(second["outcome"], "coalesced")
        self.assertEqual(second["claim_schedule_id"], "advisor-wake")
        self.assertEqual(len(self.attention_port.requests), 1)
        claim = DueRecord.from_dict(self.due_port.read_due("advisor-wake"))
        covered = DueRecord.from_dict(self.due_port.read_due("advisor-followup"))
        self.assertEqual(claim.due_reasons, ("baseline", "effect-followup"))
        self.assertEqual((covered.stop_state, covered.completion_state), ("completed", "unknown"))

        # The port-level transaction fence also catches a caller that raced
        # after its preflight read and tried to install another claim directly.
        with self.assertRaisesRegex(StateConflictError, "already in flight"):
            self.due_port.save_due(
                "advisor-followup",
                {**covered.to_dict(), "stop_state": "active", "in_flight_request": "racing-claim"},
                request_id="racing-claim", expected_version=covered.version,
            )
        completed = self.attention.complete(
            "advisor-wake", first["request_id"], outcome="returned",
            completion_evidence={"reasons": list(claim.due_reasons)},
        )
        self.assertEqual(completed["covered_records"][0]["schedule_id"], "advisor-followup")
        covered = DueRecord.from_dict(self.due_port.read_due("advisor-followup"))
        self.assertEqual((covered.delivery_state, covered.completion_state),
                         ("returned", "succeeded"))

    def test_terminal_gateway_attempt_is_not_an_inflight_advisor_peer(self):
        self._schedule_wake()
        first = self.attention.check("advisor-wake", due_reason="initial")
        claimed = DueRecord.from_dict(self.due_port.read_due("advisor-wake"))
        self.due_port.save_due(
            "advisor-wake",
            {**claimed.to_dict(), "host_evidence": {"gateway_attempt": {
                "state": "result", "result": {
                    "outcome": "succeeded", "delivery_state": "done",
                    "logical_request_key": first["request_id"],
                },
            }}},
            request_id="record-terminal-gateway-attempt", expected_version=claimed.version,
        )
        self._schedule_second_wake()
        second = self.attention.check("advisor-followup", due_reason="effect-followup")
        self.assertEqual(first["outcome"], "attention-ready")
        self.assertEqual(second["outcome"], "attention-ready")
        self.assertNotIn("claim_schedule_id", second)

    def test_unknown_gateway_attempt_still_fences_an_advisor_peer(self):
        self._schedule_wake()
        self.attention.check("advisor-wake", due_reason="initial")
        claimed = DueRecord.from_dict(self.due_port.read_due("advisor-wake"))
        self.due_port.save_due(
            "advisor-wake",
            {**claimed.to_dict(), "host_evidence": {"gateway_attempt": {
                "state": "result", "result": {
                    "outcome": "unknown", "delivery_state": "unknown",
                    "logical_request_key": claimed.in_flight_request,
                },
            }}},
            request_id="record-unknown-gateway-attempt", expected_version=claimed.version,
        )
        self._schedule_second_wake()
        second = self.attention.check("advisor-followup", due_reason="effect-followup")
        self.assertEqual(second["outcome"], "coalesced")
        self.assertEqual(second["claim_schedule_id"], "advisor-wake")

    def test_recurring_prior_completion_does_not_hide_current_claim(self):
        self._schedule_wake()
        first = self.attention.check("advisor-wake", due_reason="current-slot")
        claimed = DueRecord.from_dict(self.due_port.read_due("advisor-wake"))
        self.due_port.save_due(
            "advisor-wake",
            {**claimed.to_dict(), "last_completed_request": "prior-slot-request",
             "completion_state": "succeeded"},
            request_id="record-prior-slot-completion", expected_version=claimed.version,
        )
        self._schedule_second_wake()
        second = self.attention.check("advisor-followup", due_reason="effect-followup")
        self.assertEqual(first["outcome"], "attention-ready")
        self.assertEqual(second["outcome"], "coalesced")
        self.assertEqual(second["claim_request_id"], first["request_id"])

    def test_unknown_delivery_is_not_resent_and_readback_can_reconcile(self):
        self.delivery.state = "raise"
        first = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-1", action="Remove the invented freshness gate.",
            rationale="Narrative status did not change semantic authority.",
            evidence=[{"ref": "report-1"}], expected_evidence="focused test passes",
            request_id="decision-request-1",
        )
        self.assertEqual(first["outcome"], "unknown")
        replay = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-1", action="Remove the invented freshness gate.",
            rationale="Narrative status did not change semantic authority.",
            evidence=[{"ref": "report-1"}], expected_evidence="focused test passes",
            request_id="decision-request-1",
        )
        self.assertEqual(replay["outcome"], "unknown")
        self.assertEqual(len(self.delivery.calls), 1)
        self.delivery.readback = {
            "state": "sent", "receipt": {
                "schema": "otto.exact-session-consumption.v1",
                "delivery_id": first["delivery_id"],
                "physical_session_id": "manager-session",
                "observed_turn_id": "manager-turn-recovered",
                "observed_at": NOW.isoformat(),
                "transport": "owner-host-continuation",
                "consumed": True,
            },
            "sent_at": NOW.isoformat(),
        }
        recovered = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-1", action="Remove the invented freshness gate.",
            rationale="Narrative status did not change semantic authority.",
            evidence=[{"ref": "report-1"}], expected_evidence="focused test passes",
            request_id="decision-request-1",
        )
        self.assertEqual(
            (recovered["outcome"], recovered["reconciled"], recovered["replayed"]),
            ("sent", True, True),
        )
        self.assertEqual(len(self.delivery.calls), 1)

    def test_intent_and_started_are_persisted_before_transport(self):
        observed = []

        class InspectingDelivery(Delivery):
            def send(inner, value):
                observed.extend(item["value"]["state"] for item in self.assignments.reports
                                if item["value"].get("decision_id") == "decision-order")
                return super().send(value)

        self.delivery = InspectingDelivery()
        self.loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=self.assignments, attention=self.attention,
            authenticate=lambda actor: actor,
            current_pairing=lambda project: self.current,
            reports_for_project=lambda project: list(self.assignments.reports),
            role_delivery=self._runtime, delivery=self.delivery, now=lambda: NOW,
        ))
        result = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-order", action="Use exact-session delivery.",
            rationale="It preserves the native boundary.", evidence=[{"ref": "diff-order"}],
            expected_evidence="manager turn", request_id="decision-request-order",
        )
        self.assertEqual(result["outcome"], "sent")
        self.assertEqual(observed, ["persisted", "started"])
        self.assertEqual(self.delivery.calls[0]["message"]["rationale"],
                         "It preserves the native boundary.")
        self.assertEqual(self.delivery.calls[0]["message"]["evidence"], [{"ref": "diff-order"}])

    def test_false_sent_claim_is_not_delivery_and_append_only_correction_is_visible(self):
        self.delivery.state = "false-shim"

        def false_send(value):
            self.delivery.calls.append(value)
            return {"state": "sent", "receipt": {
                "transport": "active-manager-command-response",
                "manager_session_id": "manager-session",
                "delivery_id": value["delivery_id"],
            }}

        self.delivery.send = false_send
        first = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-false", action="Repair the delivery boundary.",
            rationale="The shim does not transport.", evidence=[{"ref": "shim-source"}],
            expected_evidence="exact manager turn", request_id="decision-request-false",
        )
        self.assertEqual(first["outcome"], "unknown")

        # Preserve the historical false record exactly as observed, then add a
        # canonical correction rather than rewriting it.
        false_record = next(item["value"] for item in self.assignments.reports
                            if item["value"].get("schema") == "otto.advisor.delivery.v1"
                            and item["value"].get("state") == "unknown")
        false_record["state"] = "sent"
        false_record["receipt"] = {
            "transport": "active-manager-command-response",
            "manager_session_id": "manager-session",
            "delivery_id": first["delivery_id"],
        }
        corrected = self.loop.record_delivery_correction(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-false", reason="The historical shim performed no transport.",
            evidence=[{"ref": "controller-source"}], request_id="correct-false-delivery",
        )
        self.assertEqual(corrected["outcome"], "corrected")
        projected = self.loop.read_decision(
            pairing=self.pairing, decision_id="decision-false",
        )
        self.assertFalse(projected["sent"])
        self.assertTrue(projected["delivery_corrected"])
        self.assertEqual(projected["invalid_sent_claims"], 1)
        self.assertTrue(any(item["value"].get("state") == "sent"
                            for item in self.assignments.reports))

        # A corrected redelivery keeps the old false claim in history while
        # readback and manager-state transitions follow the latest intent.
        redelivery = Delivery(state="started")
        loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=self.assignments, attention=self.attention,
            authenticate=lambda actor: actor,
            current_pairing=lambda project: self.current,
            reports_for_project=lambda project: list(self.assignments.reports),
            role_delivery=self._runtime, delivery=redelivery, now=lambda: NOW,
        ))
        retried = loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-false", action="Repair the delivery boundary.",
            rationale="The shim does not transport.", evidence=[{"ref": "shim-source"}],
            expected_evidence="exact manager turn", request_id="decision-request-corrected",
        )
        self.assertEqual(retried["outcome"], "started")
        self.assertNotEqual(retried["delivery_id"], first["delivery_id"])
        redelivery.readback = {
            "state": "sent", "sent_at": NOW.isoformat(), "receipt": {
                "schema": "otto.exact-session-consumption.v1",
                "delivery_id": retried["delivery_id"],
                "physical_session_id": "manager-session",
                "observed_turn_id": "manager-turn-corrected",
                "observed_at": NOW.isoformat(),
                "transport": "owner-host-continuation", "consumed": True,
            },
        }
        recovered = loop.recover_delivery(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-false",
        )
        self.assertEqual(recovered["outcome"], "sent")
        final = loop.read_decision(pairing=self.pairing, decision_id="decision-false")
        self.assertEqual(final["decision"]["delivery_id"], retried["delivery_id"])
        self.assertTrue(final["sent"])
        self.assertTrue(final["delivery_corrected"])

    def test_exact_session_adapter_rejects_wrong_session_and_accepts_readback(self):
        calls = []
        readback = {}
        adapter = ExactSessionDelivery(
            continue_session=lambda request: calls.append(request) or {
                "outcome": "succeeded", "physical_session_id": "wrong-session",
                "observed_turn_id": "turn-wrong", "observed_turn_started_at": NOW.isoformat(),
            },
            read_session_delivery=lambda delivery_id: readback,
        )
        intent = {"delivery_id": "delivery-1", "recipient": MANAGER_CONVERSATION,
                  "message": {"text": "apply repair"}}
        self.assertEqual(adapter.send(intent)["state"], "unknown")
        self.assertEqual(calls[0]["physical_session_id"], "manager-session")
        readback.update({
            "completion_state": "succeeded", "delivery_state": "returned",
            "last_result": {"physical_session_id": "manager-session",
                            "observed_turn_id": "turn-recovered",
                            "observed_turn_started_at": NOW.isoformat()},
            "target": MANAGER_CONVERSATION,
        })
        recovered = adapter.read_delivery("delivery-1")
        self.assertEqual(recovered["state"], "sent")
        self.assertTrue(recovered["receipt"]["consumed"])

    def test_exact_session_adapter_accepts_native_admission_before_completion(self):
        admitted_at = "2026-10-03T14:59:58Z"
        adapter = ExactSessionDelivery(
            continue_session=lambda request: {
                "outcome": "active",
                "delivery_admission": {
                    "state": "turn_started", "native_turn_started": True,
                    "physical_session_id": "manager-session",
                    "observed_turn_id": "turn-admitted", "observed_at": admitted_at,
                },
            },
            read_session_delivery=lambda delivery_id: {},
        )
        result = adapter.send({
            "delivery_id": "delivery-admitted", "recipient": MANAGER_CONVERSATION,
            "message": {"text": "apply repair"},
        })
        self.assertEqual(result["state"], "sent")
        self.assertEqual(result["sent_at"], "2026-10-03T14:59:58+00:00")
        self.assertEqual(result["receipt"]["observed_at"], result["sent_at"])

    def test_delivery_uses_native_admission_time_instead_of_loop_clock(self):
        admitted_at = "2026-10-03T14:58:00Z"

        class AdmittedDelivery(Delivery):
            def send(inner, value):
                inner.calls.append(value)
                return {"state": "sent", "sent_at": admitted_at, "receipt": {
                    "schema": "otto.exact-session-consumption.v1",
                    "delivery_id": value["delivery_id"],
                    "physical_session_id": "manager-session",
                    "observed_turn_id": "manager-turn-admitted",
                    "observed_at": admitted_at,
                    "transport": "owner-host-continuation", "consumed": True,
                }}

        delivery = AdmittedDelivery()
        loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
            assignments=self.assignments, attention=self.attention,
            authenticate=lambda actor: actor,
            current_pairing=lambda project: self.current,
            reports_for_project=lambda project: list(self.assignments.reports),
            role_delivery=self._runtime, delivery=delivery, now=lambda: NOW,
        ))
        result = loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-native-time", action="Use the admitted turn.",
            rationale="The native receipt owns the cadence anchor.",
            evidence=[{"ref": "native-admission"}], expected_evidence="focused result",
            request_id="decision-request-native-time",
        )
        self.assertEqual(result["sent_at"], "2026-10-03T14:58:00+00:00")

    def test_crash_after_send_before_result_report_is_unknown_without_resend(self):
        original_append = self.assignments.append_report
        crashed = {"value": False}

        def append_with_crash(assignment_ref, value, **kwargs):
            if (value.get("schema") == "otto.advisor.delivery.v1"
                    and value.get("state") in {"sent", "unknown"} and not crashed["value"]):
                crashed["value"] = True
                raise RuntimeError("crash after transport returned")
            return original_append(assignment_ref, value, **kwargs)

        self.assignments.append_report = append_with_crash
        with self.assertRaisesRegex(RuntimeError, "crash after transport"):
            self.loop.deliver_decision(
                pairing=self.pairing, advisor_actor="advisor-principal",
                decision_id="decision-crash", action="Use the bounded repair.",
                rationale="It preserves the product invariant.", evidence=[{"ref": "diff-crash"}],
                expected_evidence="focused test passes", request_id="decision-request-crash",
            )
        self.assignments.append_report = original_append
        replay = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-crash", action="Use the bounded repair.",
            rationale="It preserves the product invariant.", evidence=[{"ref": "diff-crash"}],
            expected_evidence="focused test passes", request_id="decision-request-crash",
        )
        self.assertEqual(replay["outcome"], "unknown")
        self.assertEqual(len(self.delivery.calls), 1)

    def test_delivery_followup_and_effect_states_remain_distinct(self):
        sent = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-2", action="Keep the existing repair path.",
            rationale="It is useful work and the prior advice was too broad.",
            evidence=[{"ref": "diff-1"}], expected_evidence="manager reports the focused result",
            request_id="decision-request-2",
        )
        self.assertEqual(sent["outcome"], "sent")
        followup = self.loop.schedule_effect_followup(
            pairing=self.pairing, decision_id="decision-2",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            profile="advisor", request_id="followup-request-2",
        )
        self.assertEqual(followup["due_at"], "2026-10-03T16:00:00+00:00")
        self.loop.record_manager_state(
            pairing=self.pairing, manager_actor="manager-principal",
            decision_id="decision-2", state="acknowledged", evidence=[],
            request_id="ack-2",
        )
        acknowledged = self.loop.read_decision(pairing=self.pairing, decision_id="decision-2")
        self.assertTrue(acknowledged["sent"])
        self.assertTrue(acknowledged["acknowledged"])
        self.assertFalse(acknowledged["implemented"])
        with self.assertRaisesRegex(AdvisorDeliveryError, "implementation requires acknowledgement"):
            # A different decision has been persisted and sent, but not acknowledged.
            self.loop.deliver_decision(
                pairing=self.pairing, advisor_actor="advisor-principal",
                decision_id="decision-3", action="Use the existing path.",
                rationale="It already preserves current custody.", evidence=[{"ref": "diff-2"}],
                expected_evidence="focused result", request_id="decision-request-3",
            )
            self.loop.record_manager_state(
                pairing=self.pairing, manager_actor="manager-principal",
                decision_id="decision-3", state="implemented", evidence=[{"ref": "commit-2"}],
                request_id="implemented-3",
            )
        self.loop.record_manager_state(
            pairing=self.pairing, manager_actor="manager-principal",
            decision_id="decision-2", state="implemented", evidence=[{"ref": "commit-1"}],
            request_id="implemented-2",
        )
        self.loop.record_manager_state(
            pairing=self.pairing, manager_actor="manager-principal",
            decision_id="decision-2", state="effect_observed", evidence=[{"ref": "test-1"}],
            request_id="effect-2",
        )
        final = self.loop.read_decision(pairing=self.pairing, decision_id="decision-2")
        self.assertTrue(final["implemented"])
        self.assertTrue(final["effect_observed"])

    def test_followup_uses_policy_interval_from_delivery_anchor(self):
        sent = self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-accelerated", action="Use the focused repair.",
            rationale="The evidence supports the existing path.", evidence=[{"ref": "diff-accelerated"}],
            expected_evidence="focused result", request_id="decision-request-accelerated",
        )
        followup = self.loop.schedule_effect_followup(
            pairing=self.pairing, decision_id="decision-accelerated",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            profile="advisor", request_id="followup-request-accelerated",
            interval_seconds=15 * 60,
        )
        self.assertEqual(followup["due_at"], "2026-10-03T15:15:00+00:00")
        stored = DueRecord.from_dict(self.due_port.read_due(followup["schedule_id"]))
        self.assertEqual(stored.anchor, sent["sent_at"])

    def test_followup_can_persist_exact_owner_runtime_binding(self):
        self.loop.deliver_decision(
            pairing=self.pairing, advisor_actor="advisor-principal",
            decision_id="decision-runtime", action="Use the installed correction.",
            rationale="The native receipt proves delivery.", evidence=[{"ref": "receipt"}],
            expected_evidence="same advisor inspects the effect",
            request_id="decision-request-runtime",
        )
        task = ref("work.task", "task-6", "rev-2")
        mandate = ref("portfolio.document", "advisor-mandate", "rev-3")
        guide = ref("portfolio.document", "advisor-guide", "rev-4")
        allowance = ref("limit", "advisor-pilot", "rev-1")
        followup = self.loop.schedule_effect_followup(
            pairing=self.pairing, decision_id="decision-runtime",
            advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
            profile="read-only", request_id="followup-request-runtime",
            runtime_context={
                "project_ref": PROJECT, "task_ref": task,
                "assignment_ref": ADVISOR, "mandate_ref": mandate,
                "requested_model": "gpt-6-astra", "requested_reasoning": "high",
                "context_refs": [guide, mandate], "allowance_ref": allowance,
                "result_owner": "manager-principal", "timeout_seconds": 1200,
            },
        )
        stored = DueRecord.from_dict(self.due_port.read_due(followup["schedule_id"]))
        self.assertEqual(stored.manager_ref, "owner-principal")
        self.assertEqual(stored.target["project_ref"], PROJECT)
        self.assertEqual(stored.target["task_ref"], task)
        self.assertEqual(stored.target["mandate_ref"], mandate)
        self.assertEqual(stored.target["physical_session_id"], "advisor-session")
        self.assertEqual(stored.requested_model, "gpt-6-astra")
        self.assertEqual(stored.requested_reasoning, "high")
        self.assertEqual(stored.context_refs, (guide, mandate))
        self.assertEqual(stored.allowance_ref, allowance)

    def test_baseline_cadence_has_one_shots_then_six_hour_interval(self):
        cadence = self.loop.schedule_baseline_cadence(
            pairing=self.pairing, advisor_principal="advisor-principal",
            lifecycle_owner="owner-principal", profile="advisor",
            request_id="baseline-request", anchor=NOW,
            initial_offsets_seconds=(3600, 3 * 3600),
            first_regular_offset_seconds=9 * 3600,
            repeat_interval_seconds=6 * 3600,
        )
        initial, second, regular = cadence["schedule_ids"]
        self.assertEqual(
            [DueRecord.from_dict(self.due_port.read_due(item)).due_at for item in (initial, second)],
            ["2026-10-03T16:00:00+00:00", "2026-10-03T18:00:00+00:00"],
        )
        recurring = DueRecord.from_dict(self.due_port.read_due(regular))
        self.assertEqual(recurring.anchor, "2026-10-03T18:00:00+00:00")
        self.assertEqual(recurring.interval_seconds, 6 * 3600)

        for schedule_id, when in ((initial, NOW.replace(hour=16)), (second, NOW.replace(hour=18))):
            ready = self.attention.check(schedule_id, now=when)
            self.assertEqual(ready["outcome"], "attention-ready")
            self.attention.complete(schedule_id, ready["request_id"], completed_at=when)

        first_regular_at = NOW.replace(day=4, hour=0)
        first_regular = self.attention.check(regular, now=first_regular_at)
        self.assertEqual(first_regular["outcome"], "attention-ready")
        self.attention.complete(regular, first_regular["request_id"], completed_at=first_regular_at)
        second_regular_at = NOW.replace(day=4, hour=6)  # +15h, not a skipped slot
        second_regular = self.attention.check(regular, now=second_regular_at)
        self.assertEqual(second_regular["outcome"], "attention-ready")
        self.assertEqual(second_regular["missed_slots"], 0)
        self.assertNotEqual(first_regular["request_id"], second_regular["request_id"])
        self.attention.complete(regular, second_regular["request_id"], completed_at=second_regular_at)
        missed_regular = self.attention.check(regular, now=NOW.replace(day=4, hour=18))
        self.assertEqual(missed_regular["outcome"], "attention-ready")
        self.assertEqual(missed_regular["missed_slots"], 1)

        stopped = self.attention.stop(regular, request_id="withdraw-baseline")
        self.assertEqual(stopped["outcome"], "stopped")
        self.assertEqual(self.attention.check(regular, now=NOW.replace(day=4, hour=18))["outcome"], "stopped")


class OwnerAdmissionTests(unittest.TestCase):
    def test_adoption_base_claim_reconciles_before_allowance_gateway_and_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "owner.sqlite", authority="test-owner")
            store.register_domain_handler([due_record_contribution()])
            actor = AuthenticatedActor("test-owner", "owner-principal", "credential")
            engine = _DueRecordOwnerEngine(
                store.domain_handler([due_record_contribution()]), actor,
            )
            try:
                project = {**PROJECT, "authority": "test-owner"}
                manager_ref = {**MANAGER, "authority": "test-owner"}
                base_ref = {**ADVISOR, "authority": "test-owner", "revision": "rev-6"}
                current_ref = {**ADVISOR, "authority": "test-owner", "revision": "rev-7"}
                task = {**ref("work.task", "task-6", "rev-2"), "authority": "test-owner"}
                mandate = {**ref("dat.content.document", "mandate", "rev-1"),
                           "authority": "test-owner"}
                adoption_digest = "a" * 64
                store.put_identity(
                    ResourceRef.from_dict(current_ref),
                    {
                        "scope": project, "role": "project_advisor",
                        "principal": "advisor-principal", "generation": 2,
                        "status": "queued", "manager": "manager-principal",
                        "resource_adoption_base_ref": base_ref,
                        "resource_adoptions": [{"name": "advisor-policy"}],
                        "resource_adoption_digest": adoption_digest,
                        "resource_adoption_revision": 1,
                    },
                    version=1,
                )
                current_advisor = assignment(
                    "project_advisor", current_ref, "advisor-principal", 2,
                    "manager-principal",
                )
                current_advisor.update({
                    "scope": project,
                    "payload": {"resource_adoption_base_ref": base_ref},
                })
                manager = assignment(
                    "manager", manager_ref, "manager-principal", 1,
                    "manager-principal",
                )
                manager["scope"] = project
                assignments = Assignments(manager, current_advisor)
                pairing = establish_pairing(
                    project, [manager, current_advisor],
                    manager_conversation_ref=MANAGER_CONVERSATION,
                    advisor_conversation_ref=ADVISOR_CONVERSATION,
                )
                target = {
                    **ADVISOR_CONVERSATION, "project_ref": project, "task_ref": task,
                    "assignment_ref": base_ref, "mandate_ref": mandate,
                    "role": "project_advisor", "principal": "advisor-principal",
                }
                due = DueRecord(
                    schedule_id="scheduled-adoption-runtime",
                    recipient="advisor-principal",
                    instruction="Inspect the delivered effect.", profile="read-only",
                    anchor=NOW.isoformat(), due_at=NOW.isoformat(),
                    last_covered_slot=-1,
                    invocation_identity="scheduled-adoption-runtime-v1",
                    project_ref=project["id"], manager_ref="owner-principal",
                    assignment_ref=base_ref, generation=2, target=target,
                    role="project_advisor", lifecycle_owner="owner-principal",
                    execution_mode="continue_existing",
                )
                attention = DurableAttention(
                    RecordingAttentionPort(), due_port=engine,
                    clock=lambda: NOW, host_mode="awaited",
                )
                attention.schedule(due, request_id="schedule-adoption-runtime")
                limits = LimitService(store)
                pool = limits.create_pool(
                    ResourceRef("test-owner", "limit", "advisor-pilot"),
                    capacity_units=1, cumulative_allowance_units=3,
                    logical_request_key="create-advisor-pilot", actor=actor,
                )
                provider_calls = []

                def role_delivery(delivery):
                    claimed = DueRecord.from_dict(engine.read_due(due.schedule_id))
                    self.assertEqual(
                        claimed.delivery_evidence["request_id"], delivery["request_id"]
                    )
                    reconciled = engine.reconcile_assignment_resources(
                        due.schedule_id, assignment_ref=current_ref,
                        expected_version=claimed.version,
                        request_id="reconcile:" + delivery["request_id"],
                    )
                    self.assertEqual(reconciled["assignment_ref"], current_ref)
                    reservation = limits.reserve(
                        pool.ref, "advisor-slot", 1,
                        logical_request_key="reserve:" + delivery["request_id"],
                        actor=actor,
                    )
                    capture = OwnerDueRecordAttemptCapture(
                        engine, due.schedule_id, project_ref=project, task_ref=task,
                        assignment_ref=current_ref, generation=2,
                        role="project_advisor", principal="advisor-principal",
                        lifecycle_owner="owner-principal",
                        expected_target={**target, "assignment_ref": current_ref},
                    )
                    fingerprint = "fixture-fingerprint"
                    gateway_claim = capture.claim(
                        delivery["request_id"], current_ref, 2, fingerprint,
                    )
                    self.assertEqual(gateway_claim["outcome"], "claimed")
                    provider_calls.append(delivery["request_id"])
                    capture.record({
                        "logical_request_key": delivery["request_id"],
                        "request_fingerprint": fingerprint,
                        "project_ref": project, "task_ref": task,
                        "assignment_ref": current_ref, "generation": 2,
                        "outcome": "succeeded", "delivery_state": "done",
                    })
                    settled = limits.settle(
                        reservation, 1,
                        logical_request_key="settle:" + delivery["request_id"],
                        actor=actor,
                    )
                    self.assertEqual(settled.actual_units, 1)
                    return {"outcome": "succeeded", "delivery_state": "done"}

                loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
                    assignments=assignments, attention=attention,
                    authenticate=lambda value: value,
                    current_pairing=lambda _project: pairing,
                    reports_for_project=lambda _project: [],
                    role_delivery=role_delivery, now=lambda: NOW,
                ))
                result = loop.wake_once(
                    pairing=pairing, schedule_id=due.schedule_id,
                    advisor_principal="advisor-principal",
                    lifecycle_owner="owner-principal",
                    reason="scheduled-effect-followup",
                )
                self.assertEqual(result["outcome"], "returned")
                self.assertEqual(len(provider_calls), 1)
                final = engine.read_due(due.schedule_id)
                self.assertEqual(final["assignment_ref"], current_ref)
                self.assertEqual(
                    final["host_evidence"]["resource_adoption"]["digest"],
                    adoption_digest,
                )
            finally:
                store.close()

    def test_attention_claim_can_evolve_to_gateway_claim_before_provider_stub(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "owner.sqlite", authority="test-owner")
            store.register_domain_handler([due_record_contribution()])
            engine = _DueRecordOwnerEngine(
                store.domain_handler([due_record_contribution()]),
                AuthenticatedActor("test-owner", "owner-principal", "credential"),
            )
            try:
                project = {**PROJECT, "authority": "test-owner"}
                manager_ref = {**MANAGER, "authority": "test-owner"}
                advisor_ref = {**ADVISOR, "authority": "test-owner"}
                attention = DurableAttention(
                    RecordingAttentionPort(), due_port=engine,
                    clock=lambda: NOW, host_mode="awaited",
                )
                task = {**ref("work.task", "task-6", "rev-2"), "authority": "test-owner"}
                target = {
                    **ADVISOR_CONVERSATION, "project_ref": project, "task_ref": task,
                    "assignment_ref": advisor_ref,
                    "mandate_ref": {**ref("dat.content.document", "mandate", "rev-1"),
                                    "authority": "test-owner"},
                    "role": "project_advisor", "principal": "advisor-principal",
                }
                due = DueRecord(
                    schedule_id="scheduled-owner-runtime", recipient="advisor-principal",
                    instruction="Inspect the delivered effect.", profile="read-only",
                    anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
                    invocation_identity="scheduled-owner-runtime-v1",
                    project_ref=project["id"], manager_ref="owner-principal",
                    assignment_ref=advisor_ref, generation=2, target=target,
                    role="project_advisor", lifecycle_owner="owner-principal",
                    execution_mode="continue_existing",
                )
                attention.schedule(due, request_id="schedule-owner-runtime")
                manager = assignment("manager", manager_ref, "manager-principal", 1,
                                     "manager-principal")
                advisor = assignment("project_advisor", advisor_ref, "advisor-principal", 2,
                                     "manager-principal")
                manager["scope"] = project
                advisor["scope"] = project
                pairing = establish_pairing(
                    project, [manager, advisor],
                    manager_conversation_ref=MANAGER_CONVERSATION,
                    advisor_conversation_ref=ADVISOR_CONVERSATION,
                )
                assignments = Assignments(manager, advisor)
                provider_calls = []

                def role_delivery(delivery):
                    current = DueRecord.from_dict(engine.read_due(due.schedule_id))
                    capture = OwnerDueRecordAttemptCapture(
                        engine, due.schedule_id, project_ref=project, task_ref=task,
                        assignment_ref=advisor_ref, generation=2, role="project_advisor",
                        principal="advisor-principal", lifecycle_owner="owner-principal",
                        expected_target=target,
                    )
                    fingerprint = "fixture-fingerprint"
                    claim = capture.claim(
                        delivery["request_id"], advisor_ref, 2, fingerprint,
                    )
                    self.assertEqual(claim["outcome"], "claimed")
                    provider_calls.append(delivery["request_id"])
                    capture.record({
                        "logical_request_key": delivery["request_id"],
                        "request_fingerprint": fingerprint,
                        "project_ref": project, "task_ref": task,
                        "assignment_ref": advisor_ref, "generation": 2,
                        "outcome": "succeeded", "delivery_state": "done",
                    })
                    return {"outcome": "succeeded", "delivery_state": "done"}

                loop = AdvisorDeliveryLoop(AdvisorDeliveryPorts(
                    assignments=assignments, attention=attention,
                    authenticate=lambda actor: actor,
                    current_pairing=lambda project: pairing,
                    reports_for_project=lambda project: [],
                    role_delivery=role_delivery, now=lambda: NOW,
                ))
                result = loop.wake_once(
                    pairing=pairing, schedule_id=due.schedule_id,
                    advisor_principal="advisor-principal", lifecycle_owner="owner-principal",
                    reason="scheduled-effect-followup",
                )
                self.assertEqual(result["outcome"], "returned")
                self.assertEqual(len(provider_calls), 1)
            finally:
                store.close()

    def test_brief_only_invocation_remains_compatible(self):
        brief = {"schema": "fixture.owner-brief.v1", "mandate": "Current adopted mandate."}
        digest = "b" * 64
        self.assertEqual(
            HerzchenCodexAdapter.render_verified_invocation(brief, digest, {}),
            HerzchenCodexAdapter.render_verified_brief(brief, digest),
        )

    def test_gateway_claimed_turn_prompt_is_rendered_and_observed_exactly(self):
        brief = {"schema": "fixture.owner-brief.v1", "mandate": "Current adopted mandate."}
        digest = "a" * 64
        prompt = "Correct the historical claim, then queue the persisted decision."
        rendered = HerzchenCodexAdapter.render_verified_invocation(
            brief, digest, {"logical_request_key": "manager-v31", "prompt": prompt},
        )
        self.assertIn(prompt, rendered)
        self.assertIn('schema":"otto.owner-invocation-request.v1"', rendered)
        lines = [
            json.dumps({"type": "session_meta", "payload": {"session_id": "manager-session"}}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "task_started", "turn_id": "manager-turn-payload",
                "started_at": int(NOW.timestamp()),
            }}),
            json.dumps({"type": "turn_context", "payload": {
                "turn_id": "manager-turn-payload", "model": "gpt-test",
                "collaboration_mode": {"settings": {"reasoning_effort": "medium"}},
                "sandbox_policy": {"type": "workspace-write", "writable_roots": []},
                "approval_policy": "never",
            }}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "item_completed", "turn_id": "manager-turn-payload",
                "thread_id": "manager-session",
                "item": {"type": "UserMessage", "content": [{"type": "Text", "text": rendered}]},
            }}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "task_complete", "turn_id": "manager-turn-payload",
            }}),
        ]
        selected = _select_invocation_turn(
            lines, session_id="manager-session", prompt=rendered,
            boundary=0, started_at="2026-10-03T14:59:59+00:00",
        )
        self.assertEqual(selected[0], "manager-turn-payload")

    def test_manager_due_save_does_not_scan_unrelated_due_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "owner.sqlite", authority="test-owner")
            store.register_domain_handler([due_record_contribution()])
            engine = _DueRecordOwnerEngine(
                store.domain_handler([due_record_contribution()]),
                AuthenticatedActor("test-owner", "owner", "credential"),
            )
            try:
                engine.list_due = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("manager save scanned all Due history")
                )
                record = DueRecord(
                    schedule_id="manager-current", recipient="manager-principal",
                    instruction="Continue current work.", profile="workspace-write",
                    anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=0,
                    invocation_identity="manager-current", delivery_state="none",
                    project_ref=PROJECT["id"], manager_ref="owner", generation=1,
                    target={"host": "local", "native_id": "manager-session"},
                    role="manager", lifecycle_owner="owner",
                )
                saved = engine.save_due(
                    record.schedule_id, record.to_dict(),
                    request_id="create-manager-current", expected_version=0,
                )
                self.assertEqual(saved["version"], 1)
            finally:
                store.close()

    def test_resume_admission_reads_only_current_occurrence_after_large_history(self):
        prompt = "Receive the persisted advisor decision."
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "rollout.jsonl"
            with trace.open("wb") as stream:
                stream.write((json.dumps({
                    "type": "session_meta", "payload": {"session_id": "manager-session"},
                }) + "\n").encode())
                # A sparse historical body proves the total conversation size
                # is not treated as the current occurrence's evidence budget.
                stream.seek(33 * 1024 * 1024)
                stream.write(b"\n")
            binding = CodexCliBinding.__new__(CodexCliBinding)
            binding.native_trace_path = str(trace)
            binding.trusted_thread_reader = None
            binding.occurrence_deadline = None
            path, boundary, header, snapshot = binding._resume_trace_boundary("manager-session")
            with trace.open("ab") as stream:
                for event in (
                    {"type": "event_msg", "payload": {
                        "type": "task_started", "turn_id": "manager-turn-admitted",
                        "started_at": int(NOW.timestamp()),
                    }},
                    {"type": "event_msg", "payload": {
                        "type": "item_completed", "turn_id": "manager-turn-admitted",
                        "thread_id": "manager-session",
                        "item": {"type": "UserMessage", "content": [
                            {"type": "Text", "text": prompt},
                        ]},
                    }},
                ):
                    stream.write((json.dumps(event) + "\n").encode())
                stream.write(b'{"type":"partial')
            tail = binding._resume_trace_tail(path, boundary, header, snapshot)
        self.assertLess(len(tail), 2048)
        self.assertNotIn(b"partial", tail)
        self.assertEqual(json.loads(tail.splitlines()[0])["payload"]["session_id"], "manager-session")
        self.assertEqual(_select_admitted_turn(
            tail.decode().splitlines(), session_id="manager-session", prompt=prompt,
            boundary=0, started_at="2026-10-03T14:59:59+00:00",
        ), ("manager-turn-admitted", "2026-10-03T15:00:00+00:00"))

    def test_native_message_admission_is_available_before_task_completion(self):
        prompt = "Receive the persisted advisor decision."
        lines = [
            json.dumps({"type": "session_meta", "payload": {"session_id": "manager-session"}}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "task_started", "turn_id": "manager-turn-admitted",
                "started_at": int(NOW.timestamp()),
            }}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "item_completed", "turn_id": "manager-turn-admitted",
                "thread_id": "manager-session",
                "item": {"type": "UserMessage", "content": [{"type": "Text", "text": prompt}]},
            }}),
        ]
        result = _select_admitted_turn(
            lines, session_id="manager-session", prompt=prompt, boundary=1,
            started_at="2026-10-03T14:59:59+00:00",
        )
        self.assertEqual(result, (
            "manager-turn-admitted", "2026-10-03T15:00:00+00:00",
        ))

    def test_owner_capture_persists_exact_turn_admission_before_result(self):
        class OwnerPort(InMemoryDueRecordPort):
            def save_due(inner, *args, **kwargs):
                saved = super().save_due(*args, **kwargs)
                return {**saved, "mutation_receipt": {
                    "status": "committed", "replayed": False,
                }}

        due_port = OwnerPort()
        task = ref("work.task", "task-1")
        target = {
            "host": "codex", "native_id": "manager-session",
            "project_ref": PROJECT, "task_ref": task, "assignment_ref": MANAGER,
            "role": "manager", "principal": "manager-principal",
        }
        record = DueRecord(
            schedule_id="manager-delivery", recipient="manager-principal",
            instruction="Receive advisor decision.", profile="workspace-write",
            anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=0,
            invocation_identity="delivery-key", in_flight_request="delivery-key",
            delivery_state="ready", project_ref=PROJECT["id"], manager_ref="owner-principal",
            assignment_ref=MANAGER, generation=1, target=target, role="manager",
            lifecycle_owner="owner-principal", execution_mode="continue_existing",
        )
        due_port.save_due(
            record.schedule_id, record.to_dict(), request_id="create-delivery", expected_version=0,
        )
        capture = OwnerDueRecordAttemptCapture(
            due_port, record.schedule_id, project_ref=PROJECT, task_ref=task,
            assignment_ref=MANAGER, generation=1, role="manager",
            principal="manager-principal", lifecycle_owner="owner-principal",
            expected_target=target,
        )
        self.assertEqual(
            capture.claim("delivery-key", MANAGER, 1, "fingerprint")["outcome"],
            "claimed",
        )
        capture.record_thread_started("delivery-key", "manager-session", process_created=False)
        captured = capture.record_delivery_admission(
            "delivery-key", "manager-session", "manager-turn-admitted",
            "2026-10-03T15:00:00Z",
        )
        self.assertEqual(captured["state"], "claimed")
        self.assertEqual(
            captured["delivery_admission"]["observed_at"],
            "2026-10-03T15:00:00+00:00",
        )
        self.assertNotIn("result", captured)

    def test_store_owner_transaction_fences_cross_record_advisor_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "owner.sqlite", authority="test-owner")
            store.register_domain_handler([due_record_contribution()])
            engine = _DueRecordOwnerEngine(
                store.domain_handler([due_record_contribution()]),
                AuthenticatedActor("test-owner", "owner", "credential"),
            )
            try:
                def record(schedule_id):
                    local_advisor = {**ADVISOR, "authority": "test-owner"}
                    return DueRecord(
                        schedule_id=schedule_id, recipient="advisor-principal",
                        instruction="Inspect current work.", profile="advisor",
                        anchor=NOW.isoformat(), due_at=NOW.isoformat(), last_covered_slot=-1,
                        invocation_identity=schedule_id, project_ref=PROJECT["id"],
                        manager_ref=MANAGER["id"], assignment_ref=local_advisor, generation=2,
                        target={**ADVISOR_CONVERSATION, "role": "project_advisor",
                                "principal": "advisor-principal", "assignment_ref": local_advisor},
                        role="project_advisor", lifecycle_owner="owner-principal",
                    )

                for schedule_id in ("baseline", "followup"):
                    engine.save_due(
                        schedule_id, record(schedule_id).to_dict(),
                        request_id="create:" + schedule_id, expected_version=0,
                    )
                baseline = dict(engine.read_due("baseline"))
                baseline.update(in_flight_request="claim-baseline", last_covered_slot=0,
                                delivery_state="ready")
                engine.save_due(
                    "baseline", baseline, request_id="claim:baseline",
                    expected_version=baseline["version"],
                )
                # A retained claim's ordinary save must remain identity-local,
                # even when it still fences a second advisor claim.
                retained = dict(engine.read_due("baseline"))
                retained["host_state"] = "unknown"
                with patch.object(engine, "list_due", wraps=engine.list_due) as inventory:
                    engine.save_due(
                        "baseline", retained, request_id="observe:baseline",
                        expected_version=retained["version"],
                    )
                    inventory.assert_not_called()
                self.assertEqual(engine.read_due("baseline")["in_flight_request"], "claim-baseline")
                followup = dict(engine.read_due("followup"))
                followup.update(in_flight_request="claim-followup", last_covered_slot=0,
                                delivery_state="ready")
                with patch.object(engine, "list_due", wraps=engine.list_due) as inventory:
                    with self.assertRaisesRegex(StateConflictError, "already in flight"):
                        engine.save_due(
                            "followup", followup, request_id="claim:followup",
                            expected_version=followup["version"],
                        )
                    inventory.assert_called_once_with()
                self.assertIsNone(engine.read_due("followup")["in_flight_request"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

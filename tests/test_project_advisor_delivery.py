from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from herzchen.contracts import AuthenticatedActor
from herzchen.kernel.store import Store
from otto.attention import (
    DueRecord,
    DurableAttention,
    InMemoryDueRecordPort,
    RecordingAttentionPort,
    StateConflictError,
    _DueRecordOwnerEngine,
    due_record_contribution,
)
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

    def test_exact_session_adapter_rejects_wrong_session_and_accepts_readback(self):
        calls = []
        readback = {}
        adapter = ExactSessionDelivery(
            continue_session=lambda request: calls.append(request) or {
                "outcome": "succeeded", "physical_session_id": "wrong-session",
                "observed_turn_id": "turn-wrong",
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
                            "observed_turn_id": "turn-recovered"},
            "target": MANAGER_CONVERSATION,
        })
        recovered = adapter.read_delivery("delivery-1")
        self.assertEqual(recovered["state"], "sent")
        self.assertTrue(recovered["receipt"]["consumed"])

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
        missed_regular = self.attention.check(regular, now=NOW.replace(day=4, hour=12))
        self.assertEqual(missed_regular["outcome"], "attention-ready")
        self.assertEqual(missed_regular["missed_slots"], 1)

        stopped = self.attention.stop(regular, request_id="withdraw-baseline")
        self.assertEqual(stopped["outcome"], "stopped")
        self.assertEqual(self.attention.check(regular, now=NOW.replace(day=4, hour=12))["outcome"], "stopped")


class OwnerAdmissionTests(unittest.TestCase):
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
                followup = dict(engine.read_due("followup"))
                followup.update(in_flight_request="claim-followup", last_covered_slot=0,
                                delivery_state="ready")
                with self.assertRaisesRegex(StateConflictError, "already in flight"):
                    engine.save_due(
                        "followup", followup, request_id="claim:followup",
                        expected_version=followup["version"],
                    )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

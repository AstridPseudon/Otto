"""Owner issued bridge from an admitted native turn to the Herzchen effect ledger."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from herzchen.contracts import CommandEnvelope, ResourceRef, TransactionContext
from herzchen.kernel.operations import (
    OPERATION_SCHEMA_REVISION, OperationManager, OperationRequest, OperationState,
    UnknownOutcomeError, request_digest,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


class NativeEffectLedger:
    """Finite owner capability; Store stays at the trusted composition boundary."""

    def __init__(self, store: Any, actor: Any) -> None:
        self._store = store
        self._manager = OperationManager(store)
        self._actor = actor

    @staticmethod
    def key(logical_request_key: str) -> str:
        return "otto-native-effect:" + logical_request_key

    def get(self, logical_request_key: str) -> Any:
        return self._manager.get(self.key(logical_request_key))

    def begin(self, responsibility: Any, fingerprint: str) -> Any:
        """Durably claim one invoke or resume before the adapter receives it."""
        key = self.key(responsibility.logical_request_key)
        if self._manager.get(key) is not None:
            raise UnknownOutcomeError("native effect already started or settled; inspect retained custody")
        assignment = ResourceRef.from_dict(responsibility.assignment_ref)
        payload = {
            "logical_request_key": responsibility.logical_request_key,
            "operation": responsibility.operation,
            "packet_digest": responsibility.packet_digest,
            "request_fingerprint": fingerprint,
            "project_ref": responsibility.project_ref,
            "task_ref": responsibility.task_ref,
            "assignment_ref": responsibility.assignment_ref,
            "generation": responsibility.generation,
            "physical_session_id": responsibility.physical_session_id,
        }
        request = OperationRequest(
            "otto.native-turn", OPERATION_SCHEMA_REVISION,
            ResourceRef(self._actor.authority, "agent-adapter", "codex"),
            self._actor, key, request_digest(payload), payload,
            external_owner_ref=assignment,
        )
        prepared = self._manager.prepare(request)
        return self._manager.claim_start(prepared)

    def finish(self, started: Any, attempt: Mapping[str, Any]) -> Any:
        """Record transport outcome. Task acceptance is a separate owner step."""
        outcome = attempt.get("outcome")
        delivery = attempt.get("delivery_state")
        state = (OperationState.COMMITTED if outcome == "succeeded" and delivery == "done"
                 else OperationState.FAILED if outcome == "failed" and delivery == "done"
                 else OperationState.UNKNOWN)
        result = {"attempt_sha256": _digest(attempt), "transport_outcome": outcome,
                  "delivery_state": delivery, "observed_turn_id": attempt.get("observed_turn_id")}
        return self._manager.record_outcome(started, state, result)

    def settle_verified(self, logical_request_key: str, attempt: Mapping[str, Any]) -> Any:
        """Settle an unknown effect after its exact native proof was verified.

        The caller must first validate the retained native trace and owner
        custody. This method binds that validated result to a local terminal
        proof, then uses the kernel's exact proof reconciliation procedure.
        """
        held = self.get(logical_request_key)
        if held is None:
            return None  # Historical turns predate the shared ledger.
        if held.state is not OperationState.UNKNOWN:
            raise UnknownOutcomeError("native effect is not held for reconciliation")
        payload = held.request.payload
        if (payload.get("logical_request_key") != logical_request_key
                or payload.get("assignment_ref") != attempt.get("assignment_ref")
                or payload.get("generation") != attempt.get("generation")
                or payload.get("operation") != attempt.get("operation")):
            raise UnknownOutcomeError("retained native result differs from effect custody")
        outcome = attempt.get("outcome")
        if outcome not in {"succeeded", "failed"} or attempt.get("delivery_state") != "done":
            raise UnknownOutcomeError("native result has no verified terminal outcome")
        state = OperationState.COMMITTED if outcome == "succeeded" else OperationState.FAILED
        result = {"attempt_sha256": _digest(attempt), "transport_outcome": outcome,
                  "delivery_state": attempt["delivery_state"],
                  "observed_turn_id": attempt.get("observed_turn_id")}
        proof_key = "otto-native-terminal:" + logical_request_key + ":" + _digest(result)
        proof = {"effect_ref": held.effect_ref.to_dict(), "state": state.value, "result": result}
        target = ResourceRef(self._actor.authority, "effect-proof", proof_key)
        envelope = CommandEnvelope("effect.proof", OPERATION_SCHEMA_REVISION, target,
            TransactionContext(self._actor, proof_key, request_digest(proof), expected_version=0), proof)
        self._store.mutate(envelope, event_type="effect.terminal",
            result_ref=ResourceRef(target.authority, target.kind, target.id, "rev-1"),
            effects=proof, stream="effects")
        return self._manager.resolve_unknown(held, state, result, resolver=self._actor,
            evidence_key=proof_key, transition_key=proof_key + ":settle")

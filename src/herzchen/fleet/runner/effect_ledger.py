"""Durable kernel start claims for runner process invocations."""
from __future__ import annotations

from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel import OperationManager, OperationRecord, OperationRequest, OperationState
from herzchen.kernel.operations import OPERATION_SCHEMA_REVISION, UnknownOutcomeError, request_digest


class RunnerEffectLedger:
    """Bind one runner request id to one committed process-start claim."""

    def __init__(self, store: Any, actor: AuthenticatedActor) -> None:
        if not isinstance(actor, AuthenticatedActor):
            raise TypeError("runner effect ledger requires an authenticated actor")
        self._manager = OperationManager(store)
        self._actor = actor

    @staticmethod
    def key(request_id: str) -> str:
        return "herzchen-runner-effect:" + request_id

    def get(self, request_id: str) -> OperationRecord | None:
        return self._manager.get(self.key(request_id))

    @staticmethod
    def matches(record: Mapping[str, Any], effect: OperationRecord) -> bool:
        payload = effect.request.payload
        return (payload.get("request_id") == record.get("run_id")
                and payload.get("binding") == record.get("binding")
                and payload.get("argv") == record.get("argv")
                and payload.get("cwd") == record.get("cwd")
                and payload.get("commit") == record.get("commit"))

    def claim(self, record: Mapping[str, Any]) -> OperationRecord:
        request_id = record["run_id"]
        key = self.key(request_id)
        existing = self._manager.get(key)
        payload = {"request_id": request_id, "binding": record["binding"],
                   "argv": list(record["argv"]), "cwd": record["cwd"], "commit": record["commit"]}
        if existing is not None:
            if existing.request.payload != payload:
                raise UnknownOutcomeError("runner request id is bound to another command")
            if existing.state is not OperationState.PREPARED:
                raise UnknownOutcomeError("runner process start is already claimed or held")
            prepared = existing
        else:
            request = OperationRequest(
                "herzchen.runner-process", OPERATION_SCHEMA_REVISION,
                ResourceRef(self._actor.authority, "runner-adapter", "fleet-runner"),
                self._actor, key, request_digest(payload), payload,
            )
            prepared = self._manager.prepare(request)
        return self._manager.claim_start(prepared)

    def finish(self, started: OperationRecord, state: OperationState, result: Mapping[str, Any]) -> OperationRecord:
        if state not in (OperationState.COMMITTED, OperationState.FAILED, OperationState.UNKNOWN):
            raise ValueError("runner effect outcome must be terminal or unknown")
        return self._manager.record_outcome(started, state, dict(result))


__all__ = ["RunnerEffectLedger"]

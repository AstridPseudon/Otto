"""Bounded SUP-02 host bridge primitives.

The owner persists a finite :class:`HostEffect` and a supported tool host
executes exactly one ``automation_update`` operation.  This module contains
only deterministic request construction and readback comparison; it does not
open a socket, start a scheduler, or provide a private app-server client.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping, Optional


AUTOMATION_UPDATE = "automation_update"
HOST_EFFECT_SCHEMA = "otto.sup02.host-effect.v1"
_EFFECT_FIELDS = frozenset({
    "schema", "operation", "schedule_id", "request_id", "lifecycle_owner",
    "project_ref", "manager_ref", "generation", "owner_version",
    "desired_state", "configuration", "configuration_sha256", "idempotency_key",
})


class HostBridgeError(ValueError):
    """Invalid or unsafe host bridge input."""


class HostReadbackError(HostBridgeError):
    """The host response cannot prove the requested persisted settings."""


def _copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise HostBridgeError(f"{field} must contain finite JSON values") from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HostBridgeError(f"{field} must be non-blank text")
    return value.strip()


def _single_text(mapping: Mapping[str, Any], keys: tuple[str, ...], field: str, *, required: bool = True) -> Optional[str]:
    """Read aliases while rejecting an ambiguous pair of values."""

    values = [mapping[key] for key in keys if key in mapping and mapping[key] is not None]
    if not values:
        if required:
            raise HostBridgeError(f"{field} is required")
        return None
    first = _text(values[0], field)
    if any(_text(value, field) != first for value in values[1:]):
        raise HostBridgeError(f"{field} has conflicting aliases")
    return first


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    """Return the stable hash used to fence host configuration readback."""

    if not isinstance(configuration, Mapping):
        raise HostBridgeError("configuration must be an object")
    return _digest(_copy(dict(configuration), "configuration"))


@dataclass(frozen=True)
class HostEffect:
    """Finite owner-approved host operation.

    ``owner_version`` is the version read before the external effect.  A
    callback carrying an older value must be rejected by the owner.  The
    effect's idempotency key is stable for a logical operation and is never a
    reason to create another registration.
    """

    schedule_id: str
    request_id: str
    lifecycle_owner: str
    project_ref: Optional[str]
    manager_ref: Optional[str]
    generation: int
    owner_version: int
    desired_state: str
    configuration: Mapping[str, Any]
    configuration_sha256: str
    idempotency_key: str
    operation: str = AUTOMATION_UPDATE
    schema: str = HOST_EFFECT_SCHEMA

    def __post_init__(self) -> None:
        _text(self.schedule_id, "schedule_id")
        _text(self.request_id, "request_id")
        _text(self.lifecycle_owner, "lifecycle_owner")
        if self.project_ref is not None:
            _text(self.project_ref, "project_ref")
        if self.manager_ref is not None:
            _text(self.manager_ref, "manager_ref")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 1:
            raise HostBridgeError("generation must be a positive integer")
        if isinstance(self.owner_version, bool) or not isinstance(self.owner_version, int) or self.owner_version < 0:
            raise HostBridgeError("owner_version must be a non-negative integer")
        if self.desired_state not in {"active", "paused"}:
            raise HostBridgeError("desired_state must be active or paused")
        if self.operation != AUTOMATION_UPDATE:
            raise HostBridgeError("only automation_update is allowlisted")
        if self.schema != HOST_EFFECT_SCHEMA:
            raise HostBridgeError("unsupported host effect schema")
        configuration = _copy(dict(self.configuration), "configuration")
        if configuration_fingerprint(configuration) != self.configuration_sha256:
            raise HostBridgeError("configuration fingerprint is inconsistent")
        _text(self.idempotency_key, "idempotency_key")
        object.__setattr__(self, "configuration", configuration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "operation": self.operation,
            "schedule_id": self.schedule_id,
            "request_id": self.request_id,
            "lifecycle_owner": self.lifecycle_owner,
            "project_ref": self.project_ref,
            "manager_ref": self.manager_ref,
            "generation": self.generation,
            "owner_version": self.owner_version,
            "desired_state": self.desired_state,
            "configuration": _copy(self.configuration, "configuration"),
            "configuration_sha256": self.configuration_sha256,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HostEffect":
        if not isinstance(value, Mapping):
            raise HostBridgeError("host effect must be an object")
        configuration = value.get("configuration")
        if not isinstance(configuration, Mapping):
            raise HostBridgeError("host effect configuration must be an object")
        return cls(
            schedule_id=value.get("schedule_id"),
            request_id=value.get("request_id"),
            lifecycle_owner=value.get("lifecycle_owner"),
            project_ref=value.get("project_ref"),
            manager_ref=value.get("manager_ref"),
            generation=value.get("generation"),
            owner_version=value.get("owner_version"),
            desired_state=value.get("desired_state"),
            configuration=configuration,
            configuration_sha256=value.get("configuration_sha256"),
            idempotency_key=value.get("idempotency_key"),
            operation=value.get("operation", AUTOMATION_UPDATE),
            schema=value.get("schema", HOST_EFFECT_SCHEMA),
        )


def make_host_effect(
    *,
    schedule_id: str,
    request_id: str,
    lifecycle_owner: str,
    project_ref: Optional[str],
    manager_ref: Optional[str],
    generation: int,
    owner_version: int,
    desired_state: str,
    configuration: Mapping[str, Any],
) -> HostEffect:
    """Build an owner-persistable effect with a stable replay key."""

    config = _copy(dict(configuration), "configuration")
    fingerprint = configuration_fingerprint(config)
    stable = {
        "schedule_id": schedule_id,
        "request_id": request_id,
        "lifecycle_owner": lifecycle_owner,
        "project_ref": project_ref,
        "manager_ref": manager_ref,
        "generation": generation,
        "owner_version": owner_version,
        "desired_state": desired_state,
        "configuration_sha256": fingerprint,
    }
    key = "sup02-host-" + _digest(stable)
    return HostEffect(
        schedule_id=schedule_id, request_id=request_id,
        lifecycle_owner=lifecycle_owner, project_ref=project_ref,
        manager_ref=manager_ref, generation=generation,
        owner_version=owner_version, desired_state=desired_state,
        configuration=config, configuration_sha256=fingerprint,
        idempotency_key=key,
    )


def automation_update_request(effect: HostEffect) -> dict[str, Any]:
    """Produce the only host mutation request this bridge can emit.

    The host target and complete desired configuration are typed data.  A
    caller cannot replace the operation with arbitrary shell/tool text.
    """

    if not isinstance(effect, HostEffect):
        effect = HostEffect.from_dict(effect)
    target = effect.configuration.get("target")
    if not isinstance(target, Mapping):
        raise HostBridgeError("host effect configuration has no target")
    automation = effect.configuration.get("automation")
    nested_target_automation = target.get("automation")
    if automation is not None and nested_target_automation is not None and automation != nested_target_automation:
        raise HostBridgeError("configuration has conflicting automation objects")
    if automation is None:
        automation = nested_target_automation
    flat_automation = {key: effect.configuration[key] for key in ("name", "kind", "prompt", "rrule", "status", "targetThreadId", "target_thread_id", "target_thread", "notificationPolicy", "notification_policy") if key in effect.configuration}
    if automation is not None and flat_automation:
        for key, value in flat_automation.items():
            if key in automation and automation[key] != value:
                raise HostBridgeError("configuration has conflicting automation fields")
    if automation is None:
        # Accept the equivalent flat owner projection as well.  It is still
        # validated field-by-field below and cannot carry arbitrary tool args.
        automation = flat_automation
    if not isinstance(automation, Mapping):
        raise HostBridgeError("configuration.automation is required")
    automation_id = _single_text(
        {**dict(effect.configuration), **dict(target), **dict(automation)},
        ("automation_id", "automationId", "id"),
        "configuration.automation.id",
    )
    name = _single_text(automation, ("name",), "configuration.automation.name")
    kind = _single_text(automation, ("kind",), "configuration.automation.kind")
    prompt = _single_text(automation, ("prompt",), "configuration.automation.prompt")
    rrule = _single_text(automation, ("rrule",), "configuration.automation.rrule")
    status = _single_text(automation, ("status",), "configuration.automation.status")
    target_thread_id = _single_text(
        {**dict(effect.configuration), **dict(target), **dict(automation)},
        ("targetThreadId", "target_thread_id", "target_thread"),
        "configuration.automation.targetThreadId",
    )
    if any(value is None for value in (name, kind, prompt, rrule, status, target_thread_id)):
        raise HostBridgeError("configuration.automation is incomplete")
    status = status.upper()
    if status not in {"ACTIVE", "PAUSED"}:
        raise HostBridgeError("configuration.automation.status must be ACTIVE or PAUSED")
    expected_status = "ACTIVE" if effect.desired_state == "active" else "PAUSED"
    if status != expected_status:
        raise HostBridgeError("automation status does not match desired host state")
    notification_policy = _single_text(
        automation,
        ("notificationPolicy", "notification_policy"),
        "configuration.automation.notificationPolicy",
        required=False,
    )
    request = {
        "operation": AUTOMATION_UPDATE,
        "mode": "update",
        "id": automation_id,
        "name": name,
        "kind": kind,
        "prompt": prompt,
        "rrule": rrule,
        "status": status,
        "targetThreadId": target_thread_id,
    }
    if notification_policy is not None:
        request["notificationPolicy"] = notification_policy
    return request


def readback_matches(effect: HostEffect, readback: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Compare persisted settings exactly enough to settle owner state."""

    if not isinstance(readback, Mapping):
        return False, {"code": "readback_not_object", "message": "host readback is not an object"}
    if readback.get("schedule_id") not in {None, effect.schedule_id}:
        return False, {"code": "schedule_mismatch", "message": "readback schedule does not match effect"}
    observed_state = readback.get("state")
    if observed_state is None:
        observed_state = readback.get("status")
    if isinstance(observed_state, str):
        observed_state = observed_state.lower()
    if observed_state != effect.desired_state:
        return False, {"code": "state_mismatch", "message": "persisted host state does not match desired state", "observed": observed_state}
    observed_config = readback.get("configuration")
    if observed_config is not None:
        if not isinstance(observed_config, Mapping):
            return False, {"code": "configuration_mismatch", "message": "readback configuration is not an object"}
        if configuration_fingerprint(observed_config) != effect.configuration_sha256:
            return False, {"code": "configuration_mismatch", "message": "persisted host configuration differs"}
    else:
        # A narrow helper may return the complete automation settings as
        # top-level fields instead of an enclosing configuration object.
        try:
            expected_request = automation_update_request(effect)
        except HostBridgeError:
            expected_request = {}
        if expected_request and any(key in readback for key in ("id", "name", "kind", "prompt", "rrule", "targetThreadId", "notificationPolicy")):
            for key in ("id", "name", "kind", "prompt", "rrule", "status", "targetThreadId", "notificationPolicy"):
                if key in expected_request and readback.get(key) != expected_request[key]:
                    return False, {"code": "configuration_mismatch", "message": f"readback field {key!r} differs"}
        else:
            # Otherwise require every field that was part of the owner effect.
            for key, expected in effect.configuration.items():
                if key not in readback or readback.get(key) != expected:
                    return False, {"code": "configuration_mismatch", "message": f"readback field {key!r} differs"}
    return True, {"code": "exact_readback", "message": "persisted settings match the owner effect"}


class DeterministicHostExecutor:
    """Run one allowlisted effect, read it back, and acknowledge it once."""

    def __init__(
        self,
        automation_update: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        read_settings: Callable[[HostEffect, Mapping[str, Any]], Mapping[str, Any]],
        acknowledge: Callable[[HostEffect, Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        if not callable(automation_update) or not callable(read_settings) or not callable(acknowledge):
            raise TypeError("executor callbacks must be callable")
        self._automation_update = automation_update
        self._read_settings = read_settings
        self._acknowledge = acknowledge
        self._receipts: dict[str, dict[str, Any]] = {}

    def _settle_readback(self, effect: HostEffect, host_response: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
        """Read and acknowledge without another host mutation."""

        try:
            readback = _copy(self._read_settings(effect, host_response), "host readback")
        except Exception as exc:
            readback = {
                "schedule_id": effect.schedule_id,
                "state": "pending",
                "outcome": "response_lost",
                "response_lost": True,
                "error": {"code": "readback_unavailable", "message": str(exc)},
            }
        matches, comparison = readback_matches(effect, readback)
        observation = {
            **dict(readback),
            "readback_exact": matches,
            "comparison": comparison,
            "host_response": host_response,
            "response_lost": bool(readback.get("response_lost", False)),
        }
        acknowledgement = _copy(self._acknowledge(effect, observation), "owner acknowledgement")
        outcome = "reconciled" if matches else ("response_lost" if observation["response_lost"] else "readback_mismatch")
        return {"outcome": outcome, "effect": effect.to_dict(), "host_response": host_response, "readback": observation, "acknowledgement": acknowledgement, "replayed": replayed}

    def execute(self, effect: HostEffect) -> dict[str, Any]:
        if not isinstance(effect, HostEffect):
            effect = HostEffect.from_dict(effect)
        prior = self._receipts.get(effect.idempotency_key)
        if prior is not None:
            if prior["effect"] != effect.to_dict():
                raise HostBridgeError("idempotency key was reused with changed effect")
            if prior["receipt"].get("outcome") == "reconciled":
                return {**_copy(prior["receipt"], "receipt"), "replayed": True}
            # A failed or lost response is retried by persisted readback only;
            # automation_update is never replayed blindly.
            receipt = self._settle_readback(effect, prior["receipt"].get("host_response") or {}, replayed=True)
            self._receipts[effect.idempotency_key] = {"effect": effect.to_dict(), "receipt": receipt}
            return receipt

        request = automation_update_request(effect)
        try:
            host_response = _copy(self._automation_update(request), "automation_update response")
        except Exception as exc:
            observation = {
                "schedule_id": effect.schedule_id,
                "state": "pending",
                "outcome": "host_failure",
                "error": {"code": "automation_update_failed", "message": str(exc)},
                "response_lost": False,
            }
            acknowledgement = _copy(self._acknowledge(effect, observation), "owner acknowledgement")
            receipt = {"outcome": "host_failure", "effect": effect.to_dict(), "host_response": None, "readback": observation, "acknowledgement": acknowledgement, "replayed": False}
            self._receipts[effect.idempotency_key] = {"effect": effect.to_dict(), "receipt": receipt}
            return receipt

        # Always read persisted settings after the mutation.  If the tool
        # response is lost, the helper may recover the exact settings by ID;
        # it must never blindly call automation_update a second time.
        receipt = self._settle_readback(effect, host_response, replayed=False)
        self._receipts[effect.idempotency_key] = {"effect": effect.to_dict(), "receipt": receipt}
        return receipt


class SerializedAutomationUpdateAdapter:
    """Deserialize one owner effect and pass generated fields to the host.

    The root/app layer supplies ``automation_update``.  This adapter owns no
    app credentials or transport and deliberately rejects an effect envelope
    containing hand-edited app fields.  The only callback argument is the
    result of :func:`automation_update_request`.
    """

    def __init__(self, automation_update: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> None:
        if not callable(automation_update):
            raise TypeError("automation_update must be callable")
        self._automation_update = automation_update

    def execute(self, serialized_effect: Any) -> dict[str, Any]:
        if isinstance(serialized_effect, str):
            try:
                payload = json.loads(serialized_effect)
            except (TypeError, ValueError) as exc:
                raise HostBridgeError("serialized owner effect is not valid JSON") from exc
        else:
            payload = _copy(serialized_effect, "serialized owner effect")
        if not isinstance(payload, Mapping):
            raise HostBridgeError("serialized owner effect must be an object")
        unexpected = sorted(set(payload) - _EFFECT_FIELDS)
        if unexpected:
            raise HostBridgeError("serialized owner effect contains untrusted app fields: " + ", ".join(unexpected))
        effect = HostEffect.from_dict(payload)
        request = automation_update_request(effect)
        response = _copy(self._automation_update(request), "automation_update response")
        return {"effect": effect.to_dict(), "request": request, "response": response}


__all__ = [
    "AUTOMATION_UPDATE", "HOST_EFFECT_SCHEMA", "DeterministicHostExecutor", "SerializedAutomationUpdateAdapter",
    "HostBridgeError", "HostEffect", "HostReadbackError", "automation_update_request",
    "configuration_fingerprint", "make_host_effect", "readback_matches",
]

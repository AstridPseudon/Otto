"""Typed, explicit repository and release records for Otto.

This module is a record boundary, not a Git client.  It keeps repository
custody, candidate/check/decision evidence, and explicitly requested release
operations together while leaving remote writes, package publication, and
deployment to their separately authorised owners.

The ledger is deliberately an explicit in-process repository of records.  A
caller may persist and restore its JSON snapshot with :meth:`save` and
:meth:`load`; construction never creates a scheduler, queue, allowance, or
automatic release action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union


COMMANDS = (
    "repository.register",
    "candidate.select",
    "check.record",
    "decision.record",
    "merge.record",
    "promotion.record",
    "publication.record",
    "deployment.record",
)

RIGHTS = {
    "repository.register": "repository_owner",
    "candidate.select": "repository_owner",
    "check.record": "check_authority",
    "decision.record": "manager_authority",
    "merge.record": "merge_authority",
    "promotion.record": "promotion_authority",
    "publication.record": "publication_authority",
    "deployment.record": "deployment_authority",
}

_CADENCES = (1, 12)
_RUNNER_OUTCOMES = ("completed", "failed", "unknown")
_CHECK_OUTCOMES = ("pass", "fail", "unknown")
_DECISIONS = ("approve", "reject", "hold")


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ReleaseError("invalid_field", f"{name} must be non-blank text", field=name)
    return value.strip()


class ReleaseError(ValueError):
    """A typed, side-effect-free rejection from the public release boundary."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = _json(details)

    def to_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        result.update(self.details)
        return result


@dataclass(frozen=True)
class SourceSetEntry:
    """One exact, named input in a candidate source set."""

    key: str
    source_ref: str
    commit: str
    tree: str
    artifact_sha256: Optional[str] = None
    role: str = "source"

    def __post_init__(self) -> None:
        _text(self.key, "source_set.key")
        _text(self.source_ref, "source_set.source_ref")
        _text(self.commit, "source_set.commit")
        _text(self.tree, "source_set.tree")
        if self.artifact_sha256 is not None:
            _text(self.artifact_sha256, "source_set.artifact_sha256")
        _text(self.role, "source_set.role")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_ref": self.source_ref,
            "commit": self.commit,
            "tree": self.tree,
            "artifact_sha256": self.artifact_sha256,
            "role": self.role,
        }

    @classmethod
    def from_value(cls, value: Any) -> "SourceSetEntry":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ReleaseError("invalid_source_set", "source-set entries must be objects")
        return cls(
            key=_text(value.get("key"), "source_set.key"),
            source_ref=_text(value.get("source_ref"), "source_set.source_ref"),
            commit=_text(value.get("commit"), "source_set.commit"),
            tree=_text(value.get("tree"), "source_set.tree"),
            artifact_sha256=value.get("artifact_sha256"),
            role=value.get("role", "source"),
        )


@dataclass(frozen=True)
class ProcessProfile:
    """Selected process guidance; it is not a scheduler or an allowance."""

    profile_id: str
    manager_id: str
    cadence_hours: int
    selected: bool = True
    scheduler: str = "none"
    queue: bool = False
    periodic_allowance: str = "none"
    automatic_deployment: bool = False

    def __post_init__(self) -> None:
        _text(self.profile_id, "process_profile.profile_id")
        _text(self.manager_id, "process_profile.manager_id")
        if self.cadence_hours not in _CADENCES:
            raise ReleaseError("invalid_process_profile", "cadence must be hourly or 12-hour", cadence_hours=self.cadence_hours)
        if self.scheduler != "none" or self.queue or self.periodic_allowance != "none" or self.automatic_deployment:
            raise ReleaseError(
                "unsupported_process_profile",
                "profiles carry selected cadence data only; scheduler, queue, allowance and automatic deployment are disabled",
            )

    @property
    def cadence(self) -> str:
        return "hourly" if self.cadence_hours == 1 else "12-hour"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "manager_id": self.manager_id,
            "cadence_hours": self.cadence_hours,
            "cadence": self.cadence,
            "selected": self.selected,
            "scheduler": self.scheduler,
            "queue": self.queue,
            "periodic_allowance": self.periodic_allowance,
            "automatic_deployment": self.automatic_deployment,
        }

    @classmethod
    def hourly(cls, manager_id: str, profile_id: str = "otto-hourly") -> "ProcessProfile":
        return cls(profile_id, manager_id, 1)

    @classmethod
    def twelve_hour(cls, manager_id: str, profile_id: str = "otto-12-hour") -> "ProcessProfile":
        return cls(profile_id, manager_id, 12)

    @classmethod
    def from_value(cls, value: Any) -> "ProcessProfile":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ReleaseError("invalid_process_profile", "process profile must be an object")
        return cls(
            profile_id=_text(value.get("profile_id"), "process_profile.profile_id"),
            manager_id=_text(value.get("manager_id"), "process_profile.manager_id"),
            cadence_hours=value.get("cadence_hours"),
            selected=value.get("selected", True),
            scheduler=value.get("scheduler", "none"),
            queue=value.get("queue", False),
            periodic_allowance=value.get("periodic_allowance", "none"),
            automatic_deployment=value.get("automatic_deployment", False),
        )


@dataclass(frozen=True)
class CommandEnvelope:
    operation: str
    logical_key: str
    actor: str
    authority: str
    payload_digest: str
    expected_version: Optional[int] = None
    expected_head: Optional[str] = None
    expected_edit_token: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "logical_key": self.logical_key,
            "actor": self.actor,
            "authority": self.authority,
            "payload_digest": self.payload_digest,
            "expected_version": self.expected_version,
            "expected_head": self.expected_head,
            "expected_edit_token": self.expected_edit_token,
        }


@dataclass(frozen=True)
class CommandReceipt:
    receipt_id: str
    envelope: CommandEnvelope
    outcome: str
    event_ids: tuple[str, ...]
    effects: Mapping[str, Any]
    error: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "envelope": self.envelope.to_dict(),
            "outcome": self.outcome,
            "event_ids": list(self.event_ids),
            "effects": _json(self.effects),
            "error": None if self.error is None else _json(self.error),
        }


@dataclass(frozen=True)
class ReleaseEvent:
    event_id: str
    operation: str
    logical_key: str
    subject: str
    outcome: str
    payload_digest: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "operation": self.operation,
            "logical_key": self.logical_key,
            "subject": self.subject,
            "outcome": self.outcome,
            "payload_digest": self.payload_digest,
            "details": _json(self.details),
        }


@dataclass
class RepositoryRecord:
    repository_id: str
    remote_id: str
    target_id: str
    baseline_head: str
    target_head: str
    source_set: tuple[SourceSetEntry, ...]
    owner: str
    authorities: dict[str, str]
    process_profile: ProcessProfile
    version: int = 1
    edit_token: str = ""
    candidate_ref: Optional[str] = None
    decision_ref: Optional[str] = None
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    manager_decision: Optional[dict[str, Any]] = None
    merge: Optional[dict[str, Any]] = None
    promotion: dict[str, Any] = field(default_factory=lambda: {
        "status": "not_started", "owner": None, "completed_steps": [], "pending_steps": [], "unknown_steps": []
    })
    publication: dict[str, Any] = field(default_factory=lambda: {"status": "not_performed"})
    deployment: dict[str, Any] = field(default_factory=lambda: {"status": "not_performed"})
    receipt_ids: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)

    @property
    def source_set_digest(self) -> str:
        return _digest([entry.to_dict() for entry in self.source_set])

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "remote_id": self.remote_id,
            "target_id": self.target_id,
            "baseline_head": self.baseline_head,
            "target_head": self.target_head,
            "source_set": [entry.to_dict() for entry in self.source_set],
            "source_set_digest": self.source_set_digest,
            "owner": self.owner,
            "authorities": _json(self.authorities),
            "process_profile": self.process_profile.to_dict(),
            "version": self.version,
            "edit_token": self.edit_token,
            "candidate_ref": self.candidate_ref,
            "decision_ref": self.decision_ref,
            "checks": _json(self.checks),
            "manager_decision": _json(self.manager_decision),
            "merge": _json(self.merge),
            "promotion": _json(self.promotion),
            "publication": _json(self.publication),
            "deployment": _json(self.deployment),
            "receipt_ids": list(self.receipt_ids),
            "event_ids": list(self.event_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryRecord":
        return cls(
            repository_id=value["repository_id"], remote_id=value["remote_id"], target_id=value["target_id"],
            baseline_head=value["baseline_head"], target_head=value["target_head"],
            source_set=tuple(SourceSetEntry.from_value(item) for item in value["source_set"]),
            owner=value["owner"], authorities=dict(value["authorities"]),
            process_profile=ProcessProfile.from_value(value["process_profile"]), version=value["version"],
            edit_token=value["edit_token"], candidate_ref=value.get("candidate_ref"), decision_ref=value.get("decision_ref"),
            checks=dict(value.get("checks", {})), manager_decision=value.get("manager_decision"),
            merge=value.get("merge"), promotion=dict(value.get("promotion", {})),
            publication=dict(value.get("publication", {})), deployment=dict(value.get("deployment", {})),
            receipt_ids=list(value.get("receipt_ids", [])), event_ids=list(value.get("event_ids", [])),
        )


class ReleaseLedger:
    """Explicit public command boundary for repository/release records."""

    def __init__(self) -> None:
        self._repositories: dict[str, RepositoryRecord] = {}
        self._receipts: dict[str, CommandReceipt] = {}
        self._events: dict[str, ReleaseEvent] = {}
        self._next_receipt = 1
        self._next_event = 1
        self._manager_profiles: dict[str, str] = {}

    def _ids(self) -> tuple[str, str]:
        receipt_id = f"release-receipt-{self._next_receipt}"
        event_id = f"release-event-{self._next_event}"
        self._next_receipt += 1
        self._next_event += 1
        return receipt_id, event_id

    def _envelope(self, operation: str, logical_key: str, actor: str, authority: str, payload: Any, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str]) -> CommandEnvelope:
        return CommandEnvelope(operation, _text(logical_key, "logical_key"), _text(actor, "actor"), _text(authority, "authority"), _digest(payload), expected_version, expected_head, expected_edit_token)

    def _replay(self, envelope: CommandEnvelope) -> Optional[dict[str, Any]]:
        prior = self._receipts.get(envelope.logical_key)
        if prior is None:
            return None
        if prior.envelope.payload_digest == envelope.payload_digest and prior.envelope.operation == envelope.operation:
            return {"outcome": "replayed", "receipt": prior.to_dict(), "event_ids": list(prior.event_ids), "effects": _json(prior.effects)}
        return self._rejection("replay_conflict", "logical key was already used with a different command or payload", envelope=envelope, prior=prior)

    def _rejection(self, code: str, message: str, *, envelope: Optional[CommandEnvelope] = None, prior: Optional[CommandReceipt] = None, **details: Any) -> dict[str, Any]:
        error = {"code": code, "message": message}
        error.update(_json(details))
        return {"outcome": "rejected", "error": error, "event_ids": [], "receipt": None, "effects": self._zero_effects()}

    @staticmethod
    def _zero_effects() -> dict[str, Any]:
        return {"target_head_changed": False, "promotion_steps_completed": 0, "publication": False, "deployment": False}

    def _record(self, record: RepositoryRecord, envelope: CommandEnvelope, outcome: str, details: Mapping[str, Any], effects: Mapping[str, Any]) -> dict[str, Any]:
        receipt_id, event_id = self._ids()
        event = ReleaseEvent(event_id, envelope.operation, envelope.logical_key, record.repository_id, outcome, envelope.payload_digest, details)
        receipt = CommandReceipt(receipt_id, envelope, outcome, (event_id,), effects)
        self._events[event_id] = event
        self._receipts[envelope.logical_key] = receipt
        record.receipt_ids.append(receipt_id)
        record.event_ids.append(event_id)
        return {"outcome": outcome, "repository": record.to_dict(), "receipt": receipt.to_dict(), "event_ids": [event_id], "effects": _json(effects)}

    def _commit(self, record: RepositoryRecord, envelope: CommandEnvelope, outcome: str, details: Mapping[str, Any], effects: Mapping[str, Any]) -> dict[str, Any]:
        record.version += 1
        record.edit_token = _digest({"repository_id": record.repository_id, "version": record.version, "target_head": record.target_head})[:32]
        return self._record(record, envelope, outcome, details, effects)

    def _get(self, repository_id: str) -> RepositoryRecord:
        try:
            return self._repositories[_text(repository_id, "repository_id")]
        except KeyError:
            raise ReleaseError("unknown_repository", "repository identity is not registered", repository_id=repository_id)

    def _guard(self, record: RepositoryRecord, envelope: CommandEnvelope, *, expected_owner: Optional[str] = None, source_set_digest: Optional[str] = None) -> Optional[dict[str, Any]]:
        required_right = RIGHTS[envelope.operation]
        if record.authorities.get(required_right) != envelope.authority:
            return self._rejection("authority_mismatch", "command authority is not authorised for this repository", required_right=required_right)
        if expected_owner is not None and record.owner != expected_owner:
            return self._rejection("owner_mismatch", "repository custody belongs to another owner", owner=record.owner)
        if envelope.expected_version is None or envelope.expected_version != record.version:
            return self._rejection("stale_version", "expected repository version does not match", expected_version=envelope.expected_version, actual_version=record.version)
        if envelope.expected_head is None or envelope.expected_head != record.target_head:
            return self._rejection("stale_head", "expected target head does not match current target head", expected_head=envelope.expected_head, actual_head=record.target_head)
        if envelope.expected_edit_token is None or envelope.expected_edit_token != record.edit_token:
            return self._rejection("stale_edit_token", "expected edit token does not match current repository token")
        if source_set_digest is not None and source_set_digest != record.source_set_digest:
            return self._rejection("changed_source_set", "candidate source set is no longer the current exact source set", expected_source_set_digest=source_set_digest, actual_source_set_digest=record.source_set_digest)
        return None

    def register_repository(self, *, repository_id: str, remote_id: str, target_id: str, baseline_head: str, target_head: str, source_set: Iterable[Any], owner: str, process_profile: Any, authorities: Optional[Mapping[str, str]] = None, logical_key: str, actor: str, authority: Optional[str] = None) -> dict[str, Any]:
        profile = ProcessProfile.from_value(process_profile)
        entries = tuple(SourceSetEntry.from_value(item) for item in source_set)
        keys = [entry.key for entry in entries]
        if len(keys) != len(set(keys)):
            return self._rejection("duplicate_source_set_key", "source-set keys must be unique", duplicate_keys=sorted({key for key in keys if keys.count(key) > 1}))
        owner = _text(owner, "owner")
        repo_id = _text(repository_id, "repository_id")
        if repo_id in self._repositories:
            return self._rejection("duplicate_repository_identity", "repository identity is already registered", repository_id=repo_id)
        if profile.manager_id in self._manager_profiles and self._manager_profiles[profile.manager_id] != profile.profile_id:
            return self._rejection("duplicate_periodic_allowance", "manager already has one selected process profile", manager_id=profile.manager_id)
        rights = {
            "repository_owner": owner,
            "check_authority": "check-authority",
            "manager_authority": profile.manager_id,
            "merge_authority": owner,
            "promotion_authority": owner,
            "publication_authority": "publication-authority",
            "deployment_authority": "deployment-authority",
        }
        if authorities:
            rights.update({str(key): _text(value, f"authorities.{key}") for key, value in authorities.items()})
        command_authority = authority or owner
        envelope = self._envelope("repository.register", logical_key, actor, command_authority, {"repository_id": repo_id, "remote_id": remote_id, "target_id": target_id, "baseline_head": baseline_head, "target_head": target_head, "source_set": [e.to_dict() for e in entries], "owner": owner, "process_profile": profile.to_dict(), "authorities": rights}, None, None, None)
        replay = self._replay(envelope)
        if replay:
            return replay
        if command_authority != owner or actor != owner:
            return self._rejection("authority_mismatch", "repository registration requires the repository owner")
        record = RepositoryRecord(repo_id, _text(remote_id, "remote_id"), _text(target_id, "target_id"), _text(baseline_head, "baseline_head"), _text(target_head, "target_head"), entries, owner, rights, profile)
        record.edit_token = _digest({"repository_id": repo_id, "version": record.version, "target_head": record.target_head})[:32]
        self._repositories[repo_id] = record
        self._manager_profiles[profile.manager_id] = profile.profile_id
        return self._record(record, envelope, "recorded", {"command": "repository custody registered"}, self._zero_effects())

    def select_candidate(self, repository_id: str, *, candidate_ref: str, decision_ref: str, source_set: Optional[Iterable[Any]] = None, owner: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str]) -> dict[str, Any]:
        record = self._get(repository_id)
        entries = tuple(SourceSetEntry.from_value(item) for item in (record.source_set if source_set is None else source_set))
        keys = [entry.key for entry in entries]
        if len(keys) != len(set(keys)):
            return self._rejection("duplicate_source_set_key", "source-set keys must be unique", duplicate_keys=sorted({key for key in keys if keys.count(key) > 1}))
        auth = authority or owner
        payload = {"repository_id": repository_id, "candidate_ref": candidate_ref, "decision_ref": decision_ref, "source_set": [e.to_dict() for e in entries]}
        envelope = self._envelope("candidate.select", logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner)
        if guard:
            return guard
        if _text(candidate_ref, "candidate_ref") == _text(decision_ref, "decision_ref"):
            return self._rejection("candidate_decision_identity_collision", "candidate and decision references must remain distinct")
        record.source_set = entries
        record.candidate_ref = _text(candidate_ref, "candidate_ref")
        record.decision_ref = _text(decision_ref, "decision_ref")
        record.manager_decision = None
        record.checks = {}
        record.merge = None
        record.promotion = {"status": "not_started", "owner": None, "completed_steps": [], "pending_steps": [], "unknown_steps": []}
        return self._commit(record, envelope, "recorded", {"candidate_ref": record.candidate_ref, "source_set_digest": record.source_set_digest}, self._zero_effects())

    def record_required_check(self, repository_id: str, *, check_id: str, candidate_ref: str, result: str, evidence_ref: str, owner: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        record = self._get(repository_id)
        auth = authority or record.authorities["check_authority"]
        payload = {"repository_id": repository_id, "check_id": check_id, "candidate_ref": candidate_ref, "result": result, "evidence_ref": evidence_ref}
        envelope = self._envelope("check.record", logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner, source_set_digest=source_set_digest)
        if guard:
            return guard
        if record.candidate_ref != _text(candidate_ref, "candidate_ref"):
            return self._rejection("candidate_mismatch", "required check is not bound to the current candidate")
        if result not in _CHECK_OUTCOMES:
            return self._rejection("invalid_check_result", "check result must be pass, fail, or unknown")
        record.checks[_text(check_id, "check_id")] = {"candidate_ref": candidate_ref, "result": result, "evidence_ref": _text(evidence_ref, "evidence_ref"), "authority": auth}
        return self._commit(record, envelope, "recorded", {"check_id": check_id, "result": result}, self._zero_effects())

    def record_manager_decision(self, repository_id: str, *, decision_ref: str, candidate_ref: str, disposition: str, rationale: str, owner: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        record = self._get(repository_id)
        auth = authority or record.authorities["manager_authority"]
        payload = {"repository_id": repository_id, "decision_ref": decision_ref, "candidate_ref": candidate_ref, "disposition": disposition, "rationale": rationale}
        envelope = self._envelope("decision.record", logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner, source_set_digest=source_set_digest)
        if guard:
            return guard
        if record.candidate_ref != _text(candidate_ref, "candidate_ref") or record.decision_ref != _text(decision_ref, "decision_ref"):
            return self._rejection("candidate_decision_mismatch", "decision must reference the selected candidate and decision identity")
        if disposition not in _DECISIONS:
            return self._rejection("invalid_decision", "disposition must be approve, reject, or hold")
        if disposition == "approve" and (not record.checks or any(item["result"] != "pass" for item in record.checks.values())):
            return self._rejection("required_checks_incomplete", "approval requires every recorded check to pass")
        record.manager_decision = {"decision_ref": decision_ref, "candidate_ref": candidate_ref, "disposition": disposition, "rationale": _text(rationale, "rationale"), "manager": actor, "authority": auth}
        return self._commit(record, envelope, "recorded", {"decision_ref": decision_ref, "disposition": disposition}, self._zero_effects())

    def record_merge(self, repository_id: str, *, owner: str, target_head_after: str, runner_outcome: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        record = self._get(repository_id)
        auth = authority or owner
        payload = {"repository_id": repository_id, "target_head_after": target_head_after, "runner_outcome": runner_outcome}
        envelope = self._envelope("merge.record", logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner, source_set_digest=source_set_digest)
        if guard:
            return guard
        if runner_outcome not in _RUNNER_OUTCOMES:
            return self._rejection("invalid_runner_outcome", "runner outcome must be completed, failed, or unknown")
        if record.manager_decision is None or record.manager_decision.get("disposition") != "approve":
            return self._rejection("decision_required", "an approved manager decision is required before merge")
        changed = runner_outcome == "completed" and record.target_head != _text(target_head_after, "target_head_after")
        if changed:
            record.target_head = _text(target_head_after, "target_head_after")
        record.merge = {"status": runner_outcome, "target_head_after": target_head_after, "candidate_ref": record.candidate_ref, "source_set_digest": record.source_set_digest}
        effects = self._zero_effects()
        effects["target_head_changed"] = changed
        return self._commit(record, envelope, "recorded", {"merge_status": runner_outcome, "publication_status": record.publication["status"], "deployment_status": record.deployment["status"]}, effects)

    def record_promotion(self, repository_id: str, *, owner: str, steps: Sequence[str], step_outcomes: Mapping[str, str], logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        record = self._get(repository_id)
        auth = authority or owner
        payload = {"repository_id": repository_id, "steps": list(steps), "step_outcomes": dict(step_outcomes)}
        envelope = self._envelope("promotion.record", logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner, source_set_digest=source_set_digest)
        if guard:
            return guard
        normalized_steps = [_text(step, "steps") for step in steps]
        if len(normalized_steps) != len(set(normalized_steps)):
            return self._rejection("duplicate_promotion_step", "promotion step keys must be unique")
        if record.promotion.get("status") == "partial" and record.promotion.get("owner") != owner:
            return self._rejection("promotion_owner_mismatch", "partial promotion is recoverable only by its existing owner")
        if record.merge is None or record.merge.get("status") != "completed":
            return self._rejection("merge_required", "source promotion requires a completed merge observation")
        completed = list(record.promotion.get("completed_steps", []))
        pending: list[str] = []
        unknown: list[str] = []
        for step in normalized_steps:
            outcome = step_outcomes.get(step, "pending")
            if outcome == "completed":
                if step not in completed:
                    completed.append(step)
            elif outcome == "pending":
                pending.append(step)
            elif outcome == "unknown":
                unknown.append(step)
            else:
                return self._rejection("invalid_promotion_outcome", "promotion steps may be completed, pending, or unknown", step=step)
        completed_set = set(completed)
        pending = [step for step in pending if step not in completed_set]
        record.promotion = {"status": "completed" if not pending and not unknown else ("unknown" if unknown and not pending else "partial"), "owner": owner, "completed_steps": completed, "pending_steps": pending, "unknown_steps": unknown, "source_set_digest": record.source_set_digest}
        effects = self._zero_effects()
        effects["promotion_steps_completed"] = len([step for step in normalized_steps if step in completed_set])
        return self._commit(record, envelope, "recorded", {"promotion_status": record.promotion["status"], "completed_steps": completed, "pending_steps": pending, "unknown_steps": unknown, "publication_status": record.publication["status"], "deployment_status": record.deployment["status"]}, effects)

    def record_publication(self, repository_id: str, *, owner: str, runner_outcome: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        return self._record_separate_operation(repository_id, "publication.record", "publication", owner, runner_outcome, logical_key, actor, authority, expected_version, expected_head, expected_edit_token, source_set_digest)

    def record_deployment(self, repository_id: str, *, owner: str, runner_outcome: str, logical_key: str, actor: str, authority: Optional[str] = None, expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str] = None) -> dict[str, Any]:
        return self._record_separate_operation(repository_id, "deployment.record", "deployment", owner, runner_outcome, logical_key, actor, authority, expected_version, expected_head, expected_edit_token, source_set_digest)

    def _record_separate_operation(self, repository_id: str, operation: str, field_name: str, owner: str, runner_outcome: str, logical_key: str, actor: str, authority: Optional[str], expected_version: Optional[int], expected_head: Optional[str], expected_edit_token: Optional[str], source_set_digest: Optional[str]) -> dict[str, Any]:
        record = self._get(repository_id)
        auth = authority or record.authorities[RIGHTS[operation]]
        payload = {"repository_id": repository_id, "runner_outcome": runner_outcome}
        envelope = self._envelope(operation, logical_key, actor, auth, payload, expected_version, expected_head, expected_edit_token)
        replay = self._replay(envelope)
        if replay:
            return replay
        guard = self._guard(record, envelope, expected_owner=owner, source_set_digest=source_set_digest)
        if guard:
            return guard
        if runner_outcome not in _RUNNER_OUTCOMES:
            return self._rejection("invalid_runner_outcome", "runner outcome must be completed, failed, or unknown")
        record_state = {"status": runner_outcome, "candidate_ref": record.candidate_ref, "source_set_digest": record.source_set_digest}
        setattr(record, field_name, record_state)
        effects = self._zero_effects()
        effects[field_name] = runner_outcome == "completed"
        return self._commit(record, envelope, "recorded", {"operation": operation, "promotion_status": record.promotion["status"]}, effects)

    def get_repository(self, repository_id: str) -> dict[str, Any]:
        return self._get(repository_id).to_dict()

    def list_repositories(self) -> list[dict[str, Any]]:
        return [self._repositories[key].to_dict() for key in sorted(self._repositories)]

    def get_receipt(self, logical_key: str) -> Optional[dict[str, Any]]:
        receipt = self._receipts.get(logical_key)
        return None if receipt is None else receipt.to_dict()

    def list_events(self) -> list[dict[str, Any]]:
        return [self._events[key].to_dict() for key in sorted(self._events)]

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "otto.release-ledger.v1",
            "repositories": self.list_repositories(),
            "receipts": [self._receipts[key].to_dict() for key in sorted(self._receipts)],
            "events": self.list_events(),
            "manager_profiles": dict(self._manager_profiles),
            "next_receipt": self._next_receipt,
            "next_event": self._next_event,
        }

    def save(self, file_name: Union[str, Path]) -> None:
        Path(file_name).write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, file_name: Union[str, Path]) -> "ReleaseLedger":
        value = json.loads(Path(file_name).read_text(encoding="utf-8"))
        if value.get("schema") != "otto.release-ledger.v1":
            raise ReleaseError("invalid_snapshot", "unsupported release ledger snapshot")
        ledger = cls()
        ledger._repositories = {item["repository_id"]: RepositoryRecord.from_dict(item) for item in value.get("repositories", [])}
        ledger._manager_profiles = dict(value.get("manager_profiles", {}))
        ledger._next_receipt = value.get("next_receipt", 1)
        ledger._next_event = value.get("next_event", 1)
        for item in value.get("events", []):
            ledger._events[item["event_id"]] = ReleaseEvent(item["event_id"], item["operation"], item["logical_key"], item["subject"], item["outcome"], item["payload_digest"], item.get("details", {}))
        for item in value.get("receipts", []):
            env = item["envelope"]
            envelope = CommandEnvelope(env["operation"], env["logical_key"], env["actor"], env["authority"], env["payload_digest"], env.get("expected_version"), env.get("expected_head"), env.get("expected_edit_token"))
            ledger._receipts[envelope.logical_key] = CommandReceipt(item["receipt_id"], envelope, item["outcome"], tuple(item["event_ids"]), item.get("effects", {}), item.get("error"))
        return ledger


__all__ = [
    "COMMANDS", "RIGHTS", "CommandEnvelope", "CommandReceipt", "ProcessProfile", "ReleaseError",
    "ReleaseEvent", "ReleaseLedger", "RepositoryRecord", "SourceSetEntry",
]

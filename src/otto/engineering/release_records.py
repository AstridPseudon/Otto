"""OTT-05 repository responsibility over the accepted Herzchen Store.

Otto is a finite consumer of the accepted Herzchen public contracts.  This
module deliberately contains no database, ledger, receipt, event, scheduler,
or release executor.  The trusted bootstrap owns a Herzchen ``Store`` and
domain handlers; the returned consumer exposes only typed data and finite
operations.  All durable mutations therefore use Herzchen's public
``TransactionContext``, ``CommandEnvelope``, ``CommandReceipt`` and event
identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


COMMANDS = (
    "repository.register", "candidate.select", "check.record",
    "decision.record", "merge.record", "promotion.record",
    "publication.record", "deployment.record",
)
RIGHTS = {
    "repository.register": "repository_owner", "candidate.select": "repository_owner",
    "check.record": "check_authority", "decision.record": "manager_authority",
    "merge.record": "merge_authority", "promotion.record": "promotion_authority",
    "publication.record": "publication_authority", "deployment.record": "deployment_authority",
}
_CADENCES = (1, 12)
_RUNNER_OUTCOMES = ("completed", "failed", "unknown")
_CHECK_OUTCOMES = ("pass", "fail", "unknown")
_PROMOTION_OUTCOMES = ("completed", "pending", "unknown", "failed")
_PUBLICATION_OUTCOMES = ("not_performed", "performed", "unknown")
_DECISIONS = ("approve", "reject", "hold")
RELEASE_DOMAIN_ID = "otto.engineering.release"
RELEASE_SCHEMA_REVISION = "otto.engineering.release.v1"
RELEASE_OWNER = "otto"
REPOSITORY_KIND = "otto.repository"


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ReleaseError("invalid_field", f"{name} must be non-blank text", field=name)
    return value.strip()


class ReleaseError(ValueError):
    """Typed, side-effect-free boundary rejection."""

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
    """One exact, named input in a repository source set."""

    key: str
    source_ref: str
    commit: str
    tree: str
    artifact_sha256: Optional[str] = None
    role: str = "source"

    def __post_init__(self) -> None:
        for field_name, value in (("key", self.key), ("source_ref", self.source_ref), ("commit", self.commit), ("tree", self.tree), ("role", self.role)):
            _text(value, "source_set." + field_name)
        if self.artifact_sha256 is not None:
            _text(self.artifact_sha256, "source_set.artifact_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "source_ref": self.source_ref, "commit": self.commit, "tree": self.tree, "artifact_sha256": self.artifact_sha256, "role": self.role}

    @classmethod
    def from_value(cls, value: Any) -> "SourceSetEntry":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ReleaseError("invalid_source_set", "source-set entries must be objects")
        return cls(value.get("key"), value.get("source_ref"), value.get("commit"), value.get("tree"), value.get("artifact_sha256"), value.get("role", "source"))


@dataclass(frozen=True)
class ProcessProfile:
    """Selected cadence data, never a scheduler, queue, or allowance."""

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
            raise ReleaseError("invalid_process_profile", "cadence must be hourly or 12-hour")
        if self.scheduler != "none" or self.queue or self.periodic_allowance != "none" or self.automatic_deployment:
            raise ReleaseError("unsupported_process_profile", "selected profile data cannot create scheduling or automatic deployment")

    @property
    def cadence(self) -> str:
        return "hourly" if self.cadence_hours == 1 else "12-hour"

    def to_dict(self) -> dict[str, Any]:
        return {"profile_id": self.profile_id, "manager_id": self.manager_id, "cadence_hours": self.cadence_hours, "cadence": self.cadence, "selected": self.selected, "scheduler": self.scheduler, "queue": self.queue, "periodic_allowance": self.periodic_allowance, "automatic_deployment": self.automatic_deployment}

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
        return cls(value.get("profile_id"), value.get("manager_id"), value.get("cadence_hours"), value.get("selected", True), value.get("scheduler", "none"), value.get("queue", False), value.get("periodic_allowance", "none"), value.get("automatic_deployment", False))


@dataclass(frozen=True)
class RepositoryRecord:
    """Typed view of a Herzchen Store identity; receipt is Herzchen's type."""

    ref: Any
    version: int
    edit_token: Optional[str]
    payload: Mapping[str, Any]
    receipt: Any = None

    @property
    def repository_id(self) -> str:
        return str(self.payload["repository_id"])

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref.to_dict(), "version": self.version, "edit_token": self.edit_token, "payload": _json(self.payload), "receipt": None if self.receipt is None else self.receipt.to_dict()}


@dataclass(frozen=True)
class CandidateObservation:
    """Actual Herzchen candidate record plus Otto's source-set observation."""

    candidate: Any
    receipt: Any
    source_set_digest: str


class _OwnerService:
    """Trusted owner-side composition; never passed to an ordinary consumer."""

    def __init__(self, store: Any, *, authority: str, actor_id: str, credential_ref: str) -> None:
        from herzchen.contracts import AuthenticatedActor
        from herzchen.domains.work import WorkGraph
        from herzchen.domains.work.decisions import DecisionsModule

        self.store = store
        self.authority = authority
        self.actor = AuthenticatedActor(authority, actor_id, credential_ref)
        self.release_contribution = _release_contribution()
        if RELEASE_DOMAIN_ID not in {item.domain_id for item in store.registered_domains()}:
            store.register_domain_handler((self.release_contribution,))
        self.release_handler = store.domain_handler((self.release_contribution,))
        self.graph = WorkGraph(store, actor=self.actor)
        self.decisions = DecisionsModule(store, actor=self.actor)
        self._context: Optional[tuple[Any, Any, Any, Any, Any]] = None

    @classmethod
    def create(cls, database_path: Path, *, authority: str, actor_id: str, credential_ref: str) -> "_OwnerService":
        from herzchen.kernel import Store
        from herzchen.domains.work.module import register_work
        store = Store.create(str(database_path), authority=authority)
        register_work(store)
        return cls(store, authority=authority, actor_id=actor_id, credential_ref=credential_ref)

    @classmethod
    def reopen(cls, database_path: Path, *, authority: str, actor_id: str, credential_ref: str, expected_domains: Sequence[Any]) -> "_OwnerService":
        from herzchen.kernel import Store
        store = Store.open(str(database_path), authority=authority, expected_domains=tuple(expected_domains))
        return cls(store, authority=authority, actor_id=actor_id, credential_ref=credential_ref)

    def close(self) -> None:
        self.store.close()

    def context(self) -> tuple[Any, Any, Any, Any, Any]:
        if self._context is not None:
            return self._context
        project = self.graph.create_project(title="OTT-05 repository integration", logical_request_key="otto-ott05-project", actor=self.actor)
        artifact = self.graph.create_task(project, title="Otto candidate artifact", logical_request_key="otto-ott05-artifact", actor=self.actor)
        source = self.graph.create_task(project, title="Otto candidate source", logical_request_key="otto-ott05-source", actor=self.actor)
        spec = self.graph.create_task(project, title="OTT-05 source-set specification", logical_request_key="otto-ott05-spec", actor=self.actor)
        criterion = self.graph.create_criterion(project, title="C20 C21 C27 C31", logical_request_key="otto-ott05-criterion", actor=self.actor)
        self._context = (project, artifact, source, spec, criterion)
        return self._context

    def record(self, operation: str, repository: RepositoryRecord, payload: Mapping[str, Any], *, logical_key: str, actor: Any) -> Any:
        from herzchen.contracts import CommandEnvelope, ResourceRef, TransactionContext
        expected_revision, expected_version = repository.ref.revision, repository.version
        prior = self.store.get_receipt(logical_key)
        if prior is not None and prior.event_ids:
            for event in self.store.list_events(stream="otto.repository:" + repository.repository_id):
                if event.event_id == prior.event_ids[0] and event.before_refs:
                    expected_revision = event.before_refs[0].revision
                    if isinstance(expected_revision, str) and expected_revision.startswith("rev-"):
                        expected_version = int(expected_revision.removeprefix("rev-"))
                    break
        context = TransactionContext(actor, logical_key, "0" * 64, expected_revision=expected_revision, expected_version=expected_version)
        target = ResourceRef(self.authority, REPOSITORY_KIND, repository.repository_id)
        envelope = CommandEnvelope(operation, RELEASE_SCHEMA_REVISION, target, context, dict(payload))
        result_ref = ResourceRef(self.authority, REPOSITORY_KIND, repository.repository_id, "rev-" + str(repository.version + 1))
        try:
            return self.release_handler.mutate(envelope, event_type=operation + ".recorded", result_ref=result_ref, before_refs=(repository.ref,), effects={"repository_id": repository.repository_id, "operation": operation}, stream="otto.repository:" + repository.repository_id)
        except Exception as exc:
            _translate_public_error(exc)

    def read(self, repository_id: str) -> RepositoryRecord:
        from herzchen.contracts import ResourceRef
        identity = self.store.get_identity(ResourceRef(self.authority, REPOSITORY_KIND, repository_id))
        if identity is None:
            raise ReleaseError("not_found", "repository is not registered", repository_id=repository_id)
        return RepositoryRecord(identity.ref, identity.version, identity.edit_token, identity.payload)


class _LocalOperations:
    """Owner-side implementation used only behind the serialized facade."""

    def __init__(self, owner: _OwnerService) -> None:
        self._owner = owner
        self._database_path = Path(owner.store.path)
        self._expected_domains = owner.store.registered_domains()
        self._is_open = True

    @classmethod
    def bootstrap(cls, database_path: str | Path, *, authority: str = "otto", actor_id: str = "otto-owner", credential_ref: str = "otto-owner-credential") -> "_LocalOperations":
        return cls(_OwnerService.create(Path(database_path), authority=authority, actor_id=actor_id, credential_ref=credential_ref))

    def close(self) -> None:
        self._expected_domains = self._owner.store.registered_domains()
        self._owner.close()
        self._is_open = False

    def reopen(self) -> None:
        old = self._owner
        authority, actor_id, credential_ref = old.authority, old.actor.actor, old.actor.credential_ref
        if self._is_open:
            self.close()
        self._owner = _OwnerService.reopen(self._database_path, authority=authority, actor_id=actor_id, credential_ref=credential_ref, expected_domains=self._expected_domains)
        self._is_open = True

    def register_repository(self, *, repository_id: str, remote_id: str, target_id: str, baseline_head: str, target_head: str, source_set: Sequence[Any], owner: str, process_profile: ProcessProfile, logical_request_key: str, actor: Optional[str] = None) -> Any:
        source = _source_set(source_set)
        if owner != self._owner.actor.actor:
            raise ReleaseError("authority_mismatch", "repository custody belongs to its single registered owner", owner=owner)
        from herzchen.contracts import CommandEnvelope, ResourceRef, TransactionContext
        repository_id = _text(repository_id, "repository_id")
        if self._owner.store.get_identity(ResourceRef(self._owner.authority, REPOSITORY_KIND, repository_id)) is not None:
            raise ReleaseError("duplicate_repository", "repository identity is already registered", repository_id=repository_id)
        payload = _initial_payload(repository_id, remote_id, target_id, baseline_head, target_head, source, owner, ProcessProfile.from_value(process_profile))
        target = ResourceRef(self._owner.authority, REPOSITORY_KIND, repository_id)
        envelope = CommandEnvelope("otto.repository.register", RELEASE_SCHEMA_REVISION, target, TransactionContext(self._owner.actor, logical_request_key, "0" * 64, expected_version=0), payload)
        return self._owner.release_handler.mutate(envelope, event_type="otto.repository.register.recorded", result_ref=ResourceRef(self._owner.authority, REPOSITORY_KIND, repository_id, "rev-1"), effects={"repository_id": repository_id}, stream="otto.repository:" + repository_id)

    def get_repository(self, repository_id: str) -> RepositoryRecord:
        return self._owner.read(_text(repository_id, "repository_id"))

    def select_candidate(self, repository_id: str, *, source_set: Sequence[Any], owner: str, logical_request_key: str, actor: Optional[str] = None) -> CandidateObservation:
        record = self.get_repository(repository_id)
        source = _source_set(source_set)
        _guard_owner(record, owner); _guard_source_set(record, source)
        project, artifact, source_ref, spec, criterion = self._owner.context()
        try:
            candidate = self._owner.decisions.create_candidate(parent_obligation=project, artifact=artifact, source=source_ref, spec=spec, criteria=(criterion,), owner=owner, role="repository-candidate", provenance={"otto_source_set": [item.to_dict() for item in source]}, logical_request_key="candidate:" + logical_request_key, actor=self._owner.actor)
        except Exception as exc:
            _translate_public_error(exc)
        payload = dict(record.payload)
        payload.update({"candidate_ref": candidate.ref.to_dict(), "source_set": [item.to_dict() for item in source], "source_set_digest": _source_digest(source)})
        receipt = self._owner.record("otto.candidate.select", record, payload, logical_key=logical_request_key, actor=self._owner.actor)
        return CandidateObservation(candidate, receipt, payload["source_set_digest"])

    def record_required_check(self, repository_id: str, *, check_id: str, result: str, evidence_ref: str, owner: str, authority: str, logical_request_key: str, candidate_ref: Optional[Any] = None, source_set_digest: Optional[str] = None, expected_version: Optional[int] = None, expected_head: Optional[str] = None, expected_edit_token: Optional[str] = None) -> Any:
        record = self.get_repository(repository_id); _guard_expected(record, expected_version, expected_head, expected_edit_token); _guard_owner(record, owner)
        if authority != RIGHTS["check.record"]: raise ReleaseError("authority_mismatch", "required checks require the check authority", authority=authority)
        if result not in _CHECK_OUTCOMES: raise ReleaseError("invalid_check", "check result is not typed", result=result)
        _guard_source_digest(record, source_set_digest)
        candidate_value = candidate_ref or record.payload.get("candidate_ref")
        if not isinstance(candidate_value, Mapping): raise ReleaseError("missing_candidate", "a required check must reference the actual public candidate")
        try:
            candidate = self._owner.decisions.get_candidate(candidate_value)
        except Exception as exc:
            _translate_public_error(exc)
        if candidate.ref.to_dict() != dict(candidate_value): raise ReleaseError("stale_candidate", "required check candidate reference is not the current public candidate")
        payload = dict(record.payload); checks = dict(payload.get("checks", {})); check_id = _text(check_id, "check_id")
        checks[check_id] = {"result": result, "evidence_ref": _text(evidence_ref, "evidence_ref"), "authority": authority, "candidate_ref": candidate.ref.to_dict()}; payload["checks"] = checks
        return self._owner.record("otto.check.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def record_manager_decision(self, repository_id: str, *, disposition: str, rationale: str, owner: str, authority: str, logical_request_key: str, candidate_ref: Optional[Any] = None, decision_ref: Optional[Any] = None, source_set_digest: Optional[str] = None, expected_version: Optional[int] = None, expected_head: Optional[str] = None, expected_edit_token: Optional[str] = None) -> Any:
        record = self.get_repository(repository_id); _guard_expected(record, expected_version, expected_head, expected_edit_token); _guard_owner(record, owner)
        if authority != RIGHTS["decision.record"]: raise ReleaseError("authority_mismatch", "manager decisions require the manager authority", authority=authority)
        if disposition not in _DECISIONS: raise ReleaseError("invalid_decision", "decision disposition is not typed", disposition=disposition)
        candidate_value = candidate_ref or record.payload.get("candidate_ref")
        if not isinstance(candidate_value, Mapping): raise ReleaseError("missing_candidate", "a decision must reference the actual public candidate")
        try:
            candidate = self._owner.decisions.get_candidate(candidate_value)
            project, _artifact, _source, _spec, criterion = self._owner.context()
            decision = self._owner.decisions.record_decision(project, candidate=candidate, criterion=criterion, authority=authority, author=authority, rationale=rationale, disposition=disposition, logical_request_key="decision:" + logical_request_key, actor=self._owner.actor)
        except Exception as exc:
            _translate_public_error(exc)
        _guard_source_digest(record, source_set_digest)
        payload = dict(record.payload); payload["decision_ref"] = decision.ref.to_dict(); payload["manager_decision"] = {"disposition": disposition, "rationale": _text(rationale, "rationale"), "authority": authority, "candidate_ref": candidate.ref.to_dict()}
        return self._owner.record("otto.decision.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def record_merge(self, repository_id: str, *, target_head_after: str, runner_outcome: str, owner: str, logical_request_key: str, expected_version: Optional[int] = None, expected_head: Optional[str] = None, expected_edit_token: Optional[str] = None) -> Any:
        record = self.get_repository(repository_id); _guard_expected(record, expected_version, expected_head, expected_edit_token); _guard_owner(record, owner)
        if runner_outcome not in _RUNNER_OUTCOMES: raise ReleaseError("unknown_runner_outcome", "runner outcome must be completed, failed, or unknown")
        payload = dict(record.payload); payload["merge"] = {"status": runner_outcome, "target_head_after": _text(target_head_after, "target_head_after"), "owner": owner}
        if runner_outcome == "completed": payload["target_head"] = _text(target_head_after, "target_head_after")
        return self._owner.record("otto.merge.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def record_promotion(self, repository_id: str, *, steps: Sequence[str], step_outcomes: Mapping[str, str], owner: str, logical_request_key: str, source_set_digest: Optional[str] = None, expected_version: Optional[int] = None, expected_head: Optional[str] = None, expected_edit_token: Optional[str] = None) -> Any:
        record = self.get_repository(repository_id); _guard_expected(record, expected_version, expected_head, expected_edit_token); _guard_owner(record, owner); _guard_source_digest(record, source_set_digest)
        prior = dict(record.payload.get("promotion", {})); groups = [list(prior.get(name + "_steps", [])) for name in ("completed", "pending", "unknown")]
        for step in steps:
            step = _text(step, "promotion.step"); outcome = step_outcomes.get(step)
            if outcome not in _PROMOTION_OUTCOMES: raise ReleaseError("unknown_runner_outcome", "promotion step outcome is not typed", step=step)
            for group in groups:
                while step in group: group.remove(step)
            groups[0 if outcome == "completed" else 2 if outcome == "unknown" else 1].append(step)
        completed, pending, unknown = [sorted(set(group)) for group in groups]
        state = "completed" if not pending and not unknown else ("unknown" if unknown else "partial")
        payload = dict(record.payload); payload["promotion"] = {"status": state, "owner": owner, "completed_steps": completed, "pending_steps": pending, "unknown_steps": unknown, "source_set_digest": payload["source_set_digest"]}
        return self._owner.record("otto.promotion.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def record_publication(self, repository_id: str, *, status: str, authority: str, logical_request_key: str) -> Any:
        if status not in _PUBLICATION_OUTCOMES: raise ReleaseError("invalid_publication", "publication status is not typed")
        record = self.get_repository(repository_id)
        if authority != RIGHTS["publication.record"]: raise ReleaseError("authority_mismatch", "publication authority is separate")
        payload = dict(record.payload); payload["publication"] = {"status": status, "authority": authority}
        return self._owner.record("otto.publication.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def record_deployment(self, repository_id: str, *, status: str, authority: str, logical_request_key: str) -> Any:
        if status not in _PUBLICATION_OUTCOMES: raise ReleaseError("invalid_deployment", "deployment status is not typed")
        record = self.get_repository(repository_id)
        if authority != RIGHTS["deployment.record"]: raise ReleaseError("authority_mismatch", "deployment authority is separate")
        payload = dict(record.payload); payload["deployment"] = {"status": status, "authority": authority}
        return self._owner.record("otto.deployment.record", record, payload, logical_key=logical_request_key, actor=self._owner.actor)

    def get_candidate(self, candidate_ref: Any) -> Any:
        return self._owner.decisions.get_candidate(candidate_ref)

    def get_decision(self, decision_ref: Any) -> Any:
        return self._owner.decisions.get_decision(decision_ref)

    def get_receipt(self, logical_request_key: str) -> Any:
        return self._owner.store.get_receipt(logical_request_key)

    def list_events(self, repository_id: str) -> tuple[Any, ...]:
        return self._owner.store.consumer().list_events(stream="otto.repository:" + repository_id)

    def snapshot_counts(self) -> Mapping[str, int]:
        return self._owner.store.consumer().snapshot_counts()

    @property
    def registered_domains(self) -> tuple[str, ...]:
        return tuple(item.domain_id for item in self._owner.store.consumer().registered_domains())


class _ReleaseEngine:
    """Trusted engine retained by Herzchen's owner-side command service."""

    def __init__(self, store: Any, *, authority: str = "otto", actor_id: str = "otto-owner", credential_ref: str = "otto-owner-credential") -> None:
        self._local = _LocalOperations(_OwnerService(store, authority=authority, actor_id=actor_id, credential_ref=credential_ref))
        self.reader = self._local._owner.store.consumer()
        self._database_path = Path(store.path)
        self._expected_domains = store.registered_domains()

    def _wire(self, action: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            result = action(*args, **kwargs)
        except ReleaseError as error:
            return {"$otto_error": error.to_dict()}
        if isinstance(result, RepositoryRecord):
            return {"$otto_result": "repository", "value": result.to_dict()}
        if isinstance(result, CandidateObservation):
            return {"$otto_result": "candidate", "candidate": result.candidate, "receipt": result.receipt, "source_set_digest": result.source_set_digest}
        return result

    def close_store(self) -> bool:
        self._local._owner.close()
        return True

    def reopen_store(self) -> bool:
        self._local._owner.close()
        self._local._owner = _OwnerService.reopen(self._database_path, authority=self._local._owner.authority, actor_id=self._local._owner.actor.actor, credential_ref=self._local._owner.actor.credential_ref, expected_domains=self._expected_domains)
        self._local._is_open = True
        self.reader = self._local._owner.store.consumer()
        return True

    def register_repository(self, **kwargs: Any) -> Any:
        return self._wire(self._local.register_repository, **kwargs)

    def get_repository(self, repository_id: str) -> Any:
        return self._wire(self._local.get_repository, repository_id)

    def select_candidate(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.select_candidate, repository_id, **kwargs)

    def record_required_check(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_required_check, repository_id, **kwargs)

    def record_manager_decision(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_manager_decision, repository_id, **kwargs)

    def record_merge(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_merge, repository_id, **kwargs)

    def record_promotion(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_promotion, repository_id, **kwargs)

    def record_publication(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_publication, repository_id, **kwargs)

    def record_deployment(self, repository_id: str, **kwargs: Any) -> Any:
        return self._wire(self._local.record_deployment, repository_id, **kwargs)

    def get_candidate(self, candidate_ref: Any) -> Any:
        return self._wire(self._local.get_candidate, candidate_ref)

    def get_decision(self, decision_ref: Any) -> Any:
        return self._wire(self._local.get_decision, decision_ref)

    def get_receipt(self, logical_request_key: str) -> Any:
        return self._wire(self._local.get_receipt, logical_request_key)

    def list_events(self, repository_id: str) -> Any:
        return self._wire(self._local.list_events, repository_id)

    def snapshot_counts(self) -> Any:
        return self._wire(self._local.snapshot_counts)

    @property
    def registered_domains(self) -> tuple[str, ...]:
        return self._local.registered_domains


from herzchen.command_ports import command_facade

_ReleaseCommandFacade = command_facade(_ReleaseEngine, RELEASE_DOMAIN_ID)


def _decode_consumer(value: Any) -> Any:
    if isinstance(value, Mapping) and value.get("$otto_error") is not None:
        detail = value["$otto_error"]
        raise ReleaseError(detail.get("code", "remote_error"), detail.get("message", "remote release error"), **{key: item for key, item in detail.items() if key not in {"code", "message"}})
    if isinstance(value, Mapping) and value.get("$otto_result") == "repository":
        item = value["value"]
        from herzchen.contracts import ResourceRef
        return RepositoryRecord(ResourceRef.from_dict(item["ref"]), item["version"], item.get("edit_token"), item["payload"], None)
    if isinstance(value, Mapping) and value.get("$otto_result") == "candidate":
        return CandidateObservation(value["candidate"], value["receipt"], value["source_set_digest"])
    return value


class ReleaseOperations:
    """Finite serialized consumer; owner objects never cross this boundary."""

    def __init__(self, client: Any, reader: Any, authority: str) -> None:
        from herzchen.command_ports import SerializedCommandClient, SerializedReaderClient
        if not isinstance(client, SerializedCommandClient) or not isinstance(reader, SerializedReaderClient):
            raise TypeError("ReleaseOperations requires serialized Herzchen clients")
        self._client = client
        self._reader = reader
        self._authority = authority

    @classmethod
    def bootstrap(cls, database_path: str | Path, *, authority: str = "otto", actor_id: str = "otto-owner", credential_ref: str = "otto-owner-credential") -> "ReleaseOperations":
        from herzchen.kernel import Store
        from herzchen.domains.work.module import register_work
        store = Store.create(str(database_path), authority=authority)
        register_work(store)
        facade = _ReleaseCommandFacade(store, authority=authority, actor_id=actor_id, credential_ref=credential_ref)
        return cls(facade.command_port, facade.reader, authority)

    def _call(self, endpoint: str, *args: Any, **kwargs: Any) -> Any:
        return _decode_consumer(self._client.call(endpoint, *args, **kwargs))

    def close(self) -> None:
        self._call("close_store")

    def reopen(self) -> None:
        self._call("reopen_store")

    def register_repository(self, **kwargs: Any) -> Any:
        return self._call("register_repository", **kwargs)

    def get_repository(self, repository_id: str) -> RepositoryRecord:
        return self._call("get_repository", repository_id)

    def select_candidate(self, repository_id: str, **kwargs: Any) -> CandidateObservation:
        return self._call("select_candidate", repository_id, **kwargs)

    def record_required_check(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_required_check", repository_id, **kwargs)

    def record_manager_decision(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_manager_decision", repository_id, **kwargs)

    def record_merge(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_merge", repository_id, **kwargs)

    def record_promotion(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_promotion", repository_id, **kwargs)

    def record_publication(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_publication", repository_id, **kwargs)

    def record_deployment(self, repository_id: str, **kwargs: Any) -> Any:
        return self._call("record_deployment", repository_id, **kwargs)

    def get_candidate(self, candidate_ref: Any) -> Any:
        return self._call("get_candidate", candidate_ref)

    def get_decision(self, decision_ref: Any) -> Any:
        return self._call("get_decision", decision_ref)

    def get_receipt(self, logical_request_key: str) -> Any:
        return self._call("get_receipt", logical_request_key)

    def list_events(self, repository_id: str) -> tuple[Any, ...]:
        return self._call("list_events", repository_id)

    def snapshot_counts(self) -> Mapping[str, int]:
        return self._call("snapshot_counts")

    @property
    def registered_domains(self) -> tuple[str, ...]:
        return self._call("registered_domains")


def _ref(authority: str, repository_id: str) -> Any:
    from herzchen.contracts import ResourceRef
    return ResourceRef(authority, REPOSITORY_KIND, repository_id)


def _release_contribution() -> Any:
    from herzchen.contracts import DomainContribution
    operations = ("otto.repository.register", "otto.candidate.select", "otto.check.record", "otto.decision.record", "otto.merge.record", "otto.promotion.record", "otto.publication.record", "otto.deployment.record")
    events = tuple(item + ".recorded" for item in operations)
    return DomainContribution(domain_id=RELEASE_DOMAIN_ID, version="1.0", owner=RELEASE_OWNER, resource_types=(REPOSITORY_KIND,), document_types=(), namespace_types=("otto.engineering",), operation_types=operations, event_types=events, schema_revision=RELEASE_SCHEMA_REVISION, composition_bindings=("fnd-03.identities", "fnd-03.record_references", "fnd-03.transaction", "handler-required") + tuple("mutation-port:{}|{}|{}|{}".format(RELEASE_SCHEMA_REVISION, operation, REPOSITORY_KIND, event) for operation, event in zip(operations, events)))


def _source_set(values: Sequence[Any]) -> tuple[SourceSetEntry, ...]:
    entries = tuple(SourceSetEntry.from_value(value) for value in values); keys = [entry.key for entry in entries]
    if len(keys) != len(set(keys)): raise ReleaseError("duplicate_source_set_key", "source-set keys must be unique", keys=keys)
    return entries


def _source_digest(values: Sequence[SourceSetEntry]) -> str:
    return _digest([entry.to_dict() for entry in values])


def _initial_payload(repository_id: str, remote_id: str, target_id: str, baseline_head: str, target_head: str, source: Sequence[SourceSetEntry], owner: str, profile: ProcessProfile) -> dict[str, Any]:
    source_digest = _source_digest(source)
    return {"record_type": REPOSITORY_KIND, "schema_revision": RELEASE_SCHEMA_REVISION, "repository_id": _text(repository_id, "repository_id"), "remote_id": _text(remote_id, "remote_id"), "target_id": _text(target_id, "target_id"), "baseline_head": _text(baseline_head, "baseline_head"), "target_head": _text(target_head, "target_head"), "source_set": [entry.to_dict() for entry in source], "source_set_digest": source_digest, "owner": _text(owner, "owner"), "process_profile": profile.to_dict(), "rights": dict(RIGHTS), "candidate_ref": None, "decision_ref": None, "checks": {}, "merge": {"status": "not_performed"}, "promotion": {"status": "not_performed", "owner": owner, "completed_steps": [], "pending_steps": [], "unknown_steps": [], "source_set_digest": source_digest}, "publication": {"status": "not_performed"}, "deployment": {"status": "not_performed"}, "edit_token": _digest({"repository_id": repository_id, "source_set_digest": source_digest})}


def _guard_owner(record: RepositoryRecord, owner: str) -> None:
    if owner != record.payload.get("owner"): raise ReleaseError("authority_mismatch", "only the registered repository owner may recover this state", owner=owner)


def _guard_source_set(record: RepositoryRecord, source: Sequence[SourceSetEntry]) -> None:
    if _source_digest(source) != record.payload.get("source_set_digest"): raise ReleaseError("changed_source_set", "source set differs from the registered repository source set")


def _guard_source_digest(record: RepositoryRecord, supplied: Optional[str]) -> None:
    if supplied is not None and supplied != record.payload.get("source_set_digest"): raise ReleaseError("changed_source_set", "source set digest no longer matches the repository")


def _guard_expected(record: RepositoryRecord, version: Optional[int], head: Optional[str], token: Optional[str]) -> None:
    if version is not None and version != record.version: raise ReleaseError("version_conflict", "expected repository version is stale", expected_version=version, observed_version=record.version)
    if head is not None and head != record.payload.get("target_head"): raise ReleaseError("stale_head", "expected target head is stale", expected_head=head, observed_head=record.payload.get("target_head"))
    if token is not None and token != record.payload.get("edit_token"): raise ReleaseError("edit_token_conflict", "expected edit token is stale")


def _translate_public_error(exc: Exception) -> None:
    if type(exc).__name__ == "ReplayConflictError": raise ReleaseError("replay_conflict", "same logical key carries changed input; no new event was written") from exc
    if type(exc).__name__ in {"VersionConflictError", "TargetMismatchError"}: raise ReleaseError("version_conflict", str(exc)) from exc
    raise exc


__all__ = ["COMMANDS", "RIGHTS", "CandidateObservation", "ProcessProfile", "ReleaseError", "ReleaseOperations", "RepositoryRecord", "SourceSetEntry", "RELEASE_DOMAIN_ID", "RELEASE_SCHEMA_REVISION"]

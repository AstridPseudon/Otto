"""Production composition over existing owner work and DueRecord ports.

The runtime receives only finite consumer operations and an already-issued
DueRecord port.  It never receives a Store.  Owner reads and the due-record
CAS remain the source of scope, instruction, and attempt custody.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Callable, Mapping, Optional, Sequence

from .gateway import HerzchenAttemptCapture, OwnerDueRecordAttemptCapture, OttoGateway
from .orchestrator_route import OrchestratorRouteError, invoke_canonical_assignment
from otto.portfolio.owner_readers import (
    OwnerRoleRuntimeError,
    assignment_reader,
    json_value as _json,
    mandate_reader,
    owner_ref as _ref,
    project_reader,
    task_reader,
)
from otto.portfolio.resource_sync import normalize_instruction_contract
from otto.portfolio.resource_drift import apply_resource_sync_action, select_resource_sync_action


def _completed_worker_support_refs(result, verifier, authorization):
    """Exact delivered pins for authenticated completed-result reconstruction only."""
    if (not isinstance(result, Mapping) or result.get("context_digest_verified") is not True
            or not (result.get("outcome") == "succeeded" or (result.get("outcome") == "unknown"
                and result.get("unknown_reason") == "adopted operating setup changed before delivery"))):
        return ()
    brief = (result.get("resource_evidence") or {}).get("brief") or {}
    evidence = result.get("task_bound_evidence")
    digest = hashlib.sha256(json.dumps(brief, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    if (not isinstance(authorization, Mapping) or not isinstance(evidence, Mapping)
            or authorization.get("brief_sha256") != digest
            or evidence.get("owner_delivery_authorization") != authorization):
        raise OwnerRoleRuntimeError("completed worker retained authorization differs")
    work = (result.get("raw_result") or {}).get("work_envelope")
    if not isinstance(work, Mapping) or work.get("exit_status") is None or not isinstance(work.get("host_evidence", {}).get("otto_host_turn_context"), Mapping):
        # Other retained provider schemas keep the original current-brief path.
        return ()
    if work.get("exit_status") != 0:
        raise OwnerRoleRuntimeError("completed worker retained transport is not successful")
    parsed = verifier.observe_context(work.get("host_evidence", {}).get("otto_host_turn_context"),
        expected_session_id=result.get("physical_session_id"),
        expected_turn_id=result.get("observed_turn_id"),
        expected_profile=result.get("requested_profile"),
        expected_read_targets=brief.get("instruction_contract", {}).get("read_targets"),
        expected_read_scope=brief.get("instruction_contract", {}).get("read_scope"))
    if (parsed.get("task_bound_evidence") != evidence
            or parsed.get("model") != result.get("observed_model")
            or parsed.get("reasoning") != result.get("observed_reasoning")):
        raise OwnerRoleRuntimeError("completed worker retained native evidence differs")
    return tuple(item["ref"] for item in brief.get("context", {}).get("supporting_context", []))


class OwnerAuthorizedRoleCapture(OwnerDueRecordAttemptCapture):
    """Finite delivery authorization within the existing owner attempt CAS."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_brief_reader: Optional[Callable[[], str]] = None
        self.source_result_validator = None
        self.completed_scope_validator = None
        self.manager_command_contract = None
        from .native_result_verifier import CodexNativeResultVerifier
        self.native_result_verifier = CodexNativeResultVerifier()

    def record(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        brief = envelope.get("resource_evidence", {}).get("brief", {})
        if envelope.get("outcome") == "succeeded" and brief.get("instruction_contract", {}).get("source_inspection") is not None:
            if not callable(self.source_result_validator):
                raise OwnerRoleRuntimeError("source verifier missing before owner result CAS")
            self.source_result_validator(envelope.get("task_bound_evidence"), brief)
        return super().record(envelope)

    def authorize_delivery(self, logical_request_key: str, physical_session_id: str,
                           brief_sha256: str) -> Mapping[str, Any]:
        if self.current_brief_reader is None:
            raise OwnerRoleRuntimeError("current owner brief reader is unavailable")
        if not isinstance(brief_sha256, str) or len(brief_sha256) != 64:
            raise OwnerRoleRuntimeError("exact brief digest is required")
        if self.scope_validator is not None:
            failure = self.scope_validator()
            if failure:
                raise OwnerRoleRuntimeError(str(failure))
        if self.current_brief_reader() != brief_sha256:
            raise OwnerRoleRuntimeError("adopted owner brief changed before delivery")
        record = self._record()
        if record is None or self._scope_error(record, self.assignment_ref, self.generation, logical_request_key):
            raise OwnerRoleRuntimeError("owner occurrence is no longer admitted")
        attempt = self._attempt(record)
        if (attempt is None or attempt.get("state") != "claimed"
                or attempt.get("logical_request_key") != logical_request_key
                or attempt.get("physical_session_id") != physical_session_id):
            raise OwnerRoleRuntimeError("provider identity is not bound to the current owner claim")
        if attempt.get("delivery_authorization") is not None:
            raise OwnerRoleRuntimeError("delivery is already authorized or unresolved")
        authorization = {
            "status": "authorized", "logical_request_key": logical_request_key,
            "physical_session_id": physical_session_id, "brief_sha256": brief_sha256,
            "project_ref": self.project_ref, "task_ref": self.task_ref,
            "assignment_ref": self.assignment_ref, "generation": self.generation,
            "role": self.role, "principal": self.principal,
            "lifecycle_owner": self.lifecycle_owner, "owner_version": record.version,
        }
        saved = self._save(
            record, {**attempt, "delivery_authorization": authorization},
            "otto-delivery-authorize:" + logical_request_key + ":" + physical_session_id + ":" + brief_sha256,
        )
        receipt = saved.get("mutation_receipt") if isinstance(saved, Mapping) else None
        if not isinstance(receipt, Mapping) or receipt.get("status") != "committed" or receipt.get("replayed") is not False:
            raise OwnerRoleRuntimeError("owner did not commit a fresh delivery authorization")
        readback = self._record()
        bound = None if readback is None else self._attempt(readback)
        if (readback is None or self._scope_error(readback, self.assignment_ref, self.generation, logical_request_key)
                or bound is None or bound.get("delivery_authorization") != authorization):
            raise OwnerRoleRuntimeError("delivery authorization owner readback failed")
        return authorization


    def verify_delivery(self, logical_request_key: str, physical_session_id: str,
                        brief_sha256: str, authorization: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reread the same committed claim at recipient admission; never mutate."""
        if self.scope_validator is not None:
            failure = self.scope_validator()
            if failure:
                raise OwnerRoleRuntimeError(str(failure))
        if self.current_brief_reader is None or self.current_brief_reader() != brief_sha256:
            raise OwnerRoleRuntimeError("adopted owner brief changed before recipient admission")
        record = self._record()
        if record is None or self._scope_error(record, self.assignment_ref, self.generation, logical_request_key):
            raise OwnerRoleRuntimeError("owner occurrence is no longer admitted")
        attempt = self._attempt(record)
        expected = {"status": "authorized", "logical_request_key": logical_request_key,
                    "physical_session_id": physical_session_id, "brief_sha256": brief_sha256,
                    "project_ref": self.project_ref, "task_ref": self.task_ref,
                    "assignment_ref": self.assignment_ref, "generation": self.generation,
                    "role": self.role, "principal": self.principal,
                    "lifecycle_owner": self.lifecycle_owner}
        if (attempt is None or attempt.get("state") != "claimed"
                or attempt.get("logical_request_key") != logical_request_key
                or attempt.get("physical_session_id") != physical_session_id
                or attempt.get("delivery_authorization") != authorization
                or any(authorization.get(key) != value for key, value in expected.items())):
            raise OwnerRoleRuntimeError("current owner delivery authorization does not match recipient")
        return deepcopy(dict(authorization))

    def _completed_admission(self, attempt: Mapping[str, Any]) -> Mapping[str, Any]:
        admission = attempt.get("delivery_admission")
        if admission is not None:
            return admission
        proof = attempt.get("delivery_admission_reconciliation") or {}
        prior = proof.get("source_unknown") or {}
        result = attempt.get("result") or {}
        digest = lambda body: hashlib.sha256(json.dumps(_json(body), ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (proof.get("schema") == "otto.owner-native-admission-reconciliation.v1"
                and proof.get("resolver") == self.lifecycle_owner
                and proof.get("effect") == "retained_completed_native_turn_no_provider_replay"
                and digest(prior) == proof.get("source_unknown_sha256")
                and prior.get("operation") == "invoke" and prior.get("outcome") == "unknown"
                and proof.get("physical_session_id") == result.get("physical_session_id")
                and proof.get("observed_turn_id") == result.get("observed_turn_id")
                and proof.get("task_bound_evidence_sha256") == digest(result.get("task_bound_evidence"))):
            return proof
        if (proof.get("schema") == "otto.completed-resume-capture-reconciliation.v1"
                and proof.get("resolver") == self.lifecycle_owner
                and proof.get("effect") == "trusted_completed_resume_no_provider_replay"
                and digest(prior) == proof.get("source_unknown_sha256")
                and prior.get("operation") == "resume" and prior.get("outcome") == "unknown"
                and proof.get("physical_session_id") == result.get("physical_session_id")
                and (digest(result) == proof.get("source_unknown_sha256")
                     or digest(result) == proof.get("replacement_sha256"))):
            return proof
        return {}

    def verify_completed_delivery(self, logical_request_key: str, physical_session_id: str,
                                  brief_sha256: str, authorization: Mapping[str, Any]) -> Mapping[str, Any]:
        """Verify an admitted result under its unchanged completion capability.

        Admission still uses verify_delivery's full snapshot fence. A manager
        explicitly permitted to issue canonical commands may advance project/
        task revisions. Its assignment, mandate and exact native admission must
        remain unchanged; this settles transport, never accepts task judgment.
        """
        if not callable(self.completed_scope_validator):
            return self.verify_delivery(logical_request_key, physical_session_id, brief_sha256, authorization)
        failure = self.completed_scope_validator()
        if failure:
            raise OwnerRoleRuntimeError(str(failure))
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        admission = self._completed_admission(attempt or {})
        if (record is None or self._scope_error(record, self.assignment_ref, self.generation, logical_request_key)
                or attempt is None or attempt.get("state") not in {"claimed", "result"}
                or attempt.get("logical_request_key") != logical_request_key
                or attempt.get("physical_session_id") != physical_session_id
                or attempt.get("delivery_authorization") != authorization
                or authorization.get("brief_sha256") != brief_sha256
                or authorization.get("physical_session_id") != physical_session_id
                or admission.get("native_turn_started") is not True
                or admission.get("physical_session_id") != physical_session_id):
            raise OwnerRoleRuntimeError("completed role result differs from the exact admitted native claim")
        return deepcopy(dict(authorization))

    def validate_completed_manager_result(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        """Reparse admitted evidence against unchanged manager capability."""
        from .herzchen_adapter import HerzchenCodexAdapter
        if not callable(self.completed_scope_validator) or not isinstance(self.manager_command_contract, Mapping):
            raise OwnerRoleRuntimeError("completed result has no explicit canonical-manager capability")
        resource = value.get("resource_evidence") or {}
        brief = resource.get("brief") or {}
        contract = brief.get("instruction_contract")
        authorization = ((self._attempt(self._record()) or {}).get("delivery_authorization") or {})
        digest = lambda body: hashlib.sha256(json.dumps(_json(body), ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (contract != self.manager_command_contract or digest(brief) != resource.get("brief_sha256")
                or resource.get("brief_sha256") != authorization.get("brief_sha256")):
            raise OwnerRoleRuntimeError("completed manager result changed the admitted brief or current mandate contract")
        self.verify_completed_delivery(value.get("logical_request_key"), value.get("physical_session_id"),
                                       resource["brief_sha256"], authorization)
        raw = value.get("raw_result") or {}
        context = (raw.get("work_envelope") or {}).get("host_evidence", {}).get("otto_host_turn_context")
        parsed = self.native_result_verifier.observe_context(context,
            expected_session_id=value.get("physical_session_id"), expected_turn_id=value.get("observed_turn_id"),
            expected_profile=value.get("requested_profile"), expected_read_targets=contract.get("read_targets"),
            expected_read_scope=contract.get("read_scope"))
        evidence = parsed["task_bound_evidence"]
        admission = self._completed_admission(self._attempt(self._record()) or {})
        if (evidence != value.get("task_bound_evidence") or evidence.get("owner_delivery_authorization") != authorization
                or evidence.get("delivered_brief_digest") != digest(brief)
                or evidence.get("delivered_contract_digest") != digest(contract)
                or evidence.get("task_ref") != self.task_ref or evidence.get("assignment_ref") != self.assignment_ref
                or evidence.get("generation") != self.generation
                or parsed["model"] != value.get("requested_model") or parsed["reasoning"] != value.get("requested_reasoning")
                or parsed["turn_id"] != admission.get("observed_turn_id")):
            raise OwnerRoleRuntimeError("completed manager result differs from admitted native evidence")
        return parsed

    def reconcile_unknown_result(
        self, logical_request_key: str, replacement: Mapping[str, Any], *,
        resolver: str, trace_sha256: str, parser_revision: str,
    ) -> Mapping[str, Any]:
        """Replace one exact unknown capture after retained evidence is reparsed.

        This is an owner reconciliation operation, never a provider retry.  It
        preserves the original result digest and accepts only a successful
        replacement with the same immutable request, assignment, native
        session, authorization, and retained transport bytes.
        """
        if resolver != self.lifecycle_owner:
            raise OwnerRoleRuntimeError("only the lifecycle owner may reconcile an unknown result")
        if (not isinstance(trace_sha256, str) or len(trace_sha256) != 64
                or any(char not in "0123456789abcdef" for char in trace_sha256)
                or not isinstance(parser_revision, str) or not parser_revision.strip()):
            raise OwnerRoleRuntimeError("reconciliation requires an exact trace digest and parser revision")
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        prior = attempt.get("result") if isinstance(attempt, Mapping) else None
        value = deepcopy(dict(replacement)) if isinstance(replacement, Mapping) else None
        if (record is not None and attempt is not None and attempt.get("state") == "result"
                and attempt.get("logical_request_key") == logical_request_key
                and isinstance(prior, Mapping) and isinstance(value, Mapping)
                and prior == value and prior.get("outcome") == "succeeded"
                and isinstance(attempt.get("reconciliation"), Mapping)
                and attempt["reconciliation"].get("effect") == "retained_evidence_reparsed_no_provider_replay"):
            return {"outcome": "reconciled", "replayed": True,
                    "readback_version": record.version,
                    "reconciliation": attempt["reconciliation"], "attempt": attempt}
        if (record is None or attempt is None or attempt.get("state") != "result"
                or attempt.get("logical_request_key") != logical_request_key
                or not isinstance(prior, Mapping) or not isinstance(value, Mapping)
                or prior.get("outcome") != "unknown" or prior.get("delivery_state") != "unknown"):
            raise OwnerRoleRuntimeError("reconciliation requires the exact current unknown owner result")
        immutable = (
            "logical_request_key", "owner", "project_ref", "task_ref", "assignment_ref",
            "generation", "operation", "requested_profile", "requested_model",
            "requested_reasoning", "logical_agent_id", "physical_session_id",
            "native_session_id", "request_fingerprint",
        )
        if any(value.get(field) != prior.get(field) for field in immutable):
            raise OwnerRoleRuntimeError("reconciled result changed immutable owner custody")
        evidence = value.get("task_bound_evidence")
        authorization = attempt.get("delivery_authorization")
        if (value.get("outcome") != "succeeded" or value.get("delivery_state") not in {"done", "completed"}
                or value.get("context_digest_verified") is not True
                or value.get("observed_model") != record.requested_model
                or value.get("observed_reasoning") != record.requested_reasoning
                or not isinstance(evidence, Mapping)
                or evidence.get("assignment_ref") != self.assignment_ref
                or evidence.get("generation") != self.generation
                or evidence.get("session_id") != value.get("physical_session_id")
                or evidence.get("owner_delivery_authorization") != authorization):
            raise OwnerRoleRuntimeError("reconciled result lacks the exact successful owner/native join")
        prior_raw = prior.get("raw_result")
        next_raw = value.get("raw_result")
        if not isinstance(prior_raw, Mapping) or not isinstance(next_raw, Mapping):
            raise OwnerRoleRuntimeError("reconciled result lacks retained transport evidence")
        for field in ("initialization_receipt", "initialization_envelope", "owner_delivery_authorization"):
            if next_raw.get(field) != prior_raw.get(field):
                raise OwnerRoleRuntimeError("reconciled result changed retained initialization evidence")
        prior_work = prior_raw.get("work_envelope")
        next_work = next_raw.get("work_envelope")
        if not isinstance(prior_work, Mapping) or not isinstance(next_work, Mapping):
            raise OwnerRoleRuntimeError("reconciled result lacks retained work envelope")
        for field in ("command", "stdout", "stderr", "exit_status", "started_at", "ended_at",
                      "physical_session_id", "process_id", "input_packet_digest"):
            if next_work.get(field) != prior_work.get(field):
                raise OwnerRoleRuntimeError("reconciled result changed retained work transport bytes")
        digest = lambda body: hashlib.sha256(json.dumps(
            _json(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        prior_digest = digest(prior)
        reconciliation = {
            "schema": "otto.owner-result-reconciliation.v1",
            "resolver": resolver,
            "source_unknown_sha256": prior_digest,
            "trace_sha256": trace_sha256,
            "parser_revision": parser_revision,
            "effect": "retained_evidence_reparsed_no_provider_replay",
        }
        updated = {**attempt, "result": value, "reconciliation": reconciliation}
        saved = self._save(
            record, updated,
            "otto-gateway-reconcile:" + logical_request_key + ":" + prior_digest + ":" + trace_sha256,
        )
        readback = self._attempt(self._record())
        if readback != updated:
            raise OwnerRoleRuntimeError("reconciled owner result readback differs")
        return {"outcome": "reconciled", "readback_version": saved.get("version"),
                "reconciliation": reconciliation, "attempt": readback}

    def accept_result(self, logical_request_key: str, *, manager_actor: str) -> Mapping[str, Any]:
        """Accept one exact successful owner-authorized result through Due CAS."""
        record = self._record()
        if record is None:
            return {"outcome": "unknown", "status": "undetermined", "message": "due record is missing"}
        if manager_actor != self.lifecycle_owner:
            return {"outcome": "rejected", "status": "unsupported",
                    "error": {"code": "foreign_authority", "message": "only the lifecycle owner may accept the result"}}
        attempt = self._attempt(record)
        if attempt is None or attempt.get("logical_request_key") != logical_request_key:
            return {"outcome": "unknown", "status": "undetermined", "message": "attempt is not present"}
        result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else {}
        if attempt.get("state") != "result" or result.get("outcome") != "succeeded":
            return {"outcome": "not_accepted", "status": "undetermined",
                    "retry_allowed": False, "attempt": attempt}
        if (result.get("observed_model") != record.requested_model
                or result.get("observed_reasoning") != record.requested_reasoning):
            return {"outcome": "not_accepted", "status": "unsupported", "retry_allowed": False,
                    "error": {"code": "observed_host_attestation_required",
                              "message": "owner acceptance requires matching observed model/reasoning"},
                    "attempt": attempt}
        prior = attempt.get("manager_acceptance")
        if isinstance(prior, Mapping) and prior.get("owner") == manager_actor and prior.get("accepted") is True:
            return {"outcome": "accepted", "accepted": True, "replayed": True,
                    "readback_version": record.version, "attempt": attempt}
        digest = hashlib.sha256(json.dumps(
            _json(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        acceptance = {"accepted": True, "owner": manager_actor, "owner_version": record.version,
                      "logical_request_key": logical_request_key, "result_digest": digest}
        updated = {**attempt, "manager_acceptance": acceptance}
        saved = self._save(record, updated,
                           "otto-gateway-accept:" + logical_request_key + ":" + str(record.version))
        readback = self._attempt(self._record()) or updated
        return {"outcome": "accepted", "accepted": True, "replayed": False,
                "readback_version": saved.get("version"), "attempt": readback}

    def _publication_scope_error(self, record, assignment_ref, generation, key):
        if not getattr(self, "settled_publication", False):
            return self._scope_error(record, assignment_ref, generation, key)
        if (not self._same(record.target, self.expected_target)
                or record.project_ref != self.project_ref.get("id")
                or record.generation != generation or generation != self.generation
                or not self._same(assignment_ref, self.assignment_ref)
                or record.lifecycle_owner != self.lifecycle_owner or record.manager_ref != self.lifecycle_owner
                or not CanonicalRoleRuntime._settled_publication_matches(record, key, self.lifecycle_owner)):
            return "settled publication no longer matches exact owner result"
        return None

    def publish_analytical_result(self, envelope: Mapping[str, Any], result_owner: HerzchenAttemptCapture) -> Mapping[str, Any]:
        """Append an already CAS-recorded success; never replace an unknown.

        The existing assignment owner supplies idempotency and receipt readback.
        Publication failure leaves the original DueRecord result intact, so an
        exact publication retry does not need another provider operation.
        """
        from .herzchen_adapter import HerzchenCodexAdapter

        value = deepcopy(dict(envelope))
        key = value.get("logical_request_key")
        record = self._record()
        attempt = None if record is None else self._attempt(record)
        if (record is None or self._publication_scope_error(record, value.get("assignment_ref"), value.get("generation"), key)
                or attempt is None or attempt.get("state") != "result" or attempt.get("result") != value
                or value.get("outcome") != "succeeded" or value.get("delivery_state") not in {"done", "completed"}):
            raise OwnerRoleRuntimeError("analytical publication requires the exact current CAS-recorded success")
        if self.scope_validator is not None and self.scope_validator():
            raise OwnerRoleRuntimeError("canonical owner scope changed before publication")
        evidence = value.get("task_bound_evidence")
        resource = value.get("resource_evidence")
        brief = resource.get("brief") if isinstance(resource, Mapping) else None
        authorization = attempt.get("delivery_authorization")
        if not isinstance(evidence, Mapping) or not isinstance(brief, Mapping) or not isinstance(authorization, Mapping):
            raise OwnerRoleRuntimeError("analytical publication lacks authenticated evidence and owner brief")
        digest = lambda body: hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        brief_digest = digest(brief)
        expected = {"status": "authorized", "logical_request_key": key,
                    "physical_session_id": value.get("physical_session_id"), "brief_sha256": brief_digest,
                    "project_ref": self.project_ref, "task_ref": self.task_ref,
                    "assignment_ref": self.assignment_ref, "generation": self.generation,
                    "role": self.role, "principal": self.principal, "lifecycle_owner": self.lifecycle_owner}
        contract = brief.get("instruction_contract")
        if (self.current_brief_reader is None or self.current_brief_reader() != brief_digest
                or any(authorization.get(k) != v for k, v in expected.items())
                or evidence.get("owner_delivery_authorization") != authorization
                or evidence.get("task_ref") != self.task_ref or evidence.get("assignment_ref") != self.assignment_ref
                or evidence.get("generation") != self.generation
                or evidence.get("operation") != getattr(self.native_result_verifier, "native_work_operation", "resume")
                or evidence.get("delivered_brief_digest") != brief_digest
                or not isinstance(contract, Mapping) or evidence.get("delivered_contract_digest") != digest(contract)):
            raise OwnerRoleRuntimeError("analytical publication owner/brief binding changed")
        operation = evidence.get("operation_result")
        output = operation.get("output") if isinstance(operation, Mapping) else None
        answer = output.get("final_answer") if isinstance(output, Mapping) else None
        ref = answer.get("host_record") if isinstance(answer, Mapping) else None
        text = answer.get("text") if isinstance(answer, Mapping) else None
        if (not isinstance(text, str) or not text.strip()
                or not self.native_result_verifier.supports_final_answer(answer)
                or not isinstance(ref, Mapping)
                or not isinstance(ref.get("item_id"), str) or not ref["item_id"].strip()
                or ref.get("session_id") != value.get("physical_session_id") or ref.get("turn_id") != evidence.get("turn_id")):
            raise OwnerRoleRuntimeError("analytical publication lacks the exact native final text reference")
        body = text.encode("utf-8")
        if (answer.get("utf8_bytes") != len(body) or answer.get("text_sha256") != hashlib.sha256(body).hexdigest()
                or not isinstance(ref.get("raw_line_sha256"), str) or len(ref["raw_line_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in ref["raw_line_sha256"])):
            raise OwnerRoleRuntimeError("analytical publication native bytes/digest mismatch")
        raw = value.get("raw_result")
        receipt = raw.get("work_receipt") if isinstance(raw, Mapping) else None
        if not isinstance(raw, Mapping) or raw.get("worker_content") != [text]:
            raise OwnerRoleRuntimeError("analytical publication worker content mismatch")
        commands = evidence.get("host_records", {}).get("commands", [])
        if not isinstance(commands, list) or not commands:
            raise OwnerRoleRuntimeError("analytical publication lacks bounded read evidence")
        context = {"session_id": value.get("physical_session_id"), "turn_id": evidence.get("turn_id"),
                   "provenance": "host_owned_turn_context", "context_digest": evidence.get("context_digest"),
                   "model": value.get("observed_model"), "reasoning": value.get("observed_reasoning"),
                   "worker_content": [text], "task_bound_evidence": evidence}
        if isinstance(receipt, Mapping) and receipt.get("observed_profile") is not None:
            context["effective_profile"] = receipt["observed_profile"]
        self.native_result_verifier.observe_context(context, expected_session_id=value["physical_session_id"],
            expected_turn_id=evidence["turn_id"], expected_profile=value.get("requested_profile"),
            expected_read_targets=contract.get("read_targets"), expected_read_scope=contract.get("read_scope"))
        if contract.get("source_inspection") is not None:
            if not callable(self.source_result_validator):
                raise OwnerRoleRuntimeError("source verifier missing before assignment publication")
            self.source_result_validator(evidence, brief)
        prior = result_owner.read_assignment(self.assignment_ref, self.generation)
        if isinstance(prior, Mapping) and prior.get("outcome") == "unknown":
            raise OwnerRoleRuntimeError("unknown assignment result requires reconciliation")
        result_owner.record(value)
        saved = _json(result_owner.reader.get_receipt(key))
        # Capture the small conclusion once in the existing receipt. Pure
        # reads need no transcript parse/hash or assignment-history scan.
        summary = {"result_ref": saved["result_ref"], "result_digest": evidence["result_digest"],
                   "assignment_ref": self.assignment_ref, "generation": self.generation,
                   "logical_request_key": key, "conclusion": text[:4096],
                   "conclusion_sha256": answer["text_sha256"], "utf8_bytes": answer["utf8_bytes"],
                   "verification": {"context_digest_verified": True,
                                    "observed_turn_id": value.get("observed_turn_id")},
                   "usage": {"state": "unavailable", "reason": "no qualified native usage summary retained"}}
        # A finite host-selected verifier can retain its already-verified
        # capture-time projection. Provider JSON never chooses this seam.
        summary_capture = getattr(self.native_result_verifier, "capture_summary", None)
        captured_artifacts = None
        if callable(summary_capture):
            projection = summary_capture(evidence, result_ref=saved["result_ref"])
            summary["usage"] = projection["usage"]
            captured_artifacts = projection["artifacts"]
        from .usage_capture import compact_usage_capture
        if value.get("usage_capture") is not None:
            summary["usage_capture"] = compact_usage_capture(value["usage_capture"])
        record = self._record()
        if ((record.host_evidence or {}).get("captured_result_summary") != summary
                or (captured_artifacts is not None
                    and (record.host_evidence or {}).get("captured_artifacts") != captured_artifacts)):
            from dataclasses import replace
            self.due_port.save_due(record.schedule_id, replace(record, host_evidence={
                **(record.host_evidence or {}), "captured_result_summary": summary,
                **({"captured_artifacts": captured_artifacts} if captured_artifacts is not None else {})}).to_dict(),
                request_id="otto-result-summary:" + key, expected_version=record.version)
        return {"result_ref": saved["result_ref"], "result_digest": evidence["result_digest"]}


class CanonicalRoleRuntime:
    """Bound manager/orchestrator entrypoints over canonical owner records.

    A due occurrence is mandatory for dispatch.  Its `in_flight_request` is
    the owner-side admission fence; this wrapper does not claim scheduler
    origin.  Native profile/closure proof remains the injected host adapter's
    responsibility.
    """

    def __init__(self, *, operations: Any, portfolio: Any, due_port: Any,
                 adapter: Any, actor: str,
                 runtime_probe: Optional[Callable[[], Optional[Mapping[str, Any]]]] = None,
                 result_capture_factory: Optional[Callable[..., HerzchenAttemptCapture]] = None,
                 acceptance_readiness: Any = None, allowance_readiness: Any = None,
                 completed_task_readiness: Any = None, native_result_verifier: Any = None,
                 native_bodies: Any = None) -> None:
        required = ("reader", "assignments_port", "content_port", "binding")
        if operations is None or any(getattr(operations, name, None) is None for name in required):
            raise TypeError("operations must be the finite owner-backed Herzchen operations")
        if portfolio is None or getattr(portfolio, "operations", None) is not operations:
            raise TypeError("portfolio must wrap the same canonical owner operations")
        if due_port is None or not callable(getattr(due_port, "read_due", None)) or not callable(getattr(due_port, "save_due", None)):
            raise TypeError("due_port must expose finite read_due/save_due")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("authenticated owner actor id is required")
        if runtime_probe is not None and not callable(runtime_probe):
            raise TypeError("runtime_probe must be a trusted injected callable")
        if result_capture_factory is not None and not callable(result_capture_factory):
            raise TypeError("result_capture_factory must be an owner-issued callable")
        self.operations = operations
        self.portfolio = portfolio
        self.due_port = due_port
        self.adapter = adapter
        self.actor = actor
        self.runtime_probe = runtime_probe
        self.result_capture_factory = result_capture_factory
        self.acceptance_readiness = acceptance_readiness
        self.allowance_readiness = allowance_readiness
        self.completed_task_readiness = completed_task_readiness
        from .native_result_verifier import CodexNativeResultVerifier, require_native_verifier
        self.native_result_verifier = require_native_verifier(native_result_verifier or CodexNativeResultVerifier())
        self.native_bodies = native_bodies

    def prepare_execution_readiness(self, *, due: Any) -> Mapping[str, Any]:
        """Resolve exact BASE and execution scope without admitting an effect."""
        from .orchestrator_route import prepare_canonical_assignment_role_brief
        from otto.portfolio.operating_setup import validate_execution_contract
        target = due.target
        for field, expected in (("requested_model", due.requested_model),
                                ("requested_reasoning", due.requested_reasoning),
                                ("requested_profile", due.profile)):
            if not isinstance(expected, str) or not expected.strip() or target.get(field) != expected:
                raise OwnerRoleRuntimeError("role occurrence " + field + " is missing or conflicts with target")
        read_task = self._task_reader(target["project_ref"], target["task_ref"])
        if callable(self.completed_task_readiness):
            read_task = self.completed_task_readiness(due) or read_task
        prepared = prepare_canonical_assignment_role_brief(
            role=due.role, project_ref=target["project_ref"], task_ref=target["task_ref"],
            assignment_ref=due.assignment_ref, mandate_ref=target["mandate_ref"],
            expected_generation=due.generation,
            project_reader=self._project_reader(target["project_ref"]),
            task_reader=read_task,
            assignment_reader=self._assignment_reader(due.assignment_ref),
            mandate_reader=self._mandate_reader(target["project_ref"], target["mandate_ref"]),
            resource_reader=self.operations.content_port,
            supervisor_reader=(lambda: self._manager_supervisor(target["project_ref"])) if due.role == "manager" else None,
            direction_context_reader=getattr(self.operations, "direction_context_reader", None),
            lifecycle="resume" if due.execution_mode == "continue_existing" else "launch", as_of=due.anchor,
        )
        if hasattr(read_task, "completion_readback"):
            prepared["canonical_evidence"]["completed_task_readback"] = deepcopy(read_task.completion_readback)
        from otto.portfolio.role_context import configured_binding, selected_configuration
        configuration = selected_configuration(prepared["canonical_evidence"]["supporting_context"])
        selection = target.get("execution_selection", {})
        for field in ("model", "reasoning"):
            provenance = selection.get(field, {})
            if provenance.get("source") == "selected_configuration":
                configured = configured_binding(configuration, due.role)
                if (configuration is None or provenance.get("ref") != configuration["ref"]
                        or configured[field] != target["requested_" + field]):
                    raise OwnerRoleRuntimeError("selected role " + field + " changed; prepare a current occurrence")
        validate_execution_contract(prepared, target.get("requested_profile", due.profile),
                                    execution_manager=due.role == "manager")
        return prepared

    @staticmethod
    def _resource_ref(value: Mapping[str, Any]) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef.from_dict(value)

    def _manager_supervisor(self, project_ref):
        """Current project recipient from the existing authenticated issue port."""
        loop = self.portfolio._issue_loop()
        describe = getattr(loop.ports.delivery, "describe", None) if loop else None
        if not callable(describe):
            return None
        value = describe(project_ref)
        return {"project_ref": dict(project_ref), **{k: value[k] for k in
                ("assignment_ref", "generation", "principal", "conversation_ref")}}

    def _project_reader(self, project_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return project_reader(self.operations, project_pin)

    def _task_reader(self, project_pin: Mapping[str, Any], task_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return task_reader(self.operations, project_pin, task_pin)

    def _assignment_reader(self, assignment_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return assignment_reader(self.operations, assignment_pin)

    def _mandate_reader(self, project_pin: Mapping[str, Any], mandate_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return mandate_reader(self.operations, project_pin, mandate_pin)

    @staticmethod
    def _settled_publication_matches(due, key, owner):
        attempt = (due.host_evidence or {}).get("gateway_attempt") or {}
        result = attempt.get("result") or {}
        accepted = attempt.get("manager_acceptance") or {}
        return (due.stop_state == "completed" and due.completion_state == "succeeded"
                and due.in_flight_request is None and attempt.get("state") == "result"
                and attempt.get("logical_request_key") == key and result.get("logical_request_key") == key
                and result.get("outcome") == "succeeded" and result.get("context_digest_verified") is True
                and result.get("delivery_state") in {"done", "completed"}
                and result.get("assignment_ref") == due.assignment_ref and result.get("generation") == due.generation
                and result.get("observed_model") == due.requested_model
                and result.get("observed_reasoning") == due.requested_reasoning
                and accepted.get("accepted") is True and accepted.get("owner") == owner
                and accepted.get("logical_request_key") == key
                and accepted.get("result_digest") == hashlib.sha256(json.dumps(
                    _json(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()).hexdigest())

    def _binding(self, *, role: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                 assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
                 schedule_id: str, logical_request_key: str, expected_generation: int,
                 allow_settled_publication: bool = False) -> tuple[Mapping[str, Any], Mapping[str, Any], OwnerDueRecordAttemptCapture]:
        from otto.attention import DueRecord

        project = _ref(project_ref, "project_ref")
        task = _ref(task_ref, "task_ref")
        assignment_pin = _ref(assignment_ref, "assignment_ref")
        mandate = _ref(mandate_ref, "mandate_ref")
        assignment = self._assignment_reader(assignment_pin)({key: assignment_pin[key] for key in ("authority", "kind", "id")})
        observed_role = "worker" if assignment.get("role") == "executor" else assignment.get("role")
        if observed_role != role:
            raise OwnerRoleRuntimeError("current assignment role does not match this entrypoint")
        principal = _json(assignment.get("principal"))
        agent_id = principal if isinstance(principal, str) else principal.get("id") if isinstance(principal, Mapping) else None
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise OwnerRoleRuntimeError("current assignment principal is not a usable agent identity")
        due_value = self.due_port.read_due(schedule_id)
        if due_value is None:
            raise OwnerRoleRuntimeError("owner due occurrence is missing")
        due = DueRecord.from_dict(due_value)
        target = due.target if isinstance(due.target, Mapping) else {}
        expected_target = {"project_ref": project, "task_ref": task, "assignment_ref": assignment_pin,
                           "role": role, "principal": principal, "mandate_ref": mandate}
        if any(_json(target.get(key)) != value for key, value in expected_target.items()):
            raise OwnerRoleRuntimeError("owner due occurrence target does not match canonical assignment scope")
        if (due.role is not None and due.role != role) or due.recipient != agent_id:
            raise OwnerRoleRuntimeError("DueRecord role/recipient differs from the current assignment principal")
        if due.generation != expected_generation or due.project_ref != project["id"]:
            raise OwnerRoleRuntimeError("owner due occurrence project/generation is stale")
        if due.lifecycle_owner != self.actor or due.manager_ref != self.actor:
            raise OwnerRoleRuntimeError("owner due occurrence is not held by the configured lifecycle owner")
        settled = allow_settled_publication and self._settled_publication_matches(due, logical_request_key, self.actor)
        if due.in_flight_request != logical_request_key and not settled:
            raise OwnerRoleRuntimeError("owner due occurrence is not currently admitted for this request")
        project_reader = self._project_reader(project)
        task_reader = self._task_reader(project, task)
        assignment_reader = self._assignment_reader(assignment_pin)
        mandate_reader = self._mandate_reader(project, mandate)
        identities = {
            "project": {key: project[key] for key in ("authority", "kind", "id")},
            "task": {key: task[key] for key in ("authority", "kind", "id")},
            "assignment": {key: assignment_pin[key] for key in ("authority", "kind", "id")},
            "mandate": {key: mandate[key] for key in ("authority", "kind", "id")},
        }
        readers = {"project": project_reader, "task": task_reader,
                   "assignment": assignment_reader, "mandate": mandate_reader}
        snapshots = {
            name: _json(readers[name](identities[name]))
            for name in ("project", "task", "assignment", "mandate")
        }

        def validate_current_owner_scope() -> Optional[str]:
            try:
                current_due = self.due_port.read_due(schedule_id)
                if current_due is None or current_due.get("timeout_seconds") != due.timeout_seconds:
                    return "canonical owner occurrence timeout changed"
                for name in ("project", "task", "assignment", "mandate"):
                    current = _json(readers[name](identities[name]))
                    if current != snapshots[name]:
                        return f"canonical {name} changed after instruction preparation"
            except Exception:
                return "canonical owner scope is unavailable"
            return None

        capture = OwnerAuthorizedRoleCapture(
            self.due_port, schedule_id, project_ref=project, task_ref=task,
            assignment_ref=assignment_pin, generation=expected_generation,
            role=role, principal=principal, lifecycle_owner=self.actor,
            expected_target=target,
            scope_validator=validate_current_owner_scope,
        )
        capture.settled_publication = settled
        capture.native_result_verifier = self.native_result_verifier
        capture.native_bodies = self.native_bodies
        content = snapshots["mandate"].get("payload", {})
        contract = content.get("instruction_contract", {}) if isinstance(content, Mapping) else {}
        if (role == "manager" and contract.get("authority", {}).get("effect_profile") == "workspace-write-manager"
                and "canonical_manager_commands" in contract.get("allowed_operations", ())):
            def completed_scope():
                try:
                    current_due = self.due_port.read_due(schedule_id)
                    if current_due is None or current_due.get("timeout_seconds") != due.timeout_seconds:
                        return "canonical owner occurrence timeout changed"
                    for name in ("assignment", "mandate"):
                        if _json(readers[name](identities[name])) != snapshots[name]:
                            return f"canonical {name} changed after instruction preparation"
                    # The same identity-fenced readers still prove project/task
                    # membership; mutable revisions are effects of this role.
                    for name in ("project", "task"):
                        readers[name](identities[name])
                except Exception:
                    return "completed manager owner scope is unavailable"
                return None
            capture.completed_scope_validator = completed_scope
            capture.manager_command_contract = normalize_instruction_contract(contract)
        return assignment, dict(target), capture

    def _invoke(self, *, role: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any], schedule_id: str,
                logical_request_key: str, expected_generation: int, operation: str, lifecycle: str,
                packet_digest: str, request: Mapping[str, Any], as_of: str,
                required_resource_names: Sequence[str] = (), physical_session_id: Optional[str] = None,
                authorized_direct: bool = False) -> Any:
        occurrence_started = getattr(self.adapter, "monotonic_clock", __import__("time").monotonic)()
        assignment, target, capture = self._binding(
            role=role, project_ref=project_ref, task_ref=task_ref, assignment_ref=assignment_ref,
            mandate_ref=mandate_ref, schedule_id=schedule_id,
            logical_request_key=logical_request_key, expected_generation=expected_generation,
        )
        from otto.attention import DueRecord
        from otto.portfolio.operating_setup import OperatingSetupError, delivery_context, evaluate_setup, read_setup
        due_readiness = DueRecord.from_dict(self.due_port.read_due(schedule_id))
        setup = None
        if (due_readiness.host_evidence or {}).get("gateway_attempt") is None:
            self.prepare_execution_readiness(due=due_readiness)
            setup = read_setup(self.operations, project_ref)
            if setup is not None:
                decision = evaluate_setup(self, project_ref, setup, current_due=due_readiness)
                if not decision["ready"]:
                    raise OperatingSetupError("operating setup blocked: " + json.dumps(decision["blockers"], sort_keys=True))
        result_owner = None
        if authorized_direct and role == "worker":
            if self.result_capture_factory is None:
                raise OwnerRoleRuntimeError("authorized worker requires an owner-issued result capability")
            result_owner = self.result_capture_factory(project_ref=project_ref, task_ref=task_ref,
                assignment_ref=assignment_ref, generation=expected_generation, logical_request_key=logical_request_key)
            if not isinstance(result_owner, HerzchenAttemptCapture):
                raise OwnerRoleRuntimeError("owner result capability is unavailable")
            # Reject inaccessible existing keys before any provider operation.
            prior_result = result_owner.read(logical_request_key)
            if isinstance(prior_result, Mapping) and prior_result.get("outcome") == "unknown":
                raise OwnerRoleRuntimeError("unknown owner result requires reconciliation")
        principal = _json(assignment["principal"])
        logical_agent_id = principal if isinstance(principal, str) else principal["id"]
        due = self.due_port.read_due(schedule_id) or {}
        fresh_worker = due.get("execution_mode") == "fresh_bounded_worker"
        fresh_role = due.get("execution_mode") == "fresh_bounded_role"
        if fresh_worker and (role != "worker" or operation != "invoke" or physical_session_id is not None or not authorized_direct):
            raise OwnerRoleRuntimeError("fresh logical worker requires owner-authorized invoke without a native session")
        if fresh_role and (role not in {"orchestrator", "project_advisor"} or operation != "invoke" or physical_session_id is not None or not authorized_direct):
            raise OwnerRoleRuntimeError("fresh bounded role requires owner-authorized invoke without a native session")
        requested_model = target.get("requested_model", due.get("requested_model") or "gpt-5.6-luna")
        requested_reasoning = target.get("requested_reasoning", due.get("requested_reasoning") or "high")
        requested_profile = target.get("requested_profile", due.get("profile", "default"))
        from otto.attention import native_target_identity
        target_session_id = native_target_identity(target)
        if operation in {"resume", "send"}:
            if target_session_id is None:
                raise OwnerRoleRuntimeError("owner due target has no admitted native session identity")
            if physical_session_id is not None and physical_session_id != target_session_id:
                raise OwnerRoleRuntimeError("requested native session differs from current owner due target")
            physical_session_id = target_session_id
        elif physical_session_id is not None:
            raise OwnerRoleRuntimeError("a new launch cannot be redirected to a supplied native session")
        else:
            # A fresh logical target has no native session. The existing inert
            # start captures the provider-issued ID after the durable claim.
            physical_session_id = None
        adapter = self.adapter
        if authorized_direct:
            from .orchestrator_route import (
                _canonical_operation_evidence, prepare_canonical_assignment_role_brief,
            )

            def current_brief_digest() -> str:
                if setup is not None:
                    if read_setup(self.operations, project_ref) != setup:
                        raise OperatingSetupError("adopted operating setup changed before delivery")
                    decision = evaluate_setup(self, project_ref, setup, current_due=due_readiness)
                    if not decision["ready"]:
                        raise OperatingSetupError("operating setup changed before delivery: " + json.dumps(decision["blockers"], sort_keys=True))
                prepared = prepare_canonical_assignment_role_brief(
                    role=role, project_ref=project_ref, assignment_ref=assignment_ref,
                    mandate_ref=mandate_ref, expected_generation=expected_generation,
                    project_reader=self._project_reader(project_ref),
                    assignment_reader=self._assignment_reader(assignment_ref),
                    mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                    resource_reader=self.operations.content_port,
                supervisor_reader=(lambda: self._manager_supervisor(project_ref)) if role == "manager" else None,
                    direction_context_reader=getattr(self.operations, "direction_context_reader", None),
                    lifecycle=lifecycle, as_of=as_of,
                    required_resource_names=required_resource_names,
                    task_ref=task_ref, task_reader=self._task_reader(project_ref, task_ref),
                    operating_context_reader=lambda: delivery_context(self, project_ref, current_due=due_readiness),
                )
                if (fresh_worker or fresh_role) and not prepared["canonical_evidence"].get("mandate_instruction_contract"):
                    raise OwnerRoleRuntimeError("fresh bounded role requires an exact owner execution mandate contract")
                return _canonical_operation_evidence(
                    prepared, owner=logical_agent_id, task_ref=task_ref,
                )["brief_sha256"]

            capture.current_brief_reader = current_brief_digest
            current_brief_digest()  # Reject invalid launch/resume contracts before any provider claim/delivery.
            if role == "worker":
                strict_scope = capture.scope_validator
                def completed_worker_scope():
                    failure = strict_scope()
                    if failure:
                        return failure
                    try:
                        current_setup = read_setup(self.operations, project_ref)
                        if current_setup != setup:
                            self._verify_completed_worker_selector(setup, current_setup, project_ref)
                    except Exception as exc:
                        return str(exc)
                    return None
                # The adapter verifies the original native context before this
                # callback. Admission still uses the full current-brief guard.
                capture.completed_scope_validator = completed_worker_scope
            from otto.portfolio.execution_host import ExecutionHost
            def authorize(session_id, brief_sha256):
                host = ExecutionHost.current_bounded()
                if host is not None:
                    host.bind_native_session(schedule_id, session_id)
                return capture.authorize_delivery(logical_request_key, session_id, brief_sha256)
            adapter = self.adapter.bind_owner_authorization(
                ExecutionHost.owner_callback(authorize),
                verifier=ExecutionHost.owner_callback(lambda session_id, brief_sha256, authorization: capture.verify_delivery(
                    logical_request_key, session_id, brief_sha256, authorization,
                )),
                completed_verifier=ExecutionHost.owner_callback(lambda session_id, brief_sha256, authorization: capture.verify_completed_delivery(
                    logical_request_key, session_id, brief_sha256, authorization,
                )),
                **({"role": role, "profile": requested_profile}
                   if callable(getattr(self.adapter, "validate_owner_host_composition", None)) else {}),
            )
            capture.source_result_validator = getattr(adapter, "verify_source_result", None)
            owner_timeout = due.get("timeout_seconds")
            request = {**request, "owner_timeout_seconds": owner_timeout,
                       "launch_context": {"informational": True, "credential": False,
                           "principal": principal, "role": role,
                           "responsibility_ref": assignment.get("payload", {}).get("responsibility_ref"),
                           "assignment_ref": _json(assignment_ref), "generation": expected_generation,
                           "native_session": {"adapter": due.get("target", {}).get("native_adapter"),
                                              "id": physical_session_id,
                                              "fresh_binding": physical_session_id is None},
                           "occurrence_ref": {"schedule_id": schedule_id, "logical_request_key": logical_request_key}},
                       "owner_occurrence_deadline": occurrence_started + owner_timeout if isinstance(owner_timeout, (int, float)) and not isinstance(owner_timeout, bool) else None,
                       "expected_assignment_ref": _json(assignment_ref),
                       "expected_generation": expected_generation,
                       "logical_request_key": logical_request_key,
                       "expected_project_ref": _json(project_ref), "expected_role": role,
                       "expected_principal": principal, "expected_lifecycle_owner": self.actor}
        gateway = OttoGateway(adapter, attempt_capture=capture, require_owner_binding=True)
        result = invoke_canonical_assignment(
            gateway=gateway, role=role, project_ref=project_ref, task_ref=task_ref,
            assignment_ref=assignment_ref, mandate_ref=mandate_ref,
            project_reader=self._project_reader(project_ref), task_reader=self._task_reader(project_ref, task_ref),
            assignment_reader=self._assignment_reader(assignment_ref), mandate_reader=self._mandate_reader(project_ref, mandate_ref),
            resource_reader=self.operations.content_port,
            supervisor_reader=(lambda: self._manager_supervisor(project_ref)) if role == "manager" else None,
            direction_context_reader=getattr(self.operations, "direction_context_reader", None), owner=logical_agent_id,
            logical_agent_id=logical_agent_id, operation=operation, packet_digest=packet_digest,
            logical_request_key=logical_request_key, request=request, lifecycle=lifecycle, as_of=as_of,
            expected_generation=expected_generation, required_resource_names=required_resource_names,
            physical_session_id=physical_session_id, requested_model=requested_model,
            requested_reasoning=requested_reasoning, requested_profile=requested_profile,
            operating_context_reader=lambda: delivery_context(self, project_ref, current_due=due_readiness),
        )
        def complete(result):
            if authorized_direct and role == "worker" and isinstance(result, Mapping) and result.get("outcome") == "succeeded":
                envelope = result.get("attempt")
                evidence = envelope.get("task_bound_evidence") if isinstance(envelope, Mapping) else None
                operation_result = evidence.get("operation_result") if isinstance(evidence, Mapping) else None
                output = operation_result.get("output") if isinstance(operation_result, Mapping) else None
                if isinstance(output, Mapping) and "final_answer" in output:
                    resource = envelope.get("resource_evidence") or {}
                    brief = resource.get("brief") or {}
                    support = _completed_worker_support_refs(envelope, self.native_result_verifier,
                        (capture._attempt(capture._record()) or {}).get("delivery_authorization"))
                    def completed_brief_digest():
                        prepared = prepare_canonical_assignment_role_brief(
                            role=role, project_ref=project_ref, task_ref=task_ref,
                            assignment_ref=assignment_ref, mandate_ref=mandate_ref,
                            expected_generation=expected_generation,
                            project_reader=self._project_reader(project_ref),
                            task_reader=self._task_reader(project_ref, task_ref),
                            assignment_reader=self._assignment_reader(assignment_ref),
                            mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                            resource_reader=self.operations.content_port,
                            direction_context_reader=getattr(self.operations, "direction_context_reader", None),
                            lifecycle=lifecycle, as_of=as_of, required_resource_names=required_resource_names,
                            operating_context_reader=lambda: brief.get("context", {}).get("operating_setup"),
                            completed_support_refs=support,
                            include_role_context="introduction" in brief.get("operating_core", {}))
                        return _canonical_operation_evidence(prepared, owner=logical_agent_id,
                            task_ref=task_ref)["brief_sha256"]
                    # Only after the exact native result was CAS recorded:
                    # publication reconstructs its admitted packet, as recovery
                    # already does. This cannot authorize a new delivery.
                    capture.current_brief_reader = completed_brief_digest
                    published = capture.publish_analytical_result(envelope, result_owner)
                    result = {**result, "published_analytical_result": published}
            return result
        from otto.portfolio.owner_completion import after_owner
        return after_owner(result, complete)

    def _verify_completed_worker_selector(self, original, current, project_ref):
        """Only a verified same-manager manual continuation may differ."""
        from otto.attention import DueRecord
        from otto.portfolio.operating_setup import verify_role_conversation
        if not isinstance(original, Mapping) or not isinstance(current, Mapping):
            raise OwnerRoleRuntimeError("completed worker operating setup changed beyond its manager selector")
        before, after = deepcopy(dict(original)), deepcopy(dict(current))
        old_schedule = before.get("roles", {}).pop("manager", None)
        new_schedule = after.get("roles", {}).pop("manager", None)
        if (before != after or original.get("mode") != "manual"
                or not isinstance(old_schedule, str) or not isinstance(new_schedule, str)):
            raise OwnerRoleRuntimeError("completed worker operating setup changed beyond its manager selector")
        old = DueRecord.from_dict(self.due_port.read_due(old_schedule))
        new = DueRecord.from_dict(self.due_port.read_due(new_schedule))
        identity = lambda ref: tuple(ref.get(k) for k in ("authority", "kind", "id"))
        if (old.role != "manager" or new.role != "manager" or old.recipient != new.recipient
                or identity(old.assignment_ref) != identity(new.assignment_ref) or old.generation != new.generation
                or any(d.project_ref != project_ref["id"] or d.lifecycle_owner != self.actor
                    or d.manager_ref != self.actor or identity(d.target["project_ref"]) != identity(project_ref)
                    for d in (old, new))):
            raise OwnerRoleRuntimeError("completed worker manager selector is foreign")
        assignment = self._assignment_reader(new.assignment_ref)(
            {k: new.assignment_ref[k] for k in ("authority", "kind", "id")})
        if (assignment.get("role") != "manager" or assignment.get("generation") != new.generation
                or assignment.get("principal") != new.target.get("principal")
                or old.target.get("principal") != new.target.get("principal")):
            raise OwnerRoleRuntimeError("completed worker manager selector has changed authority")
        history = getattr(self.operations, "_owner_reader", None)
        sessions = [verify_role_conversation(due=d, assignment=assignment, project_ref=project_ref,
            due_port=self.due_port, actor=self.actor, assignment_history_reader=history)[0] for d in (old, new)]
        if sessions[0] != sessions[1]:
            raise OwnerRoleRuntimeError("completed worker manager selector changed native identity")

    def invoke_manager(self, **kwargs: Any) -> Any:
        """Legacy owner route; not the post-bind authorization contract."""
        return self._invoke(role="manager", **kwargs)

    def accept_role_result(
        self, *, role: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
        assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
        schedule_id: str, logical_request_key: str, expected_generation: int,
        lifecycle: str, as_of: str, required_resource_names: Sequence[str] = (),
        publish_result: bool = False,
    ) -> Mapping[str, Any]:
        """Publish/accept a retained verified result without invoking a provider.

        This is execution acceptance; substantive task completion still belongs
        to the assessment/completion operations. A publication crash is safely
        retried through the original assignment receipt. The owner may explicitly
        publish a manager's same retained result for an installed analytical
        handoff; this never invokes work or grants task acceptance.
        """
        if type(publish_result) is not bool or (publish_result and role not in {"manager", "worker"}):
            raise OwnerRoleRuntimeError("retained result publication requires an explicit manager/worker owner operation")
        _assignment, _target, capture = self._binding(
            role=role, project_ref=project_ref, task_ref=task_ref,
            assignment_ref=assignment_ref, mandate_ref=mandate_ref,
            schedule_id=schedule_id, logical_request_key=logical_request_key,
            expected_generation=expected_generation, allow_settled_publication=publish_result,
        )
        from .orchestrator_route import _canonical_operation_evidence, prepare_canonical_assignment_role_brief
        due = self.due_port.read_due(schedule_id) or {}
        attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
        result = attempt.get("result")
        resource = result.get("resource_evidence") if isinstance(result, Mapping) else None
        retained_context = ((resource or {}).get("brief") or {}).get("context", {}).get("operating_setup")
        completed_support_refs = _completed_worker_support_refs(result, self.native_result_verifier,
            attempt.get("delivery_authorization")) if role == "worker" else ()

        def current_brief_digest() -> str:
            prepared = prepare_canonical_assignment_role_brief(
                role=role, project_ref=project_ref, assignment_ref=assignment_ref,
                mandate_ref=mandate_ref, expected_generation=expected_generation,
                project_reader=self._project_reader(project_ref),
                assignment_reader=self._assignment_reader(assignment_ref),
                mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                resource_reader=self.operations.content_port,
                supervisor_reader=(lambda: self._manager_supervisor(project_ref)) if role == "manager" else None,
                direction_context_reader=getattr(self.operations, "direction_context_reader", None), lifecycle=lifecycle,
                as_of=as_of, required_resource_names=required_resource_names,
                task_ref=task_ref, task_reader=self._task_reader(project_ref, task_ref),
                # Settlement verifies the admitted packet. A peer replacement
                # or setup revision affects future turns, not this observation.
                operating_context_reader=lambda: retained_context,
                completed_support_refs=completed_support_refs,
                include_role_context="introduction" in ((resource or {}).get("brief") or {}).get("operating_core", {}),
            )
            return _canonical_operation_evidence(
                prepared, owner=_assignment["principal"], task_ref=task_ref,
            )["brief_sha256"]

        capture.current_brief_reader = current_brief_digest
        if role == "manager" and callable(capture.completed_scope_validator) and not capture.settled_publication:
            capture.validate_completed_manager_result(result)
        elif (not isinstance(resource, Mapping)
                or resource.get("brief_sha256") != current_brief_digest()):
            raise OwnerRoleRuntimeError("retained result does not use the current adopted owner brief")
        published = None
        if role == "worker" or publish_result:
            if self.result_capture_factory is None:
                raise OwnerRoleRuntimeError("result publication requires an owner-issued capability")
            result_owner = self.result_capture_factory(
                project_ref=project_ref, task_ref=task_ref, assignment_ref=assignment_ref,
                generation=expected_generation, logical_request_key=logical_request_key,
                **({"allow_project_manager": True} if role == "manager" and publish_result else {}),
            )
            capture.source_result_validator = getattr(self.adapter, "verify_source_result", None)
            published = capture.publish_analytical_result(result, result_owner)
        accepted = capture.accept_result(logical_request_key, manager_actor=self.actor)
        return {**accepted, "published_analytical_result": published}

    def reconcile_completed_resume_capture(self, *, schedule_id: str,
                                          expected_unknown_sha256: str,
                                          validate_only: bool = False) -> Mapping[str, Any]:
        """Reparse an exact completed authorized resume; retain failed transport."""
        from .manager_capture_reconciliation import reconcile_completed_resume_capture
        return reconcile_completed_resume_capture(self, schedule_id=schedule_id,
            expected_unknown_sha256=expected_unknown_sha256, validate_only=validate_only)

    def reconcile_missing_manager_capture(self, *, schedule_id: str,
                                          expected_claim_sha256: str,
                                          validate_only: bool = False) -> Mapping[str, Any]:
        """Capture an already admitted terminal turn after an owner interruption.

        This never sends native work. A claim without a result stays held unless
        the exact retained admission, delivered brief and successful native
        terminal record can all be verified under current owner custody.
        """
        from .manager_capture_reconciliation import reconcile_missing_manager_capture
        return reconcile_missing_manager_capture(self, schedule_id=schedule_id,
            expected_claim_sha256=expected_claim_sha256, validate_only=validate_only)

    def reconcile_fresh_manager_result(self, *, schedule_id: str,
                                       expected_unknown_sha256: str,
                                       validate_only: bool = False) -> Mapping[str, Any]:
        """Reparse a retained completed fresh-manager turn; never invoke a provider.

        Only the missing first-work admission defect is eligible. The trusted
        native reader supplies the trace, including overlap/terminal checks.
        The original UNKNOWN and separate historical admission proof remain
        explicit; this does not invent an original live admission callback.
        """
        from pathlib import Path
        from herzchen.adapters.host import _native_host_context
        from herzchen.contracts import HostIdentity, HostOperation, HostRequest, ResourceRef
        from .herzchen_adapter import HerzchenCodexAdapter
        digest = lambda body: hashlib.sha256(json.dumps(_json(body), ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        due = self.due_port.read_due(schedule_id) or {}
        attempt = (due.get("host_evidence") or {}).get("gateway_attempt") or {}
        prior = attempt.get("result") or {}
        receipt = attempt.get("delivery_admission_reconciliation")
        if (receipt and receipt.get("source_unknown_sha256") == expected_unknown_sha256
                and prior.get("outcome") == "succeeded"):
            return {"outcome": "reconciled", "replayed": True, "provider_called": False,
                    "admission_reconciliation": receipt}
        if (due.get("execution_mode") != "fresh_manager" or due.get("role") != "manager"
                or attempt.get("state") != "result" or attempt.get("delivery_admission") is not None
                or prior.get("operation") != "invoke" or prior.get("outcome") != "unknown"
                or prior.get("delivery_state") != "unknown"
                or prior.get("context_digest_verified") is not True
                or prior.get("error") != {"code": "authorized_result_unverified",
                    "message": "completed manager result differs from the exact admitted native claim"}
                or digest(prior) != expected_unknown_sha256):
            raise OwnerRoleRuntimeError("not the exact retained fresh-manager missing-admission result")
        for other in self.due_port.list_due():
            if other.get("schedule_id") == schedule_id:
                continue
            active = (other.get("host_evidence") or {}).get("gateway_attempt") or {}
            if (other.get("project_ref") == due.get("project_ref")
                    and (active.get("state") == "claimed" or other.get("host_state") == "running")):
                raise OwnerRoleRuntimeError("settle the overlapping owner occurrence before native reconciliation")
        _, _, capture = self._binding(role="manager", project_ref=prior["project_ref"],
            task_ref=prior["task_ref"], assignment_ref=prior["assignment_ref"],
            mandate_ref=due["target"]["mandate_ref"], schedule_id=schedule_id,
            logical_request_key=prior["logical_request_key"], expected_generation=prior["generation"])
        if not callable(capture.completed_scope_validator) or capture.completed_scope_validator():
            raise OwnerRoleRuntimeError("exact canonical-manager assignment/mandate custody is unavailable")
        record = capture._record()
        if (capture._scope_error(record, capture.assignment_ref, capture.generation, prior["logical_request_key"])
                or prior.get("logical_request_key") != due.get("in_flight_request")
                or prior.get("requested_profile") != due.get("profile")
                or prior.get("requested_model") != due.get("requested_model")
                or prior.get("requested_reasoning") != due.get("requested_reasoning")
                or prior.get("native_session_id") != prior.get("physical_session_id")):
            raise OwnerRoleRuntimeError("retained request no longer has exact owner/session/profile custody")
        reader = getattr(self.adapter, "trusted_thread_reader", None)
        if not callable(reader):
            raise OwnerRoleRuntimeError("trusted native metadata reader required; caller-supplied proof is insufficient")
        session, turn = prior["physical_session_id"], prior["observed_turn_id"]
        qualified = reader(session)
        thread = qualified.get("thread") or {}
        if thread.get("id") != session or not isinstance(thread.get("path"), str):
            raise OwnerRoleRuntimeError("trusted native metadata differs from retained session")
        raw = Path(thread["path"]).read_bytes()
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        active, completed, selected = set(), [], []
        for line, event in zip([line for line in raw.splitlines() if line.strip()], records):
            payload = event.get("payload") or {}
            identity = payload.get("turn_id")
            if event.get("type") == "session_meta":
                if (payload.get("id") or payload.get("session_id")) != session:
                    raise OwnerRoleRuntimeError("native trace session metadata differs")
            if event.get("type") == "event_msg":
                if payload.get("type") == "task_started":
                    active.add(identity)
                elif payload.get("type") in {"task_complete", "task_aborted"}:
                    active.discard(identity)
                    if payload.get("type") == "task_complete": completed.append(identity)
            if event.get("type") == "session_meta" or identity == turn:
                selected.append(line.decode())
        if active or not completed or completed[-1] != turn:
            raise OwnerRoleRuntimeError("retained target is not the latest completed native turn without overlap")
        authorization = attempt.get("delivery_authorization") or {}
        brief = prior["resource_evidence"]["brief"]
        contract = brief["instruction_contract"]
        expected = {"status": "authorized", "logical_request_key": prior["logical_request_key"],
            "physical_session_id": session, "project_ref": capture.project_ref,
            "task_ref": capture.task_ref, "assignment_ref": capture.assignment_ref,
            "generation": capture.generation, "role": "manager", "principal": capture.principal,
            "lifecycle_owner": self.actor, "brief_sha256": digest(brief)}
        if (any(authorization.get(key) != value for key, value in expected.items())
                or contract != capture.manager_command_contract
                or prior["resource_evidence"]["brief_sha256"] != digest(brief)):
            raise OwnerRoleRuntimeError("retained native authorization or current manager contract differs")
        retained = prior["raw_result"]
        if (retained.get("verification_failures") or retained.get("work_receipt", {}).get("outcome") != "succeeded"
                or retained.get("work_receipt", {}).get("operation") != "resume"
                or retained.get("initialization_envelope", {}).get("host_evidence", {}).get("invocation_turn_verified") is not True):
            raise OwnerRoleRuntimeError("retained READY/work transport is not an exact successful fresh-manager sequence")
        initialization = retained["initialization_envelope"]
        initial_receipt = retained.get("initialization_receipt") or {}
        initial_turn = initialization["host_evidence"].get("turn_id")
        if (initialization.get("physical_session_id") != session
                or initial_receipt.get("identity", {}).get("physical_session_id") != session
                or initial_receipt.get("outcome") != "succeeded"
                or initial_receipt.get("operation") != "invoke"
                or initial_turn == turn or initial_turn not in completed
                or completed.index(initial_turn) >= completed.index(turn)):
            raise OwnerRoleRuntimeError("retained native initialization/work lineage differs")
        request = HostRequest(HostOperation.RESUME, HostIdentity(prior["logical_agent_id"], session),
            ResourceRef.from_dict(prior["task_ref"]), prior["requested_profile"])
        context = _native_host_context(selected, request=request, session_id=session, turn_id=turn,
            delivered_brief=brief, delivered_authorization=authorization)
        if context != retained["work_envelope"]["host_evidence"]["otto_host_turn_context"]:
            raise OwnerRoleRuntimeError("actual native trace differs from original retained host context")
        observed = self.native_result_verifier.observe_context(context, expected_session_id=session,
            expected_turn_id=turn, expected_profile=prior["requested_profile"],
            expected_read_targets=contract.get("read_targets"), expected_read_scope=contract.get("read_scope"))
        evidence = observed["task_bound_evidence"]
        if (evidence != prior["task_bound_evidence"] or evidence.get("owner_delivery_authorization") != authorization
                or evidence.get("delivered_brief_digest") != digest(brief)
                or evidence.get("delivered_contract_digest") != digest(contract)
                or evidence.get("task_ref") != capture.task_ref or evidence.get("assignment_ref") != capture.assignment_ref
                or evidence.get("generation") != capture.generation
                or observed["model"] != due["requested_model"] or observed["reasoning"] != due["requested_reasoning"]
                or prior.get("observed_model") != observed["model"] or prior.get("observed_reasoning") != observed["reasoning"]):
            raise OwnerRoleRuntimeError("completed native evidence differs from exact task/model/assignment authorization")
        proof = {"schema": "otto.owner-native-admission-reconciliation.v1", "resolver": self.actor,
            "effect": "retained_completed_native_turn_no_provider_replay", "native_turn_started": True,
            "physical_session_id": session, "observed_turn_id": turn,
            "initialization_turn_id": initial_turn, "native_operation": "resume",
            "source_unknown_sha256": expected_unknown_sha256, "source_unknown": deepcopy(prior),
            "trace_sha256": hashlib.sha256(raw).hexdigest(), "task_bound_evidence_sha256": digest(evidence)}
        if validate_only:
            return {"outcome": "qualified", "provider_called": False,
                    "admission_reconciliation": proof, "store_mutated": False}
        if receipt is not None and receipt != proof:
            raise OwnerRoleRuntimeError("historical admission reconciliation changed")
        if capture.completed_scope_validator():
            raise OwnerRoleRuntimeError("canonical manager custody changed during native qualification")
        if receipt is None:
            # Use the record read before qualification: an intervening owner CAS
            # must conflict rather than replace any newly recorded effects.
            capture._save(record, {**attempt, "delivery_admission_reconciliation": proof},
                "otto-native-admission-reconcile:" + prior["logical_request_key"] + ":" + expected_unknown_sha256)
        capture.validate_completed_manager_result(prior)
        replacement = deepcopy(prior)
        replacement.update(outcome="succeeded", delivery_state="done", unknown_reason=None, error=None)
        reconciled = capture.reconcile_unknown_result(prior["logical_request_key"], replacement,
            resolver=self.actor, trace_sha256=proof["trace_sha256"],
            parser_revision="otto.fresh-manager-native-admission.v1")
        return {"outcome": "reconciled", "provider_called": False,
                "admission_reconciliation": proof, "result_reconciliation": reconciled["reconciliation"]}

    def refresh_completed_worker_artifacts(self, *, project_ref: Mapping[str, Any],
            task_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
            mandate_ref: Mapping[str, Any], schedule_id: str,
            logical_request_key: str, expected_generation: int) -> Mapping[str, Any]:
        """Refresh only a verified published worker's derived capture projection.

        Completed workers remain ineligible for provider admission. This owner
        operation accepts no replacement result, artifact path or native turn.
        It uses the exact existing publication and a separately verified result.
        """
        from dataclasses import replace
        from otto.attention import DueRecord
        project = _ref(project_ref, "project_ref")
        task = _ref(task_ref, "task_ref")
        assignment = _ref(assignment_ref, "assignment_ref")
        mandate = _ref(mandate_ref, "mandate_ref")
        readers = {"project": self._project_reader(project), "task": self._task_reader(project, task),
            "assignment": self._assignment_reader(assignment), "mandate": self._mandate_reader(project, mandate)}
        refs = {"project": project, "task": task, "assignment": assignment, "mandate": mandate}
        snapshots = {name: _json(readers[name]({k: ref[k] for k in ("authority", "kind", "id")})) for name, ref in refs.items()}
        current = snapshots["assignment"]
        principal = current.get("principal")
        if (not isinstance(principal, str) or current.get("role") not in {"worker", "executor"}
                or current.get("generation") != expected_generation):
            raise OwnerRoleRuntimeError("artifact refresh requires the current canonical worker")
        raw = self.due_port.read_due(schedule_id)
        if raw is None:
            raise OwnerRoleRuntimeError("artifact refresh occurrence is unavailable")
        due = DueRecord.from_dict(raw)
        target = due.target
        expected = {"project_ref": project, "task_ref": task, "assignment_ref": assignment,
            "mandate_ref": mandate, "role": "worker", "principal": principal}
        attempt = (due.host_evidence or {}).get("gateway_attempt") or {}
        value = attempt.get("result") or {}
        summary = (due.host_evidence or {}).get("captured_result_summary") or {}
        if (any(_json(target.get(k)) != v for k, v in expected.items())
                or due.assignment_ref != assignment or due.generation != expected_generation
                or due.recipient != principal or due.role != "worker" or due.project_ref != project["id"]
                or due.lifecycle_owner != self.actor or due.manager_ref != self.actor
                or due.stop_state != "completed" or due.completion_state != "succeeded"
                or due.in_flight_request is not None or attempt.get("state") != "result"
                or attempt.get("logical_request_key") != logical_request_key
                or value.get("logical_request_key") != logical_request_key
                or value.get("outcome") != "succeeded" or value.get("context_digest_verified") is not True
                or value.get("assignment_ref") != assignment or value.get("generation") != expected_generation
                or not isinstance(value.get("physical_session_id"), str) or not value["physical_session_id"]
                or (target.get("native_id") is not None and value["physical_session_id"] != target["native_id"])
                or value.get("observed_model") != due.requested_model
                or value.get("observed_reasoning") != due.requested_reasoning
                or (summary.get("verification") or {}).get("context_digest_verified") is not True):
            raise OwnerRoleRuntimeError("artifact refresh requires exact settled verified worker capture")
        if not callable(self.result_capture_factory) or not callable(getattr(self.native_result_verifier, "capture_summary", None)):
            raise OwnerRoleRuntimeError("owner artifact capture capability is unavailable")
        result_owner = self.result_capture_factory(project_ref=project, task_ref=task,
            assignment_ref=assignment, generation=expected_generation, logical_request_key=logical_request_key)
        if not isinstance(result_owner, HerzchenAttemptCapture) or result_owner.read(logical_request_key) != value:
            raise OwnerRoleRuntimeError("artifact refresh lacks the exact canonical published result")
        receipt = _json(result_owner.reader.get_receipt(logical_request_key))
        if receipt.get("result_ref") != summary.get("result_ref"):
            raise OwnerRoleRuntimeError("artifact refresh publication reference changed")
        evidence = value.get("task_bound_evidence") or {}
        brief = (value.get("resource_evidence") or {}).get("brief") or {}
        contract = brief.get("instruction_contract") or {}
        authorization = attempt.get("delivery_authorization") or {}
        expected_auth = {"status": "authorized", "logical_request_key": logical_request_key,
            "physical_session_id": value.get("physical_session_id"), "project_ref": project,
            "task_ref": task, "assignment_ref": assignment, "generation": expected_generation,
            "role": "worker", "principal": principal, "lifecycle_owner": self.actor}
        if (any(authorization.get(k) != v for k,v in expected_auth.items())
                or evidence.get("owner_delivery_authorization") != authorization
                or evidence.get("assignment_ref") != assignment or evidence.get("generation") != expected_generation):
            raise OwnerRoleRuntimeError("artifact refresh owner/native authorization changed")
        context = {"session_id": value["physical_session_id"], "turn_id": value.get("observed_turn_id"),
            "provenance": "host_owned_turn_context", "context_digest": evidence.get("context_digest"),
            "model": value["observed_model"], "reasoning": value["observed_reasoning"],
            "worker_content": value.get("worker_content"), "task_bound_evidence": evidence}
        if value.get("observed_profile") is not None:
            context["effective_profile"] = value["observed_profile"]
        self.native_result_verifier.observe_context(context, expected_session_id=value["physical_session_id"],
            expected_turn_id=value.get("observed_turn_id"), expected_profile=due.profile,
            expected_read_targets=contract.get("read_targets"), expected_read_scope=contract.get("read_scope"))
        projection = self.native_result_verifier.capture_summary(evidence, result_ref=summary["result_ref"])
        # Recheck all current canonical scope and exact Due bytes before CAS.
        if (self.due_port.read_due(schedule_id) != raw
                or any(_json(readers[name]({k:ref[k] for k in ("authority", "kind", "id")})) != snapshots[name] for name,ref in refs.items())):
            raise OwnerRoleRuntimeError("artifact refresh current custody changed")
        changed = (due.host_evidence or {}).get("captured_artifacts") != projection["artifacts"]
        if changed:
            updated = replace(due, host_evidence={**(due.host_evidence or {}), "captured_artifacts": projection["artifacts"]})
            self.due_port.save_due(schedule_id, updated.to_dict(),
                request_id="otto-artifact-projection-refresh:" + logical_request_key,
                expected_version=due.version)
        return {"outcome": "refreshed" if changed else "replayed", "result_ref": summary["result_ref"],
            "artifact_count": len(projection["artifacts"]), "provider_called": False,
            "new_result_identity": False, "native_result_unchanged": True}

    def reconcile_worker_result(
        self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
        assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
        schedule_id: str, logical_request_key: str, expected_generation: int,
        lifecycle: str, as_of: str, replacement: Mapping[str, Any],
        trace_sha256: str, parser_revision: str,
        required_resource_names: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        """Reconcile retained worker evidence without invoking the provider."""
        if self.result_capture_factory is None:
            raise OwnerRoleRuntimeError("worker reconciliation requires an owner-issued result capability")
        _assignment, _target, capture = self._binding(
            role="worker", project_ref=project_ref, task_ref=task_ref,
            assignment_ref=assignment_ref, mandate_ref=mandate_ref,
            schedule_id=schedule_id, logical_request_key=logical_request_key,
            expected_generation=expected_generation,
        )
        from .orchestrator_route import (
            _canonical_operation_evidence, prepare_canonical_assignment_role_brief,
        )
        due = self.due_port.read_due(schedule_id) or {}
        original = (((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("result") or {})
        original_brief = (original.get("resource_evidence") or {}).get("brief") or {}
        retained_context = original_brief.get("context", {}).get("operating_setup")
        completed_support_refs = _completed_worker_support_refs(original, self.native_result_verifier,
            ((due.get("host_evidence") or {}).get("gateway_attempt") or {}).get("delivery_authorization"))

        def current_brief_digest() -> str:
            prepared = prepare_canonical_assignment_role_brief(
                role="worker", project_ref=project_ref, assignment_ref=assignment_ref,
                mandate_ref=mandate_ref, expected_generation=expected_generation,
                project_reader=self._project_reader(project_ref),
                assignment_reader=self._assignment_reader(assignment_ref),
                mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                resource_reader=self.operations.content_port,
                                direction_context_reader=getattr(self.operations, "direction_context_reader", None),
                lifecycle=lifecycle, as_of=as_of,
                required_resource_names=required_resource_names,
                task_ref=task_ref, task_reader=self._task_reader(project_ref, task_ref),
                operating_context_reader=lambda: retained_context,
                completed_support_refs=completed_support_refs,
                include_role_context="introduction" in ((original.get("resource_evidence") or {}).get("brief") or {}).get("operating_core", {}),
            )
            return _canonical_operation_evidence(
                prepared, owner=replacement.get("logical_agent_id"), task_ref=task_ref,
            )["brief_sha256"]

        capture.current_brief_reader = current_brief_digest
        resource = replacement.get("resource_evidence")
        if (not isinstance(resource, Mapping)
                or resource.get("brief_sha256") != current_brief_digest()):
            raise OwnerRoleRuntimeError("reconciled result does not use the current adopted owner brief")
        reconciled = capture.reconcile_unknown_result(
            logical_request_key, replacement, resolver=self.actor,
            trace_sha256=trace_sha256, parser_revision=parser_revision,
        )
        result_owner = self.result_capture_factory(
            project_ref=project_ref, task_ref=task_ref,
            assignment_ref=assignment_ref, generation=expected_generation,
            logical_request_key=logical_request_key,
        )
        if not isinstance(result_owner, HerzchenAttemptCapture):
            raise OwnerRoleRuntimeError("owner result capability is unavailable")
        published = capture.publish_analytical_result(replacement, result_owner)
        accepted = capture.accept_result(logical_request_key, manager_actor=self.actor)
        if accepted.get("accepted") is not True:
            raise OwnerRoleRuntimeError("reconciled result was not accepted by the owner occurrence")
        return {"outcome": "reconciled", "attempt": reconciled,
                "published_analytical_result": published, "manager_acceptance": accepted}

    def invoke_orchestrator(self, **kwargs: Any) -> Any:
        """Legacy owner route; not the post-bind authorization contract."""
        return self._invoke(role="orchestrator", **kwargs)

    def invoke_role(self, *, role: str, mode: str, **kwargs: Any) -> Any:
        """Run a direct, owner-authorized route or hold an unsupported mode.

        The direct route requires a strict host-context adapter that can
        withhold the task until provider identity has current owner readback.
        Caller-native receipts alone do not authorize task delivery.
        """
        if role not in {"orchestrator", "manager", "worker", "project_advisor"}:
            raise OwnerRoleRuntimeError("role must be orchestrator, manager, worker, or project_advisor")
        if mode not in {"direct", "caller_native"}:
            raise OwnerRoleRuntimeError("mode must be direct or caller_native")

        receipt_field = "direct_startup_receipt" if mode == "direct" else "native_launch_receipt"
        receipt = kwargs.pop(receipt_field, None)
        if (mode == "direct" and receipt is None
                and getattr(self, "operations", None) is not None
                and getattr(getattr(self, "adapter", None), "require_host_context", False) is True
                and callable(getattr(getattr(self, "adapter", None), "bind_owner_authorization", None))):
            return self._invoke(role=role, authorized_direct=True, **kwargs)
        if not isinstance(receipt, Mapping) and getattr(self, "operations", None) is None:
            return self._authorization_unsupported(
                role=role, code=f"{mode}_authorization_receipt_missing",
                message=f"{mode} mode has no identity-correlated bind/readback authorization receipt",
            )
        # Validate the current owner occurrence even when authorization proof
        # is absent, so the held result cannot hide a stale or foreign wake.
        assignment, target, _capture = self._binding(
            role=role, project_ref=kwargs.get("project_ref"), task_ref=kwargs.get("task_ref"),
            assignment_ref=kwargs.get("assignment_ref"), mandate_ref=kwargs.get("mandate_ref"),
            schedule_id=kwargs.get("schedule_id"), logical_request_key=kwargs.get("logical_request_key"),
            expected_generation=kwargs.get("expected_generation"),
        )
        if kwargs.get("lifecycle") == "callback":
            if kwargs.get("operation") != "resume":
                raise OwnerRoleRuntimeError("an admitted callback must resume the bound owner session")
            target_session_id = next((target.get(key) for key in ("physical_session_id", "conversation_id", "native_id")
                                      if isinstance(target.get(key), str) and target.get(key).strip()), None)
            supplied_session_id = kwargs.get("physical_session_id")
            if target_session_id is None or (supplied_session_id is not None and supplied_session_id != target_session_id):
                raise OwnerRoleRuntimeError("requested native session differs from current owner due target")
        if not isinstance(receipt, Mapping):
            return self._authorization_unsupported(
                role=role, code=f"{mode}_authorization_receipt_missing",
                message=f"{mode} mode has no identity-correlated bind/readback authorization receipt",
            )
        project = _ref(kwargs.get("project_ref"), "project_ref")
        task = _ref(kwargs.get("task_ref"), "task_ref")
        assignment_ref = _ref(kwargs.get("assignment_ref"), "assignment_ref")
        mandate = _ref(kwargs.get("mandate_ref"), "mandate_ref")
        from .orchestrator_route import prepare_canonical_assignment_role_brief

        prepared = prepare_canonical_assignment_role_brief(
            role=role, project_ref=project, assignment_ref=assignment_ref, mandate_ref=mandate,
            expected_generation=kwargs.get("expected_generation"),
            project_reader=self._project_reader(project),
            assignment_reader=self._assignment_reader(assignment_ref),
            mandate_reader=self._mandate_reader(project, mandate), resource_reader=self.operations.content_port,
            supervisor_reader=(lambda: self._manager_supervisor(project)) if role == "manager" else None,
            direction_context_reader=getattr(self.operations, "direction_context_reader", None),
            lifecycle=kwargs.get("lifecycle", "launch"), as_of=kwargs.get("as_of", ""),
            required_resource_names=kwargs.get("required_resource_names", ()),
            task_ref=task, task_reader=self._task_reader(project, task),
        )
        principal = _json(assignment.get("principal"))
        expected = {
            "role": role,
            "project_ref": project,
            "task_ref": task,
            "assignment_ref": assignment_ref,
            "mandate_ref": mandate,
            "generation": kwargs["expected_generation"],
            "principal": principal,
            "schedule_id": kwargs.get("schedule_id"),
            "logical_request_key": kwargs.get("logical_request_key"),
            "operation": kwargs.get("operation"),
            "lifecycle": kwargs.get("lifecycle"),
            "prepared_digest": prepared["resource_evidence"]["brief_sha256"],
            "packet_digest": kwargs.get("packet_digest"),
            "resource_brief_sha256": prepared["resource_evidence"]["brief_sha256"],
        }
        for field, value in expected.items():
            if _json(receipt.get(field)) != value:
                raise OwnerRoleRuntimeError(f"caller-native receipt {field} is foreign or stale")
        parent_ref = target.get("parent_assignment_ref")
        if _json(receipt.get("parent_assignment_ref")) != _json(parent_ref):
            raise OwnerRoleRuntimeError("caller-native receipt parent_assignment_ref is foreign or stale")
        native_id = receipt.get("native_id")
        host = receipt.get("host")
        tool = receipt.get("tool")
        if not all(isinstance(value, str) and value.strip() for value in (native_id, host, tool)):
            raise OwnerRoleRuntimeError("caller-native receipt requires native_id, host, and tool provenance")
        return self._authorization_unsupported(
            role=role, code=f"{mode}_bind_readback_authorization_unavailable",
            message="owner/provider does not expose a verified bind/readback and recipient go-ahead operation",
            native_id=native_id, host=host, tool=tool, project_ref=project,
            task_ref=task, assignment_ref=assignment_ref, generation=kwargs["expected_generation"],
            prepared_digest=expected["prepared_digest"], packet_digest=kwargs.get("packet_digest"),
            resource_brief_sha256=expected["resource_brief_sha256"],
        )

    @staticmethod
    def _authorization_unsupported(*, role: str, code: str, message: str, **identity: Any) -> dict[str, Any]:
        return {
            "outcome": "unsupported",
            "role": role,
            "boundary": "bind_readback_recipient_authorize",
            "identity_status": "unverified" if identity else "unavailable",
            "identity": dict(identity),
            "authorization": "held",
            "task_effects": False,
            "launch": False,
            "retry_launch": False,
            "error": {"code": code, "message": message},
        }

    def invoke_admitted_callback(self, *, role: str, **kwargs: Any) -> Any:
        """Resume only an actual current owner DueRecord occurrence.

        This verifies owner admission state and exact assignment custody; it
        does not attest which scheduler delivered the callback.
        """
        kwargs["operation"] = "resume"
        kwargs["lifecycle"] = "resume"
        if role not in {"manager", "orchestrator", "project_advisor"}:
            raise OwnerRoleRuntimeError("callback role must be manager, orchestrator, or project_advisor")
        result = self._invoke(role=role, **kwargs)
        if isinstance(result, Mapping):
            return {**result, "callback_admission": "current_owner_due_record", "scheduler_origin_attested": False}
        return result

    def _attempt_projection(self, inbox: Mapping[str, Any], *, schedule_id: str,
                            project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                            assignment_ref: Mapping[str, Any], expected_generation: int) -> dict[str, Any]:
        from herzchen.contracts import ResourceRef

        projected = deepcopy(dict(inbox))
        try:
            from otto.attention import DueRecord

            current = self.due_port.read_due(schedule_id)
            if current is None:
                return projected
            due = DueRecord.from_dict(current)
            target = due.target if isinstance(due.target, Mapping) else {}
            expected = {"project_ref": _ref(project_ref, "project_ref"), "task_ref": _ref(task_ref, "task_ref"),
                        "assignment_ref": _ref(assignment_ref, "assignment_ref")}
            if any(_json(target.get(key)) != value for key, value in expected.items()) or due.generation != expected_generation:
                return projected
            identity = ResourceRef(self.operations.binding.authority, "otto.due-record", schedule_id)
            owner_record = self.operations.reader.get_record(identity)
            if owner_record is None or owner_record.ref.kind != "otto.due-record":
                return projected
            owner_payload = _json(owner_record.payload)
            if not isinstance(owner_payload, Mapping) or owner_payload.get("schedule_id") != schedule_id or owner_payload != _json(current):
                return projected
            evidence = owner_payload.get("host_evidence", {})
            capture = evidence.get("gateway_attempt") if isinstance(evidence, Mapping) else None
            attempt = capture.get("result") if isinstance(capture, Mapping) and capture.get("state") == "result" else None
            if not isinstance(attempt, Mapping):
                attempt = {"outcome": "unknown", "unknown_reason": "no terminal owner attempt result is recorded"}
            if attempt.get("assignment_ref", expected["assignment_ref"]) != expected["assignment_ref"] or attempt.get("generation", expected_generation) != expected_generation:
                return projected
            attempts = list(projected.get("attempts", ()))
            attempts.append({"source_ref": _json(owner_record.ref), "assignment_ref": expected["assignment_ref"],
                            "generation": expected_generation, "task_ref": expected["task_ref"], "attempt": dict(attempt),
                            "source":"otto.due-record host_evidence (owner readback)"})
            projected["attempts"] = attempts
        except Exception:
            # Missing or mismatched readback must leave the owner projection
            # unaugmented; the selector then returns its held dependency.
            return projected
        return projected

    def hourly_resource_check(self, *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                              assignment_ref: Mapping[str, Any], schedule_id: str,
                              expected_generation: int, lifecycle: str = "resume") -> dict[str, Any]:
        inbox = self.portfolio.manager_inbox(project_ref, actor=self.actor, safety_scan=True)
        projected = self._attempt_projection(
            inbox, schedule_id=schedule_id, project_ref=project_ref, task_ref=task_ref,
            assignment_ref=assignment_ref, expected_generation=expected_generation,
        )
        observation = None if self.runtime_probe is None else self.runtime_probe()
        attempts = projected.get("attempts", [])
        exact_attempt = next((item for item in attempts if isinstance(item, Mapping)
                              and isinstance(item.get("source_ref"), Mapping)
                              and item["source_ref"].get("kind") == "otto.due-record"
                              and item["source_ref"].get("id") == schedule_id
                              and item.get("assignment_ref") == _ref(assignment_ref, "assignment_ref")
                              and item.get("generation") == expected_generation), None)
        if exact_attempt is None:
            material = {"project_identity": {key: _ref(project_ref, "project_ref")[key] for key in ("authority", "kind", "id")},
                        "task_ref": _ref(task_ref, "task_ref"), "assignment_ref": _ref(assignment_ref, "assignment_ref"),
                        "generation": expected_generation, "schedule_id": schedule_id, "state": "owner_due_record_attempt_readback_missing"}
            discrepancy_key = "resource-drift-" + hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
            return {"selection": {"schema": "otto.resource-drift.selection.v1", "outcome": "held_attempt_missing",
                                  "discrepancy_key": discrepancy_key, "dependency": "owner_due_record_attempt_readback",
                                  "action": None, "resource_sync_verified": False, "verified_progress": False,
                                  "dispatch": False, "notify": False}, "attention": None, "dispatch": False}
        selection = select_resource_sync_action(
            inbox=projected, project_ref=project_ref, task_ref=task_ref, assignment_ref=assignment_ref,
            attempt_ref=exact_attempt["source_ref"],
            expected_generation=expected_generation, runtime_observation=observation, lifecycle=lifecycle,
        )
        if selection.get("outcome") != "selected_revisit":
            return {"selection": selection, "attention": None, "dispatch": False}
        applied = apply_resource_sync_action(portfolio=self.portfolio, project_ref=project_ref, actor=self.actor, selection=selection)
        return {"selection": selection, "attention": applied, "dispatch": False}


__all__ = ["CanonicalRoleRuntime", "OwnerRoleRuntimeError"]

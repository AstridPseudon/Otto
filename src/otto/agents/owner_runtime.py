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
from otto.portfolio.resource_drift import apply_resource_sync_action, select_resource_sync_action


class OwnerAuthorizedRoleCapture(OwnerDueRecordAttemptCapture):
    """Finite delivery authorization within the existing owner attempt CAS."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_brief_reader: Optional[Callable[[], str]] = None
        self.source_result_validator = None

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
        if (record is None or self._scope_error(record, value.get("assignment_ref"), value.get("generation"), key)
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
                or evidence.get("generation") != self.generation or evidence.get("operation") != "resume"
                or evidence.get("delivered_brief_digest") != brief_digest
                or not isinstance(contract, Mapping) or evidence.get("delivered_contract_digest") != digest(contract)):
            raise OwnerRoleRuntimeError("analytical publication owner/brief binding changed")
        operation = evidence.get("operation_result")
        output = operation.get("output") if isinstance(operation, Mapping) else None
        answer = output.get("final_answer") if isinstance(output, Mapping) else None
        ref = answer.get("host_record") if isinstance(answer, Mapping) else None
        text = answer.get("text") if isinstance(answer, Mapping) else None
        if (not isinstance(text, str) or not text.strip()
                or answer.get("format") != "codex-cli-0.158.0-native-final-text-v1" or answer.get("phase") != "final_answer"
                or not isinstance(ref, Mapping) or ref.get("item_type") != "AgentMessage" or ref.get("event_type") != "item_completed"
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
        HerzchenCodexAdapter._observed_context(context, expected_session_id=value["physical_session_id"],
            expected_turn_id=evidence["turn_id"], expected_read_targets=contract.get("read_targets"))
        if contract.get("source_inspection") is not None:
            if not callable(self.source_result_validator):
                raise OwnerRoleRuntimeError("source verifier missing before assignment publication")
            self.source_result_validator(evidence, brief)
        prior = result_owner.read_assignment(self.assignment_ref, self.generation)
        if isinstance(prior, Mapping) and prior.get("outcome") == "unknown":
            raise OwnerRoleRuntimeError("unknown assignment result requires reconciliation")
        result_owner.record(value)
        saved = _json(result_owner.reader.get_receipt(key))
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
                 result_capture_factory: Optional[Callable[..., HerzchenAttemptCapture]] = None) -> None:
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

    @staticmethod
    def _resource_ref(value: Mapping[str, Any]) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef.from_dict(value)

    def _project_reader(self, project_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return project_reader(self.operations, project_pin)

    def _task_reader(self, project_pin: Mapping[str, Any], task_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return task_reader(self.operations, project_pin, task_pin)

    def _assignment_reader(self, assignment_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return assignment_reader(self.operations, assignment_pin)

    def _mandate_reader(self, project_pin: Mapping[str, Any], mandate_pin: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], Any]:
        return mandate_reader(self.operations, project_pin, mandate_pin)

    def _binding(self, *, role: str, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any],
                 assignment_ref: Mapping[str, Any], mandate_ref: Mapping[str, Any],
                 schedule_id: str, logical_request_key: str, expected_generation: int) -> tuple[Mapping[str, Any], Mapping[str, Any], OwnerDueRecordAttemptCapture]:
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
        if due.in_flight_request != logical_request_key:
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
                prepared = prepare_canonical_assignment_role_brief(
                    role=role, project_ref=project_ref, assignment_ref=assignment_ref,
                    mandate_ref=mandate_ref, expected_generation=expected_generation,
                    project_reader=self._project_reader(project_ref),
                    assignment_reader=self._assignment_reader(assignment_ref),
                    mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                    resource_reader=self.operations.content_port,
                    lifecycle=lifecycle, as_of=as_of,
                    required_resource_names=required_resource_names,
                    task_ref=task_ref, task_reader=self._task_reader(project_ref, task_ref),
                )
                if (fresh_worker or fresh_role) and not prepared["canonical_evidence"].get("mandate_instruction_contract"):
                    raise OwnerRoleRuntimeError("fresh bounded role requires an exact owner execution mandate contract")
                return _canonical_operation_evidence(
                    prepared, owner=logical_agent_id, task_ref=task_ref,
                )["brief_sha256"]

            capture.current_brief_reader = current_brief_digest
            if fresh_worker or fresh_role:
                current_brief_digest()  # Reject missing/setup/conflicting contracts before any provider claim/delivery.
            adapter = self.adapter.bind_owner_authorization(
                lambda session_id, brief_sha256: capture.authorize_delivery(
                    logical_request_key, session_id, brief_sha256,
                ),
                verifier=lambda session_id, brief_sha256, authorization: capture.verify_delivery(
                    logical_request_key, session_id, brief_sha256, authorization,
                ),
            )
            capture.source_result_validator = getattr(adapter, "verify_source_result", None)
            owner_timeout = due.get("timeout_seconds")
            request = {**request, "owner_timeout_seconds": owner_timeout,
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
            resource_reader=self.operations.content_port, owner=logical_agent_id,
            logical_agent_id=logical_agent_id, operation=operation, packet_digest=packet_digest,
            logical_request_key=logical_request_key, request=request, lifecycle=lifecycle, as_of=as_of,
            expected_generation=expected_generation, required_resource_names=required_resource_names,
            physical_session_id=physical_session_id, requested_model=requested_model,
            requested_reasoning=requested_reasoning, requested_profile=requested_profile,
        )
        if authorized_direct and role == "worker" and isinstance(result, Mapping) and result.get("outcome") == "succeeded":
            envelope = result.get("attempt")
            evidence = envelope.get("task_bound_evidence") if isinstance(envelope, Mapping) else None
            operation_result = evidence.get("operation_result") if isinstance(evidence, Mapping) else None
            output = operation_result.get("output") if isinstance(operation_result, Mapping) else None
            if isinstance(output, Mapping) and "final_answer" in output:
                published = capture.publish_analytical_result(envelope, result_owner)
                result = {**result, "published_analytical_result": published}
        return result

    def invoke_manager(self, **kwargs: Any) -> Any:
        """Legacy owner route; not the post-bind authorization contract."""
        return self._invoke(role="manager", **kwargs)

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

        def current_brief_digest() -> str:
            prepared = prepare_canonical_assignment_role_brief(
                role="worker", project_ref=project_ref, assignment_ref=assignment_ref,
                mandate_ref=mandate_ref, expected_generation=expected_generation,
                project_reader=self._project_reader(project_ref),
                assignment_reader=self._assignment_reader(assignment_ref),
                mandate_reader=self._mandate_reader(project_ref, mandate_ref),
                resource_reader=self.operations.content_port,
                lifecycle=lifecycle, as_of=as_of,
                required_resource_names=required_resource_names,
                task_ref=task_ref, task_reader=self._task_reader(project_ref, task_ref),
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

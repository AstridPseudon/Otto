"""Finite owner-only views for the retained Usage project.

This facade deliberately has no target-project, actor, SQL, filesystem, or
Store-open input. It consumes the already authenticated owner lane and only
the existing injected evidence command handler for a bounded preview.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from herzchen.command_ports import CommandTransportClosed, WriterAuthorityDenied, owner_local_engine
from herzchen.contracts import ResourceRef, canonical_json


USAGE_PROJECT_ID = "project-0414b14adc7aa1b935e1dc773660"
_TASK_LIMIT = 100
_MAX_CURSOR = 512
_MAX_PROJECTED_BYTES = 65536
_MAX_TASKS = 100
_MAX_STATUS_BYTES = 65536
_KNOWN_EVIDENCE_STATUS_REFERENCE = {
    "authority": "otto-project-operating-setup-20261005-owner-v1",
    "kind": "dat.content.document",
    "id": "evidence-a074c4b017c3e761737cb5f5d1f4",
    "revision": "rev-1",
}

_PROJECT_FIELDS = {
    "lifecycle": ("lifecycle",),
    "tasks": ("tasks",),
    "join_assignment_ref": ("metadata", "otto_orchestrator", "assignment_ref"),
    "join_project_ref": ("metadata", "otto_orchestrator", "project_ref"),
    "join_portfolio_ref": ("metadata", "otto_orchestrator", "portfolio_ref"),
    "join_generation": ("metadata", "otto_orchestrator", "generation"),
    "close_report_ref": ("lifecycle_control", "close_request", "report_ref"),
    "close_project_ref": ("lifecycle_control", "close_request", "project_ref"),
    "close_manager_ref": ("lifecycle_control", "close_request", "manager_assignment"),
    "close_task_refs": ("lifecycle_control", "close_request", "task_refs"),
    "close_receipt_ref": ("lifecycle_control", "close_request", "receipt", "result_ref"),
    "close_generation": ("lifecycle_control", "close_request", "generation"),
    "terminal_acceptance_status": ("lifecycle_control", "terminal_evidence", "acceptance", "status"),
    "terminal_publication_status": ("lifecycle_control", "terminal_evidence", "publication", "status"),
    "terminal_remote_status": ("lifecycle_control", "terminal_evidence", "remote", "status"),
    "terminal_runtime_status": ("lifecycle_control", "terminal_evidence", "runtime", "status"),
    "reconciliation_status": ("lifecycle_control", "reconciliation", "status"),
    "reconciliation_mode": ("lifecycle_control", "reconciliation", "mode"),
    "reconciliation_survivor_refs": ("lifecycle_control", "reconciliation", "survivor_refs"),
    "observation_mode": ("lifecycle_control", "reconciliation", "observation", "mode"),
    "observation_pm_owned_schedule_ids": ("lifecycle_control", "reconciliation", "observation", "pm_owned_schedule_ids"),
    "observation_unknown_ownership": ("lifecycle_control", "reconciliation", "observation", "unknown_ownership"),
    "observation_ownership": ("lifecycle_control", "reconciliation", "observation", "ownership"),
    "observation_coverage": ("lifecycle_control", "reconciliation", "observation", "coverage"),
    "observation_shared_records": ("lifecycle_control", "reconciliation", "observation", "shared_records"),
    "reconciliation_host_effects": ("lifecycle_control", "reconciliation", "host_effects"),
}

_TASK_FIELDS = {
    "project_ref": ("project_ref",),
    "lifecycle": ("lifecycle",),
    "assignment_ref": ("assignment_ref",),
    "completion_candidate_ref": ("completion", "candidate_ref"),
    "completion_result_ref": ("completion", "result_ref"),
    "completion_evidence_refs": ("completion", "evidence_refs"),
    "completion_gate_refs": ("completion", "gate_refs"),
    "completion_assignment_ref": ("completion", "assignment_ref"),
    "completion_attempt_ref": ("completion", "attempt_ref"),
    "completion_source_refs": ("completion", "source_refs"),
    "effect_candidate_ref": ("effect_packet", "candidate_ref"),
    "effect_result_ref": ("effect_packet", "result_ref"),
    "effect_evidence_refs": ("effect_packet", "evidence_refs"),
    "effect_gate_refs": ("effect_packet", "gate_refs"),
    "effect_assignment_ref": ("effect_packet", "assignment_ref"),
    "effect_source_refs": ("effect_packet", "source_refs"),
    "settlement_candidate_ref": ("settlement", "candidate_ref"),
    "settlement_result_ref": ("settlement", "result_ref"),
    "settlement_evidence_refs": ("settlement", "evidence_refs"),
    "settlement_gate_refs": ("settlement", "gate_refs"),
    "settlement_assignment_ref": ("settlement", "assignment_ref"),
    "settlement_source_refs": ("settlement", "source_refs"),
    "result_refs": ("results",),
    "observation_refs": ("observations",),
}


class RetentionOwnerRead:
    def __init__(self, service: Any, *, storage_receipt: Mapping[str, Any] | None = None,
                 evidence_handler: Any = None) -> None:
        self.service = service
        self.storage_receipt = storage_receipt
        self.evidence_handler = evidence_handler

    def call(self, request: Mapping[str, Any], *, root: Any, actor: Any) -> Mapping[str, Any]:
        handle = request.get("handle")
        if not isinstance(handle, Mapping) or not isinstance(handle.get("view"), str):
            raise ValueError("retention read requires a view handle")
        view = handle["view"]
        if view == "lifecycle":
            if set(handle) != {"view"}:
                raise ValueError("lifecycle view accepts only its view selector")
            return self._lifecycle(root=root, actor=actor)
        if view == "storage":
            if set(handle) != {"view"}:
                raise ValueError("storage view accepts only its view selector")
            _owner, project = self._project_context(root=root, actor=actor)
            if not _has_current_reconciliation(project.payload):
                return {"outcome": "held", "view": "storage", "complete": False,
                        "currentness": "not-revalidated", "provider_called": False, "writes": 0,
                        "reason": "fixed Usage project is not completed with current reconciled lifecycle control"}
            return self._storage()
        if view == "evidence-status":
            if set(handle) != {"view", "reference"}:
                raise ValueError("evidence status requires the exact retained reference")
            return self._evidence_status(handle, root=root, actor=actor)
        if view == "reclaim-preview":
            if set(handle) != {"view", "cutoff", "cursor", "limit"}:
                raise ValueError("reclaim preview requires explicit cutoff, cursor and limit")
            return self._preview(handle, root=root, actor=actor, request_key=request.get("request_key"))
        raise ValueError("unsupported retention view")

    def _evidence_status(self, handle: Mapping[str, Any], *, root: Any, actor: Any) -> Mapping[str, Any]:
        """Read one owner-proven Evidence pin through the existing handler.

        The fixed reference is deliberately bound to the retained selection
        diagnosis. This route projects metadata only; it does not expose a
        payload, dependency decision, eligibility claim, or mutation hook.
        """
        owner, project = self._project_context(root=root, actor=actor)
        if actor != owner.owner_actor:
            raise PermissionError("evidence status requires the authenticated service owner")
        if not _has_current_reconciliation(project.payload):
            return {"outcome": "held", "view": "evidence-status", "complete": False,
                    "provider_called": False, "writes": 0,
                    "reason": "fixed Usage project is not completed with current reconciled lifecycle control"}
        reference = handle.get("reference")
        if not isinstance(reference, Mapping) or dict(reference) != _KNOWN_EVIDENCE_STATUS_REFERENCE:
            raise PermissionError("evidence status reference is not the retained authorized pin")
        if self.evidence_handler is None or not callable(getattr(self.evidence_handler, "status", None)):
            return {"outcome": "unavailable", "view": "evidence-status", "complete": False,
                    "provider_called": False, "writes": 0,
                    "reason": "existing Evidence status handler is not injected"}
        requested = ResourceRef.from_dict(reference)
        status = self.evidence_handler.status(requested, actor=actor)
        if not isinstance(status, Mapping):
            raise ValueError("Evidence status returned an invalid bounded record")
        if len(canonical_json(status).encode()) > _MAX_STATUS_BYTES:
            raise ValueError("Evidence status exceeds its bounded metadata limit")
        returned_value = status.get("reference")
        returned = _safe_ref(returned_value.to_dict() if hasattr(returned_value, "to_dict") else returned_value)
        if returned != reference:
            raise PermissionError("Evidence status returned a different revision")
        if status.get("representation") != "managed":
            raise PermissionError("retained Evidence pin is not a managed representation")
        document = status.get("document")
        if not isinstance(document, Mapping) or document.get("role") != "evidence":
            raise PermissionError("retained pin is not an Evidence document")
        manifest = status.get("manifest")
        if not isinstance(manifest, Mapping) or manifest.get("record_type") != "dat.evidence.manifest":
            raise PermissionError("retained Evidence pin lacks the managed evidence manifest")
        origin = manifest.get("origin")
        if not isinstance(origin, Mapping) or not _same_ref_identity(origin.get("project_ref"), project.ref.to_dict()):
            raise PermissionError("retained Evidence pin has foreign project provenance")
        storage = manifest.get("storage")
        if not isinstance(storage, Mapping) or storage.get("kind") != "managed-file":
            raise PermissionError("retained Evidence pin has no managed-file representation")
        byte_length = status.get("byte_length", manifest.get("byte_length"))
        byte_digest = manifest.get("byte_digest", status.get("content_digest"))
        if type(byte_length) is not int or byte_length < 0:
            raise ValueError("Evidence status has invalid byte length")
        if (not isinstance(byte_digest, str) or len(byte_digest) != 64
                or any(c not in "0123456789abcdef" for c in byte_digest.lower())):
            raise ValueError("Evidence status has invalid byte digest")
        io_work = _bounded_io_work(status.get("io_work"))
        if (io_work is None or any(io_work.get(name) != 0 for name in
                ("payload_bytes_read", "payload_bytes_parsed", "payload_bytes_hashed"))):
            raise PermissionError("Evidence status lacks a zero-payload metadata observation")
        provenance = {name: _safe_ref(origin.get(name)) for name in ("project_ref", "task_ref", "attempt_ref")}
        provenance = {name: value for name, value in provenance.items() if value is not None}
        if not _same_ref_identity(provenance.get("project_ref"), project.ref.to_dict()):
            raise PermissionError("Evidence status provenance is not bound to the fixed Usage project")
        current_head_value = status.get("current_head")
        current_head = _safe_ref(current_head_value.to_dict() if hasattr(current_head_value, "to_dict") else current_head_value)
        if (current_head is None or not current_head.get("revision")
                or not _same_ref_identity(current_head, reference)):
            raise PermissionError("Evidence status has no current head")
        if status.get("payload_verification") != "not-revalidated":
            raise ValueError("Evidence status lacks explicit payload verification state")
        return {"outcome": "read", "view": "evidence-status", "complete": True,
                "reference": reference, "current_head": current_head,
                "representation": "managed", "evidence_role": "evidence",
                "availability": _bounded_label(status.get("availability")),
                "verification": _bounded_label(status.get("verification")),
                "payload_verification": "not-revalidated",
                "byte_length": byte_length, "byte_digest": byte_digest,
                "format": _bounded_label(manifest.get("format", status.get("format"))),
                "provenance": provenance, "io_work": io_work,
                "dependency_evaluation": "not-performed",
                "eligibility": "not-evaluated", "provider_called": False, "writes": 0}

    def _fixed_project(self) -> tuple[Any, Any]:
        owner = self.service.server.owner
        project_ref = ResourceRef(owner.store.authority, "work.project", USAGE_PROJECT_ID)
        read = owner.store.consumer().project_identity_fields_for_refs(
            [project_ref], fields=_PROJECT_FIELDS, max_projection_bytes=_MAX_PROJECTED_BYTES)
        if not read or read[0].get("state") != "available" or not isinstance(read[0].get("fields"), Mapping):
            raise PermissionError("fixed Usage project is missing or requires bounded detail")
        row = read[0]
        fields = row["fields"]
        project_payload = {
            "lifecycle": fields.get("lifecycle"),
            "tasks": fields.get("tasks"),
            "metadata": {"otto_orchestrator": {
                "assignment_ref": fields.get("join_assignment_ref"),
                "project_ref": fields.get("join_project_ref"),
                "portfolio_ref": fields.get("join_portfolio_ref"),
                "generation": fields.get("join_generation"),
            }},
            "lifecycle_control": {
                "close_request": {
                    "report_ref": fields.get("close_report_ref"),
                    "project_ref": fields.get("close_project_ref"),
                    "manager_assignment": fields.get("close_manager_ref"),
                    "task_refs": fields.get("close_task_refs"),
                    "receipt": fields.get("close_receipt_ref"),
                    "generation": fields.get("close_generation"),
                },
                "terminal_evidence": {
                    name: {"status": fields.get(f"terminal_{name}_status")}
                    for name in ("acceptance", "publication", "remote", "runtime")
                },
                "reconciliation": {
                    "status": fields.get("reconciliation_status"),
                    "mode": fields.get("reconciliation_mode"),
                    "survivor_refs": fields.get("reconciliation_survivor_refs"),
                    "observation": {
                        "mode": fields.get("observation_mode"),
                        "pm_owned_schedule_ids": fields.get("observation_pm_owned_schedule_ids"),
                        "unknown_ownership": fields.get("observation_unknown_ownership"),
                        "ownership": fields.get("observation_ownership"),
                        "coverage": fields.get("observation_coverage"),
                        "shared_records": fields.get("observation_shared_records"),
                    },
                    "host_effects": fields.get("reconciliation_host_effects"),
                },
            },
        }
        current_ref = ResourceRef.from_dict(row["ref"])
        return owner, SimpleNamespace(ref=current_ref, payload=project_payload)

    def _lifecycle(self, *, root: Any, actor: Any) -> Mapping[str, Any]:
        owner, project_record = self._project_context(root=root, actor=actor)
        project = project_record.payload
        consumer = owner.store.consumer()
        task_refs = project.get("tasks")
        project_task_refs_available = isinstance(task_refs, (list, tuple))
        declared_task_count = len(task_refs) if project_task_refs_available else None
        rows = []
        selected_ids = set()
        assignments = [root.ref.to_dict()]
        observations = []
        held = 0
        valid_refs = []
        invalid_refs = 0
        truncated = bool(project_task_refs_available and len(task_refs) > _MAX_TASKS)
        if truncated:
            held += len(task_refs) - _MAX_TASKS
        membership_refs = []
        unversioned_membership = False
        mixed_membership_revisions = False
        for raw_ref in (task_refs[:_MAX_TASKS] if project_task_refs_available else ()):
            task_ref = _safe_ref(raw_ref)
            if (task_ref is None or task_ref.get("authority") != project_record.ref.authority
                    or task_ref.get("kind") != "work.task"):
                held += 1
                invalid_refs += 1
                continue
            if task_ref["id"] in selected_ids:
                held += 1
                invalid_refs += 1
                continue
            selected_ids.add(task_ref["id"])
            membership_refs.append(task_ref)
            revision = task_ref.get("revision")
            if isinstance(revision, str) and revision:
                valid_refs.append(ResourceRef.from_dict(task_ref))
            elif revision is None:
                unversioned_membership = True
            else:
                held += 1
                invalid_refs += 1
        if unversioned_membership and valid_refs:
            mixed_membership_revisions = True
        pin_source = "project-membership-revisions"
        if unversioned_membership or mixed_membership_revisions:
            close_pins = _completed_close_task_pins(project, project_record.ref, membership_refs)
            if close_pins is None or mixed_membership_revisions or invalid_refs:
                held += len(membership_refs)
                invalid_refs += len(membership_refs)
                valid_refs = []
                rows.extend({"task_ref": ref, "lifecycle": None, "state": "close-pinset-mismatch",
                             "survivor_facets": {"state": "unavailable", "reason": "close-pinset-mismatch"}}
                            for ref in membership_refs)
            else:
                valid_refs = [ResourceRef.from_dict(ref) for ref in close_pins]
                pin_source = "completed-close-request-exact-identity-set"
        projected = consumer.project_identity_fields_for_refs(valid_refs, fields=_TASK_FIELDS,
            max_projection_bytes=_MAX_PROJECTED_BYTES, max_refs=_MAX_TASKS)
        for result in projected:
            ref = result.get("requested_ref")
            if result.get("state") != "available":
                held += 1
                rows.append({"task_ref": ref, "lifecycle": None, "state": result.get("state"),
                             "survivor_facets": {"state": "unavailable", "reason": result.get("state")}})
                continue
            ref = result.get("ref")
            payload = result.get("fields")
            if not isinstance(ref, Mapping) or not isinstance(payload, Mapping):
                held += 1
                rows.append({"task_ref": result.get("requested_ref"), "lifecycle": None, "state": "invalid-projection"})
                continue
            if not _same_ref_identity(payload.get("project_ref"), project_record.ref.to_dict()):
                held += 1
                rows.append({"task_ref": ref, "lifecycle": None, "state": "project-link-mismatch",
                             "survivor_facets": {"state": "unavailable", "reason": "project-link-mismatch"}})
                continue
            assignment_ref = _safe_ref(payload.get("assignment_ref"))
            if assignment_ref is not None:
                assignments.append(assignment_ref)
            facets = _task_survivor_facets(payload, project_record.ref.authority)
            observations.extend(facets["refs"])
            facets_output = {key: value for key, value in facets.items() if key != "refs"}
            rows.append({"task_ref": ref,
                         "lifecycle": _bounded_label(payload.get("lifecycle")),
                         "assignment_ref": assignment_ref,
                         "survivor_facets": facets_output})
        lifecycle_control = project.get("lifecycle_control")
        reconciliation = (lifecycle_control.get("reconciliation")
                          if isinstance(lifecycle_control, Mapping) else None)
        reconciliation_view = _reconciliation_projection(reconciliation, project_record.ref)
        close_request = lifecycle_control.get("close_request") if isinstance(lifecycle_control, Mapping) else None
        terminal_evidence = lifecycle_control.get("terminal_evidence") if isinstance(lifecycle_control, Mapping) else None
        observations.extend(reconciliation_view["survivor_refs"])
        observations.extend(reconciliation_view["observation_refs"])
        assignment_projection = _dedupe_refs_projection(assignments)
        observation_projection = _dedupe_refs_projection(observations)
        unique_assignments = assignment_projection["refs"]
        unique_observations = observation_projection["refs"]
        task_inventory_complete = (project_task_refs_available and declared_task_count <= _MAX_TASKS
                                   and held == 0 and invalid_refs == 0)
        observation_state = _facet_collection_state(rows, reconciliation_view)
        if observation_projection["truncated"] and observation_state == "complete":
            observation_state = "partial"
        observation_complete = observation_state == "complete"
        complete = task_inventory_complete and observation_complete and reconciliation_view["complete"]
        return {"outcome": "read", "view": "lifecycle", "project_ref": project_record.ref.to_dict(),
                "lifecycle": _bounded_label(project.get("lifecycle")),
                "current_lifecycle": _bounded_label(project.get("lifecycle")),
                "lifecycle_control": {
                    "close_request": _close_request_projection(close_request, project_record.ref.authority),
                    "terminal_evidence": _terminal_evidence_projection(terminal_evidence),
                },
                "reconciliation": reconciliation_view,
                "tasks": rows,
                "task_inventory": {"state": "complete" if task_inventory_complete else "partial-or-unknown",
                    "selected_count": len(rows), "declared_count": declared_task_count,
                    "limit": _MAX_TASKS, "held": held,
                    "read_mode": "exact-primary-key-projection", "pin_source": pin_source,
                    "identities_examined": len(valid_refs),
                    "projected_bytes": sum(item.get("projected_bytes", 0) for item in projected),
                    "truncated": truncated},
                "assignment_refs": unique_assignments,
                "assignment_refs_count": assignment_projection["count"],
                "assignment_refs_truncated": assignment_projection["truncated"],
                "observation_subjects": {"state": observation_state,
                    "refs": unique_observations,
                    "count": observation_projection["count"],
                    "truncated": observation_projection["truncated"],
                    "reason": "only explicit task-completion and lifecycle-control survivor fields are projected; global event history is not read"},
                "completeness": "complete" if complete else "partial-or-unknown",
                "complete": complete, "provider_called": False, "writes": 0}

    def _project_context(self, *, root: Any, actor: Any) -> tuple[Any, Any]:
        owner, project_record = self._fixed_project()
        project = project_record.payload
        current_ref = ResourceRef.from_dict(self.service.server.state["orchestrator_assignment_ref"])
        if (root.ref != current_ref or root.principal != actor.actor or root.role != "orchestrator"
                or root.scope.kind != "wrk.portfolio" or root.status.value == "cancelled"):
            raise PermissionError("retention read root is stale or foreign")
        join = ((project.get("metadata") or {}).get("otto_orchestrator") or {})
        joined_ref = join.get("assignment_ref")
        joined_project = join.get("project_ref")
        joined_portfolio = join.get("portfolio_ref")
        if (not isinstance(joined_ref, Mapping)
                or any(joined_ref.get(key) != root.ref.to_dict().get(key)
                       for key in ("authority", "kind", "id", "revision"))
                or join.get("generation") != root.generation
                or not _same_ref_identity(joined_project, project_record.ref.to_dict())
                or not _same_ref_identity(joined_portfolio, root.scope.to_dict())
                or actor != owner.owner_actor):
            raise PermissionError("fixed Usage project is not joined to the exact current root")
        return owner, project_record

    def _storage(self) -> Mapping[str, Any]:
        receipt = self.storage_receipt
        if not isinstance(receipt, Mapping):
            return {"outcome": "unavailable", "view": "storage", "complete": False,
                    "currentness": "not-revalidated", "provider_called": False, "writes": 0,
                    "reason": "no trusted bounded storage observation was injected"}
        # Only explicitly retained facts cross this boundary. In particular,
        # absent source and custody details remain absent/unknown.
        if receipt.get("schema") == "otto.closed-storage-diagnostic-receipt.v1":
            return self._closed_storage(receipt)
        allowed = ("schema", "at", "outcome", "exit_status", "provider_called",
                   "helper_record_mutation_authority", "capacity_fit",
                   "complete_storage_diagnostic", "observed_free_before_bytes",
                   "observed_free_low_water_bytes", "physical_footprint_sample",
                   "sample_ref", "partial_log_ref", "free_after_bytes", "next_action")
        projected = {}
        for key in allowed:
            if key not in receipt:
                continue
            value = receipt[key]
            if key in {"sample_ref", "partial_log_ref"} and isinstance(value, str):
                projected["sample_locator" if key == "sample_ref" else "partial_log_locator"] = value[:512]
            elif type(value) in {int, bool}:
                projected[key] = value
            elif isinstance(value, str):
                projected[key] = value[:512]
        valid = (projected.get("schema") == "otto.owner-storage-diagnostic-partial.v1"
                 and projected.get("complete_storage_diagnostic") is False)
        if not valid:
            return {"outcome": "unavailable", "view": "storage", "complete": False,
                    "currentness": "not-revalidated", "provider_called": False, "writes": 0,
                    "reason": "injected storage receipt does not match the bounded partial schema"}
        return {"outcome": "partial", "view": "storage", "receipt": projected,
                "source": "not-recorded", "custody": "not-established-by-this-receipt",
                "currentness": "not-revalidated", "complete": False,
                "capacity_fit": projected.get("capacity_fit", "unavailable"),
                "provider_called": False, "writes": 0}

    def _closed_storage(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        observed_at = receipt.get("observed_at")
        source_commit = receipt.get("source_commit")
        custody = receipt.get("custody")
        diagnostics = receipt.get("diagnostics")
        if (not isinstance(observed_at, str) or len(observed_at) > 128
                or not isinstance(source_commit, str) or not source_commit.strip() or len(source_commit) > 128
                or not isinstance(custody, Mapping) or len(custody) > 16
                or not isinstance(diagnostics, Mapping) or not diagnostics or len(diagnostics) > 32):
            return {"outcome": "unavailable", "view": "storage", "complete": False,
                    "currentness": "not-revalidated", "provider_called": False, "writes": 0,
                    "reason": "closed storage receipt lacks bounded source, custody or diagnostics"}
        stages_source = diagnostics.get("stages")
        if not isinstance(stages_source, Mapping) or not stages_source or len(stages_source) > 16:
            return {"outcome": "unavailable", "view": "storage", "complete": False,
                    "currentness": "not-revalidated", "provider_called": False, "writes": 0,
                    "reason": "closed storage receipt has no bounded stage summaries"}
        stages = {}
        for name, raw_stage in stages_source.items():
            if (not isinstance(name, str) or not name or len(name) > 64
                    or not all(char.isalnum() or char in "-_" for char in name)
                    or not isinstance(raw_stage, Mapping) or len(raw_stage) > 12):
                continue
            state = raw_stage.get("state")
            stages[name] = {"state": state[:64] if isinstance(state, str) else "unknown",
                            "reason": _bounded_label(raw_stage.get("reason"))}
        work = diagnostics.get("work")
        work_view = ({"state": _bounded_label(work.get("state")) or "unknown",
                      "reason": _bounded_label(work.get("reason"))}
                     if isinstance(work, Mapping) else {"state": "unknown", "reason": None})
        custody_view = {}
        for key in ("ordinary_exit_status", "store_closed", "owner_alive", "supervisor_alive"):
            value = custody.get(key)
            if type(value) in {int, bool}:
                custody_view[key] = value
        for key, value in custody.items():
            if not isinstance(key, str) or len(key) > 64:
                continue
            if key.endswith("_ref"):
                ref = _object_ref(value)
                if ref is not None:
                    custody_view[key] = ref
            elif key.endswith("_sha256") and isinstance(value, str) and len(value) == 64 \
                    and all(char in "0123456789abcdef" for char in value.lower()):
                custody_view[key] = value.lower()
        records_modified = diagnostics.get("records_modified")
        diagnostics_view = {"work": work_view, "stages": stages,
                            "records_modified": records_modified if type(records_modified) is bool else None}
        for key in ("source_bytes", "file_allocated_bytes", "page_size", "page_count", "freelist_pages", "freelist_bytes"):
            value = diagnostics.get(key)
            if type(value) is int and 0 <= value <= 10**15:
                diagnostics_view[key] = value
        for name in ("tables", "payload_groups"):
            values = diagnostics.get(name)
            if isinstance(values, (list, tuple)):
                summaries = []
                for item in values[:64]:
                    if not isinstance(item, Mapping):
                        continue
                    summary = {}
                    for key in ("name", "table", "state"):
                        if isinstance(item.get(key), str):
                            summary[key] = item[key][:64]
                    for key, value in item.items():
                        if isinstance(key, str) and type(value) is int and 0 <= value <= 10**15:
                            summary[key] = value
                    summaries.append(summary)
                diagnostics_view[name] = {"items": summaries, "count": len(values), "truncated": len(values) > 64}
            elif isinstance(values, Mapping):
                metrics = {key: value for key, value in values.items()
                           if isinstance(key, str) and len(key) <= 64 and type(value) is int
                           and 0 <= value <= 10**15}
                state = values.get("state")
                if isinstance(state, str):
                    metrics["state"] = state[:64]
                diagnostics_view[name] = metrics
        page_allocation = diagnostics.get("page_allocation")
        if isinstance(page_allocation, Mapping):
            diagnostics_view["page_allocation"] = {
                key: value for key, value in page_allocation.items()
                if isinstance(key, str) and len(key) <= 64
                and (isinstance(value, str) and len(value) <= 64
                     or type(value) is int and 0 <= value <= 10**15
                     or type(value) is bool)}
        physical_cow = diagnostics.get("physical_unique_CoW_bytes")
        if isinstance(physical_cow, str):
            diagnostics_view["physical_unique_CoW_bytes"] = physical_cow[:64]
        custody_ok = (custody_view.get("ordinary_exit_status") == 0
                      and custody_view.get("store_closed") is True
                      and custody_view.get("owner_alive") is False
                      and custody_view.get("supervisor_alive") is False)
        stages_ok = (all(stages.get(name, {}).get("state") == "complete"
                         for name in ("pages", "tables", "payload_groups"))
                     and stages.get("allocation", {}).get("state") in {"complete", "available"})
        required_stages = {"pages", "tables", "payload_groups", "allocation"}
        complete = (work_view["state"] == "complete" and custody_ok
                    and required_stages.issubset(stages)
                    and stages_ok and diagnostics_view["records_modified"] is False)
        return {"outcome": "read" if complete else "partial", "view": "storage",
                "observed_at": observed_at, "source_commit": source_commit[:128],
                "custody": custody_view or "not-recorded", "diagnostics": diagnostics_view,
                "complete": complete, "currentness": "retained-observation-not-revalidated",
                "capacity_fit": "unavailable",
                "provider_called": False,
                "writes": 0}

    def _preview(self, handle: Mapping[str, Any], *, root: Any, actor: Any, request_key: Any) -> Mapping[str, Any]:
        cutoff, cursor, limit = handle.get("cutoff"), handle.get("cursor"), handle.get("limit")
        if (not isinstance(cutoff, str) or not cutoff.strip() or len(cutoff) > 128
                or not isinstance(cursor, str) or len(cursor) > _MAX_CURSOR
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError("reclaim preview bounds are invalid")
        if self.evidence_handler is None or not callable(getattr(self.evidence_handler, "reclaim_preview", None)):
            return {"outcome": "unavailable", "view": "reclaim-preview", "complete": False,
                    "provider_called": False, "deletion_count": 0,
                    "reason": "existing evidence preview handler is not injected"}
        owner, project = self._project_context(root=root, actor=actor)
        if actor != owner.owner_actor:
            raise PermissionError("reclaim preview requires the authenticated service owner")
        if not _has_current_reconciliation(project.payload):
            return {"outcome": "held", "view": "reclaim-preview", "complete": False,
                    "provider_called": False, "deletion_count": 0, "writes": 0,
                    "reason": "fixed Usage project is not completed with current reconciled lifecycle control"}
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 256:
            raise ValueError("reclaim preview requires a stable request key")
        binding = self._install_dependency_resolver(root=root, actor=actor)
        try:
            result = self.evidence_handler.reclaim_preview(project.ref, actor=actor,
                logical_request_key="retention-read:" + request_key, cutoff=cutoff,
                cursor=cursor, limit=limit)
        finally:
            if binding is not None:
                engine, prior = binding
                engine._resolve_dependencies = prior
        items = []
        invalid_items = 0
        result_items = result.get("items", ())
        if not isinstance(result_items, (list, tuple)) or len(result_items) > limit:
            return {"outcome": "partial", "view": "reclaim-preview", "complete": False,
                    "project_ref": project.ref.to_dict(), "cutoff": cutoff, "cursor": cursor,
                    "limit": limit, "items": [], "provider_called": False, "deletion_count": 0,
                    "writes": 0, "reason": "Evidence preview returned an invalid bounded page"}
        for item in result_items:
            if not isinstance(item, Mapping):
                invalid_items += 1
                continue
            row = {key: item[key] for key in ("byte_length", "eligible", "hold", "availability",
                                                "storage_location", "captured_at", "format")
                   if key in item and (key != "byte_length" or type(item[key]) is int and item[key] >= 0)
                   and (key != "eligible" or type(item[key]) is bool)
                   and (key not in {"hold", "availability", "storage_location", "captured_at", "format"}
                        or isinstance(item[key], str))}
            reference = _object_ref(item.get("reference"))
            if reference is not None:
                row["reference"] = reference
            current_head = _object_ref(item.get("current_head"))
            if current_head is not None:
                row["current_head"] = current_head
            digest = item.get("byte_digest")
            if isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
                row["byte_digest"] = digest
            provenance = _bounded_provenance(item.get("provenance", item.get("origin")))
            if provenance is not None:
                row["provenance"] = provenance
            work = _bounded_io_work(item.get("io_work"))
            if work is not None:
                row["io_work"] = work
            if (reference is not None and reference.get("kind") == "dat.content.document"
                    and current_head is not None and _same_ref_identity(reference, current_head)
                    and "revision" in current_head and "byte_digest" in row
                    and isinstance(row.get("storage_location"), str)
                    and isinstance(provenance, Mapping)
                    and _same_ref_identity(provenance.get("project_ref"), project.ref.to_dict())):
                row["material_class"] = "managed-evidence"
            items.append(row)
        selection_ref = _object_ref(result.get("selection_ref"))
        selection = result.get("selection") if isinstance(result.get("selection"), Mapping) else {}
        eligible_bytes = sum(item.get("byte_length", 0) for item in items
                             if item.get("eligible") is True and item.get("material_class") == "managed-evidence")
        held_bytes = sum(item.get("byte_length", 0) for item in items if item.get("eligible") is not True)
        hold_reasons = {}
        for item in items:
            if item.get("eligible") is not True:
                hold = item.get("hold") if isinstance(item.get("hold"), str) else "unknown"
                hold_reasons[hold] = hold_reasons.get(hold, 0) + 1
        page_work = _bounded_io_work(result.get("io_work"))
        selection_project = _object_ref(selection.get("project_ref"))
        next_cursor_raw = result.get("next_cursor")
        next_cursor = _bounded_cursor(next_cursor_raw)
        cursor_valid = next_cursor_raw is None or next_cursor is not None
        selection_digest = _bounded_digest(selection.get("selection_digest"))
        selection_pinned = (selection_ref is not None and isinstance(selection_ref.get("revision"), str)
                            and selection_digest is not None
                            and selection_project is not None
                            and _same_ref_identity(selection_project, project.ref.to_dict()))
        page_valid = cursor_valid and invalid_items == 0 and selection_pinned
        return {"outcome": result.get("outcome", "previewed"), "view": "reclaim-preview",
                "project_ref": project.ref.to_dict(), "selection_ref": selection_ref,
                "selection_digest": selection_digest,
                "cutoff": cutoff, "cursor": cursor, "limit": limit,
                "next_cursor": next_cursor, "items": items,
                "complete": next_cursor_raw is None and page_valid,
                "page_state": "bounded-page" if page_valid else "partial-or-unknown",
                "coverage_state": "complete" if next_cursor_raw is None and page_valid
                    else "continuation-available" if next_cursor is not None and page_valid
                    else "unknown",
                "invalid_item_count": invalid_items,
                "page_summary": {"item_count": len(items), "eligible_managed_bytes": eligible_bytes,
                    "held_bytes": held_bytes, "hold_reason_counts": hold_reasons,
                    "eligible_unique_managed_bytes": result.get("eligible_unique_managed_bytes")
                    if type(result.get("eligible_unique_managed_bytes")) is int else None,
                    "selection_project_ref": selection_project,
                    "selection_project_matches": bool(selection_project and
                        _same_ref_identity(selection_project, project.ref.to_dict())),
                    "io_work": page_work},
                "read_only": False, "canonical_selection_recorded": True,
                "provider_called": False, "deletion_count": 0,
                "managed_bytes_removed": result.get("managed_bytes_removed", 0),
                "writes": 1 if result.get("outcome") == "previewed" else 0,
                "writes_meaning": "canonical selection receipt; replay returns the existing receipt"}

    def _install_dependency_resolver(self, *, root: Any, actor: Any):
        """Bind one preview to the authenticated owner read composition.

        Evidence already has a private bounded resolver hook.  The public
        facade cannot serialize a Python callback, so install it transiently
        on the owner-local engine for this authenticated preview only.  A
        consumer or foreign process therefore remains fail-closed.
        """
        try:
            engine = owner_local_engine(self.evidence_handler)
        except (AttributeError, CommandTransportClosed, WriterAuthorityDenied):
            return None
        prior = getattr(engine, "_resolve_dependencies", None)
        engine._resolve_dependencies = lambda exact, project: self._resolve_dependencies(
            exact, project, root=root, actor=actor)
        return engine, prior

    def _resolve_dependencies(self, exact: Any, project: Any, *, root: Any, actor: Any) -> Mapping[str, Any]:
        """Resolve only the exact retained item's linked dependency graph.

        This is deliberately a finite join: target Evidence.status, the fixed
        project, one origin task/attempt, and the bounded survivor refs named
        by that task.  Missing, stale, foreign, malformed, or oversize records
        remain unknown; no global history or payload scan is attempted.
        """
        try:
            owner, project_record = self._project_context(root=root, actor=actor)
            expected_project = project_record.ref
            requested_project = project if isinstance(project, ResourceRef) else ResourceRef.from_dict(project)
            if requested_project != expected_project and not _same_ref_identity(requested_project, expected_project.to_dict()):
                return {"complete": False, "holds": ("dependency-unknown",)}
            evidence = self.evidence_handler.status(exact, actor=actor)
            manifest = evidence.get("manifest") if isinstance(evidence, Mapping) else None
            if not isinstance(manifest, Mapping):
                return {"complete": False, "holds": ("dependency-unknown",)}
            origin = manifest.get("origin")
            if not isinstance(origin, Mapping) or not _same_ref_identity(origin.get("project_ref"), expected_project.to_dict()):
                return {"complete": False, "holds": ("dependency-unknown",)}
            task = _dependency_ref(origin.get("task_ref"), expected_project.authority, "work.task")
            attempt = _dependency_ref(origin.get("attempt_ref"), expected_project.authority, "work.attempt")
            if task is None and attempt is None:
                return {"complete": False, "holds": ("dependency-unknown",)}
            # An attempt without its exact originating task is not enough to
            # establish ownership.  Never dereference a missing task while
            # trying to explain an attempt-only origin.
            if attempt is not None and task is None:
                return {"complete": False, "holds": ("dependency-unknown",)}
            current_project = project_record.payload
            project_hold = _dependency_state(current_project, require_terminal=True)
            if project_hold is not None:
                return {"complete": True, "holds": (project_hold,)} if project_hold == "in-flight-recovery" else {"complete": False, "holds": (project_hold,)}
            refs = [ref for ref in (task, attempt) if ref is not None]
            fields = _dependency_fields()
            task_rows = owner.store.consumer().project_identity_fields_for_refs(
                refs, fields=fields, max_projection_bytes=_MAX_PROJECTED_BYTES, max_refs=8)
            by_requested = {tuple(row.get("requested_ref", {}).get(key) for key in ("authority", "kind", "id", "revision")): row
                            for row in task_rows if isinstance(row, Mapping)}
            survivor_refs = []
            for ref in refs:
                row = by_requested.get((ref.authority, ref.kind, ref.id, ref.revision))
                if not isinstance(row, Mapping) or row.get("state") != "available":
                    return {"complete": False, "holds": ("dependency-unknown",)}
                projected = row.get("fields")
                if not isinstance(projected, Mapping):
                    return {"complete": False, "holds": ("dependency-unknown",)}
                if not _same_ref_identity(projected.get("project_ref"), expected_project.to_dict()):
                    return {"complete": False, "holds": ("dependency-unknown",)}
                linked_task = _dependency_ref(projected.get("task_ref"), expected_project.authority, "work.task")
                if ref.kind == "work.attempt" and linked_task is not None and not _same_ref_identity(linked_task.to_dict(), task.to_dict()):
                    return {"complete": False, "holds": ("dependency-unknown",)}
                state = _dependency_state(projected, require_terminal=True)
                if state is not None:
                    return {"complete": True, "holds": (state,)} if state == "in-flight-recovery" else {"complete": False, "holds": (state,)}
                # A completed task must carry the manager's canonical result
                # candidate.  result_ref and attempt_ref remain nullable
                # optional fields, while candidate_ref is the producer proof.
                if ref.kind == "work.task":
                    candidate = _dependency_ref(projected.get("completion_candidate_ref"), expected_project.authority, "wrk.result")
                    assignment = _dependency_ref(projected.get("completion_assignment_ref"), expected_project.authority, "wrk.assignment")
                    completion_project = _dependency_ref(projected.get("completion_project_ref"), expected_project.authority, "work.project")
                    completion_task = _dependency_ref(projected.get("completion_task_ref"), expected_project.authority, "work.task")
                    if (candidate is None or assignment is None or completion_project is None
                            or completion_task is None
                            or not _same_ref_identity(completion_project.to_dict(), expected_project.to_dict())
                            or not _same_ref_identity(completion_task.to_dict(), task.to_dict())):
                        return {"complete": False, "holds": ("dependency-unknown",)}
                row_refs = _survivor_refs(projected, row.get("present"), expected_project.authority)
                if row_refs is None:
                    return {"complete": False, "holds": ("dependency-unknown",)}
                survivor_refs.extend(row_refs)
            unique_survivors = []
            seen = set()
            for ref in survivor_refs:
                key = (ref.authority, ref.kind, ref.id, ref.revision)
                if key not in seen:
                    seen.add(key)
                    unique_survivors.append(ref)
            if not unique_survivors:
                return {"complete": False, "holds": ("dependency-unknown",)}
            survivor_rows = owner.store.consumer().project_identity_fields_for_refs(
                unique_survivors, fields=fields, max_projection_bytes=_MAX_PROJECTED_BYTES, max_refs=_MAX_TASKS)
            if len(survivor_rows) != len(unique_survivors):
                return {"complete": False, "holds": ("dependency-unknown",)}
            candidate_refs = {tuple(ref.to_dict().get(key) for key in ("authority", "kind", "id", "revision"))
                              for ref in survivor_refs if ref.kind == "wrk.result"}
            if not candidate_refs:
                return {"complete": False, "holds": ("dependency-unknown",)}
            for row in survivor_rows:
                if row.get("state") != "available" or not isinstance(row.get("fields"), Mapping):
                    return {"complete": False, "holds": ("dependency-unknown",)}
                requested = row.get("requested_ref") or {}
                fields = row["fields"]
                if requested.get("kind") == "wrk.result":
                    if not _canonical_candidate_provenance(fields, row.get("present"), expected_project, task):
                        return {"complete": False, "holds": ("dependency-unknown",)}
                    state = _dependency_state(fields, require_terminal=False)
                    # Canonical owner observations have no lifecycle column;
                    # their exact assignment/project/task provenance is the
                    # terminal proof.  Explicit bad states remain held.
                    if state == "dependency-unknown" and not any(
                            fields.get(name) is not None for name in _DEPENDENCY_STATE_FIELDS):
                        state = None
                elif requested.get("kind") == "dat.content.document":
                    if not _evidence_origin_matches(self.evidence_handler, row.get("requested_ref"),
                                                    expected_project, task, actor):
                        return {"complete": False, "holds": ("dependency-unknown",)}
                    state = None
                else:
                    state = _dependency_state(fields, require_terminal=False)
                if state is not None:
                    return {"complete": True, "holds": (state,)} if state == "in-flight-recovery" else {"complete": False, "holds": (state,)}
            return {"complete": True, "holds": (), "linked_refs_read": len(refs) + len(unique_survivors)}
        except (KeyError, TypeError, ValueError, PermissionError):
            return {"complete": False, "holds": ("dependency-unknown",)}

def _dependency_fields() -> Mapping[str, tuple[str, ...]]:
    return {
        "project_ref": ("project_ref",), "task_ref": ("task_ref",),
        "lifecycle": ("lifecycle",), "status": ("status",), "state": ("state",),
        "outcome": ("outcome",), "completion_state": ("completion_state",),
        "stop_state": ("stop_state",), "in_flight": ("in_flight",),
        "pending_recovery": ("pending_recovery",),
        "record_type": ("record_type",), "observation_kind": ("observation_kind",),
        "assignment_ref": ("assignment",), "value_project_ref": ("value", "project_ref"),
        "value_task_ref": ("value", "task_ref"), "value_assignment_ref": ("value", "assignment_ref"),
        "completion_candidate_ref": ("completion", "candidate_ref"),
        "completion_assignment_ref": ("completion", "assignment_ref"),
        "completion_project_ref": ("completion", "project_ref"),
        "completion_task_ref": ("completion", "task_ref"),
        "completion_result_ref": ("completion", "result_ref"),
        "completion_evidence_refs": ("completion", "evidence_refs"),
        "completion_gate_refs": ("completion", "gate_refs"),
        "completion_source_refs": ("completion", "source_refs"),
        "effect_result_ref": ("effect_packet", "result_ref"),
        "effect_evidence_refs": ("effect_packet", "evidence_refs"),
        "effect_gate_refs": ("effect_packet", "gate_refs"),
        "effect_source_refs": ("effect_packet", "source_refs"),
        "settlement_result_ref": ("settlement", "result_ref"),
        "settlement_evidence_refs": ("settlement", "evidence_refs"),
        "settlement_gate_refs": ("settlement", "gate_refs"),
        "settlement_source_refs": ("settlement", "source_refs"),
    }


def _dependency_ref(value: Any, authority: str, kind: str) -> ResourceRef | None:
    ref = _safe_ref(value, authority)
    if ref is None or ref.get("kind") != kind:
        return None
    try:
        return ResourceRef.from_dict(ref)
    except (TypeError, ValueError):
        return None


_DEPENDENCY_STATE_FIELDS = ("lifecycle", "status", "state", "outcome", "completion_state", "stop_state")


def _dependency_state(fields: Mapping[str, Any], *, require_terminal: bool) -> str | None:
    if not isinstance(fields, Mapping):
        return "dependency-unknown"
    if fields.get("in_flight") is True or fields.get("pending_recovery") is True:
        return "in-flight-recovery"
    active = {"active", "assigned", "in-flight", "in_progress", "pending", "queued", "running", "started"}
    terminal = {"completed", "succeeded", "settled", "accepted", "released", "done", "purged"}
    unknown = {"unknown", "failed", "failure", "error", "rejected", "aborted", "cancelled", "canceled", "ambiguous", "incomplete"}
    values = [fields.get(name) for name in _DEPENDENCY_STATE_FIELDS]
    text = {value for value in values if isinstance(value, str)}
    if text & active:
        return "in-flight-recovery"
    if text & unknown:
        return "dependency-unknown"
    # ``require_terminal=False`` only relaxes the caller's need to explain
    # an otherwise terminal row; it never turns an unrecognised state into a
    # successful dependency proof.
    if not text.intersection(terminal):
        return "dependency-unknown"
    return None


_LINKED_SINGLE_FIELDS = (
    "completion_candidate_ref", "completion_result_ref", "completion_attempt_ref",
    "effect_candidate_ref", "effect_result_ref", "effect_attempt_ref",
    "settlement_candidate_ref", "settlement_result_ref", "settlement_attempt_ref",
)
_LINKED_LIST_FIELDS = (
    "completion_evidence_refs", "completion_gate_refs", "completion_source_refs",
    "effect_evidence_refs", "effect_gate_refs", "effect_source_refs",
    "settlement_evidence_refs", "settlement_gate_refs", "settlement_source_refs",
)


def _survivor_refs(fields: Mapping[str, Any], present: Mapping[str, Any] | None,
                   authority: str) -> list[ResourceRef] | None:
    """Collect named links strictly; malformed links poison the join."""
    if not isinstance(fields, Mapping) or not isinstance(present, Mapping):
        return None
    result = []
    for name in _LINKED_SINGLE_FIELDS:
        if present.get(name) not in (True, 1):
            continue
        value = fields.get(name)
        # Completion result/attempt are intentionally nullable optional pins.
        if value is None and name in {"completion_result_ref", "completion_attempt_ref"}:
            continue
        ref = _safe_ref(value, authority)
        if ref is None:
            return None
        try:
            parsed = ResourceRef.from_dict(ref)
        except (TypeError, ValueError):
            return None
        if parsed.kind not in {"work.project", "work.task", "work.attempt"}:
            result.append(parsed)
    for name in _LINKED_LIST_FIELDS:
        if present.get(name) not in (True, 1):
            continue
        values = fields.get(name)
        if not isinstance(values, (list, tuple)) or len(values) > _TASK_LIMIT:
            return None
        for value in values:
            ref = _safe_ref(value, authority)
            if ref is None:
                return None
            try:
                parsed = ResourceRef.from_dict(ref)
            except (TypeError, ValueError):
                return None
            if parsed.kind not in {"work.project", "work.task", "work.attempt"}:
                result.append(parsed)
    return result


def _canonical_candidate_provenance(fields: Mapping[str, Any], present: Mapping[str, Any] | None,
                                    project: ResourceRef, task: ResourceRef) -> bool:
    if not isinstance(present, Mapping):
        return False
    if (fields.get("record_type") != "work.observation"
            or fields.get("observation_kind") != "result"):
        return False
    assignment = _safe_ref(fields.get("assignment_ref"), project.authority)
    value_assignment = _safe_ref(fields.get("value_assignment_ref"), project.authority)
    value_project = _safe_ref(fields.get("value_project_ref"), project.authority)
    value_task = _safe_ref(fields.get("value_task_ref"), project.authority)
    return (assignment is not None and assignment.get("kind") == "wrk.assignment"
            and value_assignment is not None and value_assignment.get("kind") == "wrk.assignment"
            and _same_ref_identity(assignment, value_assignment)
            and value_project is not None and value_project.get("kind") == "work.project"
            and _same_ref_identity(value_project, project.to_dict())
            and value_task is not None and value_task.get("kind") == "work.task"
            and _same_ref_identity(value_task, task.to_dict()))


def _evidence_origin_matches(handler: Any, ref: Mapping[str, Any] | None,
                             project: ResourceRef, task: ResourceRef, actor: Any) -> bool:
    try:
        if not isinstance(ref, Mapping) or ref.get("kind") != "dat.content.document":
            return False
        status = handler.status(ResourceRef.from_dict(ref), actor=actor)
        manifest = status.get("manifest") if isinstance(status, Mapping) else None
        origin = manifest.get("origin") if isinstance(manifest, Mapping) else None
        return (isinstance(origin, Mapping)
                and _same_ref_identity(origin.get("project_ref"), project.to_dict())
                and _same_ref_identity(origin.get("task_ref"), task.to_dict()))
    except (KeyError, TypeError, ValueError, PermissionError):
        return False


def _bounded_label(value: Any) -> str | None:
    return value[:128] if isinstance(value, str) else None


def _bounded_cursor(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) <= _MAX_CURSOR else None


def _bounded_digest(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value) else None


def _bounded_provenance(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result = {}
    for name in ("project_ref", "task_ref", "attempt_ref", "source_ref"):
        ref = _safe_ref(value.get(name))
        if ref is not None:
            result[name] = ref
    for name in ("canonical_transfer", "in_flight", "pending_recovery", "dependency_unknown"):
        if type(value.get(name)) is bool:
            result[name] = value[name]
    return result or None


def _bounded_io_work(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    work = {}
    for name, item in list(value.items())[:32]:
        if not isinstance(name, str) or len(name) > 64:
            continue
        if type(item) is int and 0 <= item <= 10**12:
            work[name] = item
        elif type(item) is bool:
            work[name] = item
        elif isinstance(item, str) and len(item) <= 128:
            work[name] = item
    return work or None


def _has_current_reconciliation(project_payload: Mapping[str, Any]) -> bool:
    lifecycle_control = project_payload.get("lifecycle_control")
    reconciliation = lifecycle_control.get("reconciliation") if isinstance(lifecycle_control, Mapping) else None
    return (project_payload.get("lifecycle") == "completed" and isinstance(reconciliation, Mapping)
            and reconciliation.get("status") == "reconciled")


def _safe_ref(value: Any, authority: str | None = None) -> Mapping[str, Any] | None:
    if (not isinstance(value, Mapping)
            or not all(isinstance(value.get(k), str) and value.get(k) and len(value[k]) <= 256
                       for k in ("authority", "kind", "id"))
            or authority is not None and value.get("authority") != authority):
        return None
    if "revision" in value and value["revision"] is not None and (
            not isinstance(value["revision"], str) or len(value["revision"]) > 256):
        return None
    return {key: value[key] for key in ("authority", "kind", "id", "revision") if key in value}


def _same_ref_identity(left: Any, right: Any) -> bool:
    left_ref, right_ref = _safe_ref(left), _safe_ref(right)
    return (left_ref is not None and right_ref is not None
            and all(left_ref.get(key) == right_ref.get(key) for key in ("authority", "kind", "id")))


def _safe_ref_list(value: Any, limit: int, authority: str | None = None) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [ref for item in value[:limit] if (ref := _safe_ref(item, authority)) is not None]


def _bounded_refs_projection(value: Any, limit: int, authority: str | None = None) -> Mapping[str, Any]:
    if value is None:
        return {"state": "unavailable", "refs": [], "count": None, "truncated": False}
    if not isinstance(value, (list, tuple)):
        return {"state": "invalid", "refs": [], "count": None, "truncated": False}
    refs = _safe_ref_list(value, limit, authority)
    truncated = len(value) > limit
    invalid = len(value[:limit]) - len(refs)
    return {"state": "available" if not truncated and not invalid else "partial",
            "refs": refs, "count": len(value), "valid_count": len(refs), "invalid_count": invalid,
            "truncated": truncated}


_SURVIVOR_SINGLE_FIELDS = ("candidate_ref", "result_ref", "assignment_ref", "attempt_ref")
_SURVIVOR_LIST_FIELDS = ("evidence_refs", "gate_refs", "source_refs")


def _task_survivor_facets(payload: Mapping[str, Any], authority: str) -> Mapping[str, Any]:
    groups = {}
    all_refs = []
    for prefix in ("completion", "effect", "settlement"):
        refs = []
        fields = {}
        present = 0
        invalid = 0
        for name in _SURVIVOR_SINGLE_FIELDS:
            key = f"{prefix}_{name}"
            if key not in payload:
                fields[name] = {"state": "unavailable", "ref": None}
                continue
            present += 1
            raw_ref = payload.get(key)
            # The canonical work-completion producer explicitly stores result
            # and attempt as nullable optional fields. Null means no survivor
            # was supplied, not a malformed or foreign pin.
            if raw_ref is None and prefix == "completion" and name in {"result_ref", "attempt_ref"}:
                fields[name] = {"state": "unavailable", "ref": None}
                continue
            ref = _safe_ref(raw_ref, authority)
            if ref is None:
                fields[name] = {"state": "invalid", "ref": None}
                invalid += 1
            else:
                fields[name] = {"state": "available", "ref": ref}
                refs.append(ref)
        for name in _SURVIVOR_LIST_FIELDS:
            key = f"{prefix}_{name}"
            if key not in payload:
                fields[name] = {"state": "unavailable", "refs": [], "count": None,
                                "valid_count": 0, "invalid_count": 0, "truncated": False}
                continue
            present += 1
            projected = _bounded_refs_projection(payload.get(key), _TASK_LIMIT, authority)
            fields[name] = projected
            refs.extend(projected["refs"])
            if projected["state"] not in {"available"}:
                invalid += 1
        state = "unavailable" if present == 0 else "partial" if invalid else "available"
        required = ("candidate_ref", "evidence_refs", "gate_refs", "assignment_ref")
        required_available = all(fields[name]["state"] == "available" for name in required)
        # Only canonical completion can establish task completion survivor
        # coverage. effect_packet and settlement are optional alternate facets.
        groups[prefix] = {"state": state,
                          "complete": prefix == "completion" and required_available and invalid == 0,
                          "fields": fields, "refs": _dedupe_refs(refs)}
        all_refs.extend(refs)
    return {"state": "available" if any(group["state"] == "available" for group in groups.values())
            else "partial" if any(group["state"] == "partial" for group in groups.values()) else "unavailable",
            "groups": groups, "refs": all_refs,
            "global_event_history_read": False}


def _bounded_shared_records(value: Any, limit: int = _TASK_LIMIT) -> Mapping[str, Any]:
    if not isinstance(value, list):
        return {"state": "unavailable", "records": [], "count": None, "truncated": False}
    records = []
    invalid = 0
    for item in value[:limit]:
        if not isinstance(item, Mapping):
            invalid += 1
            continue
        schedule_id = item.get("schedule_id")
        status = item.get("status")
        if not isinstance(schedule_id, str) or len(schedule_id) > 256 or not isinstance(status, str):
            invalid += 1
            continue
        row = {"schedule_id": schedule_id, "status": status[:64]}
        for name in ("assignment_ref", "project_ref", "record_ref"):
            ref = _safe_ref(item.get(name))
            if ref is not None:
                row[name] = ref
        records.append(row)
    truncated = len(value) > limit
    return {"state": "available" if not invalid and not truncated else "partial",
            "records": records, "count": len(value), "invalid_count": invalid, "truncated": truncated}


def _bounded_coverage(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unavailable", "fields": {}}
    fields = {}
    for key, item in list(value.items())[:32]:
        if isinstance(key, str) and len(key) <= 64 and (type(item) in {str, int, bool} or item is None):
            fields[key] = item[:128] if isinstance(item, str) else item
    return {"state": "available" if len(fields) == len(value) else "partial", "fields": fields}


def _bounded_string_list(value: Any, limit: int = _TASK_LIMIT) -> Mapping[str, Any]:
    if not isinstance(value, list):
        return {"state": "unavailable", "values": [], "count": None, "invalid_count": None,
                "truncated": False}
    values = [item[:256] for item in value[:limit] if isinstance(item, str) and item and len(item) <= 256]
    invalid = min(len(value), limit) - len(values)
    truncated = len(value) > limit
    return {"state": "available" if invalid == 0 and not truncated else "partial",
            "values": values, "count": len(value), "invalid_count": invalid, "truncated": truncated}


def _close_request_projection(value: Any, authority: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unavailable", "refs": [], "generation": None}
    names = ("report_ref", "project_ref", "manager_assignment", "receipt")
    refs = [_safe_ref(value.get(name), authority) for name in names]
    refs = [ref for ref in refs if ref is not None]
    tasks = _bounded_refs_projection(value.get("task_refs"), _TASK_LIMIT, authority)
    return {"state": "available" if refs and tasks["state"] == "available" else "partial",
            "refs": refs, "task_refs": tasks, "generation": value.get("generation")
            if type(value.get("generation")) is int else None}


def _completed_close_task_pins(project: Mapping[str, Any], project_ref: ResourceRef,
                               memberships: list[Mapping[str, Any]]) -> list[Mapping[str, Any]] | None:
    """Use close-request revisions only when they pin this exact completed task set."""
    lifecycle_control = project.get("lifecycle_control")
    close_request = (lifecycle_control.get("close_request")
                     if isinstance(lifecycle_control, Mapping) else None)
    if project.get("lifecycle") != "completed" or not isinstance(close_request, Mapping):
        return None
    close_project = _safe_ref(close_request.get("project_ref"), project_ref.authority)
    close_manager = _safe_ref(close_request.get("manager_assignment"), project_ref.authority)
    close_report = _safe_ref(close_request.get("report_ref"), project_ref.authority)
    generation = close_request.get("generation")
    if (not _same_ref_identity(close_project, project_ref.to_dict())
            or close_manager is None or close_manager.get("kind") != "wrk.assignment"
            or not isinstance(close_manager.get("revision"), str) or not close_manager["revision"]
            or close_report is None or close_report.get("kind") != "wrk.report"
            or type(generation) is not int or generation < 1):
        return None
    pinned = _bounded_refs_projection(close_request.get("task_refs"), _MAX_TASKS,
                                      project_ref.authority)
    close_refs = pinned.get("refs")
    if (pinned.get("state") != "available" or not isinstance(close_refs, list)
            or len(close_refs) != len(memberships)):
        return None
    if any(ref.get("kind") != "work.task" or not isinstance(ref.get("revision"), str)
           or not ref["revision"] for ref in close_refs):
        return None
    membership_ids = {(ref["authority"], ref["kind"], ref["id"]) for ref in memberships}
    close_ids = {(ref["authority"], ref["kind"], ref["id"]) for ref in close_refs}
    if len(close_ids) != len(close_refs) or close_ids != membership_ids:
        return None
    return close_refs


def _terminal_evidence_projection(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unavailable", "statuses": {}}
    statuses = {}
    for name in ("acceptance", "publication", "remote", "runtime"):
        facet = value.get(name)
        status = facet.get("status") if isinstance(facet, Mapping) else None
        if isinstance(status, str):
            statuses[name] = status[:64]
    return {"state": "available" if len(statuses) == 4 else "partial", "statuses": statuses}


def _object_ref(value: Any) -> Mapping[str, Any] | None:
    if hasattr(value, "result_ref"):
        value = value.result_ref
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return _safe_ref(value)


def _reconciliation_projection(value: Any, project_ref: ResourceRef) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unknown", "complete": False, "survivor_refs": [],
                "survivor_refs_count": None, "survivor_refs_truncated": False,
                "observation_ref": None, "observation_refs": [], "observation": {"state": "unavailable"}}
    authority = project_ref.authority
    survivors = _bounded_refs_projection(value.get("survivor_refs"), _TASK_LIMIT, authority)
    survivor_refs = survivors["refs"]
    observation = value.get("observation") if isinstance(value.get("observation"), Mapping) else None
    coverage = _bounded_coverage(observation.get("coverage")) if observation is not None else {"state": "unavailable", "fields": {}}
    shared = _bounded_shared_records(observation.get("shared_records")) if observation is not None else {"state": "unavailable", "records": [], "count": None, "truncated": False}
    owned = (_bounded_string_list(observation.get("pm_owned_schedule_ids"))
             if observation is not None else {"state": "unavailable", "values": [], "count": None,
                                              "invalid_count": None, "truncated": False})
    ownership_unknown = (observation is None or observation.get("unknown_ownership") is True
                         or observation.get("ownership") == "unknown"
                         or any(record.get("status") == "unknown" for record in shared["records"]))
    coverage_fields = coverage.get("fields", {})
    coverage_matches = (coverage["state"] == "available"
        and coverage_fields.get("authority") == project_ref.authority
        and coverage_fields.get("project_id") == project_ref.id
        and coverage_fields.get("source") in {"complete public Due list",
                                                "complete project-scoped public Due list"}
        and type(coverage_fields.get("record_count")) is int and coverage_fields["record_count"] >= 0)
    shared_count_matches = (shared["state"] == "available" and shared["count"] is not None
        and not ownership_unknown and shared["count"] == coverage_fields.get("record_count"))
    observation_complete = (observation is not None and observation.get("mode") == "no-owned-schedule"
                            and owned["state"] == "available" and owned["count"] == 0 and not ownership_unknown
                            and coverage_matches and shared_count_matches
                            and all(item["status"] == "preserved" for item in shared["records"]))
    observation_refs = []
    if observation is not None:
        for item in shared["records"]:
            observation_refs.extend(ref for key in ("assignment_ref", "project_ref", "record_ref")
                                    if (ref := _safe_ref(item.get(key), authority)) is not None)
    return {"state": _bounded_label(value.get("status")) or "unknown",
            "complete": value.get("status") in {"reconciled", "complete", "completed"} and observation_complete,
            "survivor_refs_present": survivors["state"] != "unavailable",
            "survivor_refs": survivor_refs,
            "survivor_refs_count": survivors["count"],
            "survivor_refs_truncated": survivors["truncated"],
            "observation_ref": _safe_ref(value.get("observation_ref")),
            "mode": _bounded_label(value.get("mode")),
            "observation": {"state": "complete" if observation_complete else "partial-or-unknown",
                "mode": _bounded_label(observation.get("mode")) if observation is not None else None,
                "pm_owned_schedule_ids": owned,
                "coverage": coverage, "shared_records": shared,
                "unknown_ownership": ownership_unknown},
            "host_effects": _bounded_refs_projection(value.get("host_effects"), _TASK_LIMIT, authority),
            "observation_refs": _dedupe_refs(observation_refs)}


def _facet_collection_state(rows: list[Mapping[str, Any]], reconciliation: Mapping[str, Any]) -> str:
    task_facets = [row.get("survivor_facets") for row in rows if row.get("state") is None]
    if rows and len(task_facets) != len(rows):
        return "partial"
    if (task_facets and all(isinstance(facet, Mapping) and facet.get("state") == "available"
                            and any(group.get("complete") for group in facet.get("groups", {}).values())
                            for facet in task_facets)
            and reconciliation.get("observation", {}).get("state") == "complete"):
        return "complete"
    if any(isinstance(facet, Mapping) and facet.get("refs") for facet in task_facets) or reconciliation.get("survivor_refs") or reconciliation.get("observation_refs"):
        return "partial"
    return "unavailable"


def _dedupe_refs_projection(values: list[Mapping[str, Any]], limit: int = _TASK_LIMIT) -> Mapping[str, Any]:
    seen, result = set(), []
    for value in values:
        key = tuple(value.get(part) for part in ("authority", "kind", "id", "revision"))
        if key not in seen:
            seen.add(key)
            if len(result) < limit:
                result.append(value)
    return {"refs": result, "count": len(seen), "truncated": len(seen) > limit}


def _dedupe_refs(values: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return _dedupe_refs_projection(values)["refs"]

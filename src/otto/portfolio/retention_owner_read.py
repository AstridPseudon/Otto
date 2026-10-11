"""Finite owner-only views for the retained Usage project.

This facade deliberately has no target-project, actor, SQL, filesystem, or
Store-open input. It consumes the already authenticated owner lane and only
the existing injected evidence command handler for a bounded preview.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from herzchen.contracts import ResourceRef


USAGE_PROJECT_ID = "project-0414b14adc7aa1b935e1dc773660"
_MAX_RECORD_BYTES = 32768
_TASK_LIMIT = 100
_TASK_RECORD_BYTES = 16384
_TASK_PAGE_SIZE = 25
_MAX_TASK_PAGES = 4
_MAX_CURSOR = 512


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
        if view == "reclaim-preview":
            if set(handle) != {"view", "cutoff", "cursor", "limit"}:
                raise ValueError("reclaim preview requires explicit cutoff, cursor and limit")
            return self._preview(handle, root=root, actor=actor, request_key=request.get("request_key"))
        raise ValueError("unsupported retention view")

    def _fixed_project(self) -> tuple[Any, Any]:
        owner = self.service.server.owner
        project_ref = ResourceRef(owner.store.authority, "work.project", USAGE_PROJECT_ID)
        read = owner.store.consumer().get_identity_bounded(project_ref, max_record_bytes=_MAX_RECORD_BYTES)
        project = read.get("record")
        if read.get("state") != "available" or project is None:
            raise PermissionError("fixed Usage project is missing or requires bounded detail")
        return owner, project

    def _lifecycle(self, *, root: Any, actor: Any) -> Mapping[str, Any]:
        owner, project_record = self._project_context(root=root, actor=actor)
        project = project_record.payload
        consumer = owner.store.consumer()
        after = ""
        discovered = []
        examined = held_pages = 0
        next_cursor = None
        pages = 0
        for _ in range(_MAX_TASK_PAGES):
            page = consumer.read_identity_page(kind="work.task", after=after, limit=_TASK_PAGE_SIZE,
                max_record_bytes=_TASK_RECORD_BYTES,
                payload_matches={("project_ref", "authority"): project_record.ref.authority,
                                 ("project_ref", "kind"): project_record.ref.kind,
                                 ("project_ref", "id"): project_record.ref.id})
            pages += 1
            examined += page["examined"]
            held_pages += page["held"]
            discovered.extend(page["records"])
            next_cursor = page["next_cursor"]
            if next_cursor is None:
                break
            after = next_cursor
        task_refs = project.get("tasks")
        project_task_refs_available = isinstance(task_refs, (list, tuple))
        declared_task_count = len(task_refs) if project_task_refs_available else None
        rows = []
        selected_ids = set()
        assignments = [root.ref.to_dict()]
        observations = []
        held = 0
        sources = [(record.ref, record.payload, "available") for record in discovered]
        for raw_ref in (task_refs[:_TASK_LIMIT] if project_task_refs_available else ()):
            task_ref = _safe_ref(raw_ref)
            if (task_ref is None or task_ref.get("authority") != project_record.ref.authority
                    or task_ref.get("kind") != "work.task"):
                held += 1
                continue
            if task_ref["id"] in selected_ids:
                continue
            if any(existing_ref.id == task_ref["id"] for existing_ref, _payload, _state in sources):
                continue
            if len(sources) >= _TASK_LIMIT:
                held += 1
                break
            bounded = owner.store.consumer().get_identity_bounded(ResourceRef.from_dict(task_ref),
                max_record_bytes=_TASK_RECORD_BYTES)
            record = bounded.get("record")
            if bounded.get("state") != "available" or record is None:
                held += 1
                rows.append({"task_ref": task_ref, "lifecycle": None, "state": bounded.get("state")})
                continue
            sources.append((record.ref, record.payload, "available"))
        for ref, payload, _state in sources:
            if ref.id in selected_ids:
                continue
            selected_ids.add(ref.id)
            if not _same_ref_identity(payload.get("project_ref"), project_record.ref.to_dict()):
                held += 1
                rows.append({"task_ref": ref.to_dict(), "lifecycle": None, "state": "project-link-mismatch"})
                continue
            assignment_ref = _safe_ref(payload.get("assignment_ref"))
            if assignment_ref is not None:
                assignments.append(assignment_ref)
            result_refs = _bounded_refs_projection(payload.get("results"), 16)
            observation_refs = _bounded_refs_projection(payload.get("observations"), 16)
            observations.extend(result_refs["refs"])
            observations.extend(observation_refs["refs"])
            rows.append({"task_ref": ref.to_dict(),
                         "lifecycle": _bounded_label(payload.get("lifecycle")),
                         "assignment_ref": assignment_ref,
                         "result_refs": result_refs,
                         "observation_refs": observation_refs})
        lifecycle_control = project.get("lifecycle_control")
        reconciliation = (lifecycle_control.get("reconciliation")
                          if isinstance(lifecycle_control, Mapping) else None)
        reconciliation_view = _reconciliation_projection(reconciliation)
        observations.extend(reconciliation_view["survivor_refs"])
        if reconciliation_view["observation_ref"] is not None:
            observations.append(reconciliation_view["observation_ref"])
        unique_assignments = _dedupe_refs(assignments)
        unique_observations = _dedupe_refs(observations)
        task_inventory_complete = (next_cursor is None and held_pages == 0 and held == 0
                                   and (not project_task_refs_available or declared_task_count <= _TASK_LIMIT))
        observation_complete = False  # No finite subject-only observation reader is currently injected.
        complete = task_inventory_complete and observation_complete and reconciliation_view["complete"]
        return {"outcome": "read", "view": "lifecycle", "project_ref": project_record.ref.to_dict(),
                "lifecycle": _bounded_label(project.get("lifecycle")),
                "current_lifecycle": _bounded_label(project.get("lifecycle")),
                "reconciliation": reconciliation_view,
                "tasks": rows,
                "task_inventory": {"state": "complete" if task_inventory_complete else "partial-or-unknown",
                    "selected_count": len(rows), "declared_count": declared_task_count,
                    "limit": _TASK_LIMIT, "held": held + held_pages,
                    "pages": pages, "identities_examined": examined,
                    "next_cursor": next_cursor,
                    "truncated": bool(next_cursor is not None or project_task_refs_available
                                      and declared_task_count > _TASK_LIMIT)},
                "assignment_refs": unique_assignments,
                "observation_subjects": {"state": "partial" if unique_observations else "unavailable",
                    "refs": unique_observations,
                    "reason": "only refs present in selected canonical metadata are shown; no bounded event-subject reader is installed"},
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
        diagnostics_view = {"work": work_view, "stages": stages, "records_modified": diagnostics.get("records_modified") is False}
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
        required_stages = {"pages", "tables", "payload_groups", "allocation"}
        complete = (work_view["state"] == "complete" and custody_ok
                    and required_stages.issubset(stages)
                    and all(stages[name]["state"] == "complete" for name in required_stages)
                    and diagnostics_view["records_modified"] is True)
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
        result = self.evidence_handler.reclaim_preview(project.ref, actor=actor,
            logical_request_key="retention-read:" + request_key, cutoff=cutoff,
            cursor=cursor, limit=limit)
        items = []
        for item in result.get("items", ())[:100]:
            if not isinstance(item, Mapping):
                continue
            row = {key: item[key] for key in ("byte_length", "eligible", "hold", "material_class")
                   if key in item and (key != "byte_length" or type(item[key]) is int and item[key] >= 0)
                   and (key != "eligible" or type(item[key]) is bool)
                   and (key not in {"hold", "material_class"} or isinstance(item[key], str))}
            reference = _object_ref(item.get("reference"))
            if reference is not None:
                row["reference"] = reference
            items.append(row)
        selection_ref = _object_ref(result.get("selection_ref"))
        selection = result.get("selection") if isinstance(result.get("selection"), Mapping) else {}
        return {"outcome": result.get("outcome", "previewed"), "view": "reclaim-preview",
                "project_ref": project.ref.to_dict(), "selection_ref": selection_ref,
                "selection_digest": _bounded_label(selection.get("selection_digest")),
                "cutoff": cutoff, "cursor": cursor, "limit": limit,
                "next_cursor": result.get("next_cursor"), "items": items,
                "read_only": False, "canonical_selection_recorded": True,
                "provider_called": False, "deletion_count": 0,
                "managed_bytes_removed": result.get("managed_bytes_removed", 0),
                "writes": 1 if result.get("outcome") == "previewed" else 0,
                "writes_meaning": "canonical selection receipt; replay returns the existing receipt"}


def _bounded_label(value: Any) -> str | None:
    return value[:128] if isinstance(value, str) else None


def _has_current_reconciliation(project_payload: Mapping[str, Any]) -> bool:
    lifecycle_control = project_payload.get("lifecycle_control")
    reconciliation = lifecycle_control.get("reconciliation") if isinstance(lifecycle_control, Mapping) else None
    return (project_payload.get("lifecycle") == "completed" and isinstance(reconciliation, Mapping)
            and reconciliation.get("status") == "reconciled")


def _safe_ref(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or not all(isinstance(value.get(k), str) for k in ("authority", "kind", "id")):
        return None
    return {key: value[key] for key in ("authority", "kind", "id", "revision") if key in value}


def _same_ref_identity(left: Any, right: Any) -> bool:
    left_ref, right_ref = _safe_ref(left), _safe_ref(right)
    return (left_ref is not None and right_ref is not None
            and all(left_ref.get(key) == right_ref.get(key) for key in ("authority", "kind", "id")))


def _safe_ref_list(value: Any, limit: int) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [ref for item in value[:limit] if (ref := _safe_ref(item)) is not None]


def _bounded_refs_projection(value: Any, limit: int) -> Mapping[str, Any]:
    if value is None:
        return {"state": "unavailable", "refs": [], "count": None, "truncated": False}
    if not isinstance(value, (list, tuple)):
        return {"state": "invalid", "refs": [], "count": None, "truncated": False}
    refs = _safe_ref_list(value, limit)
    truncated = len(value) > limit
    invalid = len(value[:limit]) - len(refs)
    return {"state": "available" if not truncated and not invalid else "partial",
            "refs": refs, "count": len(value), "valid_count": len(refs), "invalid_count": invalid,
            "truncated": truncated}


def _object_ref(value: Any) -> Mapping[str, Any] | None:
    if hasattr(value, "result_ref"):
        value = value.result_ref
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return _safe_ref(value)


def _reconciliation_projection(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unknown", "complete": False, "survivor_refs": [],
                "survivor_refs_count": None, "survivor_refs_truncated": False,
                "observation_ref": None}
    survivors = _bounded_refs_projection(value.get("survivor_refs"), _TASK_LIMIT)
    return {"state": _bounded_label(value.get("status")) or "unknown",
            "complete": value.get("status") in {"reconciled", "complete", "completed"},
            "survivor_refs_present": survivors["state"] != "unavailable",
            "survivor_refs": survivors["refs"],
            "survivor_refs_count": survivors["count"],
            "survivor_refs_truncated": survivors["truncated"],
            "observation_ref": _safe_ref(value.get("observation_ref"))}


def _dedupe_refs(values: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen, result = set(), []
    for value in values:
        key = tuple(value.get(part) for part in ("authority", "kind", "id", "revision"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result[:_TASK_LIMIT]

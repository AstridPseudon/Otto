"""Pure, pinned Worker-retirement source mapping; no owner or provider effects.

This converter is intentionally specific to the frozen Worker project.  It
produces proposed records and diagnostics for a later owner-backed importer;
it neither creates native references nor switches source authority.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping

from herzchen.contracts import canonical_json


TRUTH_SHA256 = "95afa20602a18a40c4aa40c4e93079e1be00d10438e782a72ef721088320f917"
SOURCE_RUN_CONFIG_SHA256 = "19addfcc1bc15275f4acc1979159b404fe129f0c3205931e2daee863f31c79f2"
_TASK_IDS = tuple(f"T{number:02d}" for number in range(1, 25))
_CRITERION_IDS = tuple(f"C{number:02d}" for number in range(1, 25))
_TASK_TOKEN = re.compile(r"\bT(?:0[1-9]|1[0-9]|2[0-4])\b")
_CRITERION_TOKEN = re.compile(r"\bC(\d{2})(?:[–-]C(\d{2}))?\b")

# Exact finite projection of the pinned source run.yaml. Its raw bytes are
# carried as a document and checked against SOURCE_RUN_CONFIG_SHA256 below.
_SOURCE_ROLE_BINDINGS = {
    "coordinator": {"model": "gpt-6-astra", "reasoning": "high"},
    "worker_normal": {"model": "gpt-6-luna", "reasoning": "high"},
    "worker_xhard": {"model": "gpt-6-sol", "reasoning": "high"},
    "reviewer_normal": {"model": "gpt-6-luna", "reasoning": "medium"},
    "reviewer_xhard": {"model": "gpt-6-astra", "reasoning": "high"},
    "oracle": {"model": "gpt-6-astra", "reasoning": "high"},
    "final_reviewer": {"model": "gpt-6-astra", "reasoning": "high"},
}
_DORMANT_STAGE_PROJECTION = {
    "foundation": {
        "after": ["T07", "T08"], "gates": ["T09", "T11", "T13"],
        "reviewer_role": "reviewer_xhard", "classification": "xhard",
        "scope_tasks": ["T01", "T03", "T04", "T05", "T06", "T07", "T08"],
        "criteria": ["C01", "C03", "C04", "C05", "C06", "C07", "C08"],
    },
    "final_completion": {
        "after": ["T24"], "gates": ["code_cpu_delivery_complete"],
        "reviewer_role": "final_reviewer", "classification": "normal",
        "scope_tasks": [task for task in _TASK_IDS if task not in {"T22", "T23"}],
        "criteria": [criterion for criterion in _CRITERION_IDS if criterion not in {"C22", "C23"}],
    },
}


class WorkerImportMappingError(ValueError):
    """A frozen input changed or cannot be represented faithfully."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise WorkerImportMappingError(code, message)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _criterion_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in _CRITERION_TOKEN.finditer(text):
        first = int(match.group(1))
        last = int(match.group(2) or match.group(1))
        _require(1 <= first <= last <= 24, "criterion_reference_invalid", match.group())
        for number in range(first, last + 1):
            ref = f"C{number:02d}"
            if ref not in refs:
                refs.append(ref)
    return refs


def _expanded_applicability(value: Mapping[str, Any]) -> dict[str, str]:
    assigned: dict[str, str] = {}
    for label, ranges in value.items():
        _require(isinstance(ranges, list), "applicability_invalid", str(label))
        for expression in ranges:
            _require(isinstance(expression, str), "applicability_invalid", str(label))
            refs = _criterion_refs(expression)
            _require(bool(refs), "applicability_invalid", expression)
            for ref in refs:
                _require(ref not in assigned, "applicability_conflict", ref)
                assigned[ref] = label
    _require(set(assigned) == set(_CRITERION_IDS), "applicability_incomplete", "C01–C24 must each have one source category")
    return assigned


def build_worker_import_map(
    truth_bytes: bytes,
    document_bytes: Mapping[str, bytes],
    *,
    expected_truth_sha256: str = TRUTH_SHA256,
) -> dict[str, Any]:
    """Map the exact frozen truth and supplied file bytes without I/O.

    The caller supplies bytes keyed by the independent truth's ``source_key``.
    Every byte and source identity is checked before any proposed mapping is
    returned. Native references remain null until a separate owner operation.
    """
    _require(isinstance(truth_bytes, bytes), "truth_invalid", "truth must be bytes")
    _require(_sha(truth_bytes) == TRUTH_SHA256 == expected_truth_sha256,
             "changed_truth_conflict", "independent truth digest differs from the frozen input")
    try:
        truth = json.loads(truth_bytes)
    except (UnicodeError, ValueError) as exc:
        raise WorkerImportMappingError("truth_invalid", "truth JSON is malformed") from exc
    _require(isinstance(truth, dict) and truth.get("kind") == "otto-worker-truth-freeze",
             "truth_invalid", "independent truth kind is not exact")
    _require(truth.get("task_ids") == list(_TASK_IDS) and truth.get("criterion_ids") == list(_CRITERION_IDS),
             "source_id_conflict", "source IDs are not exactly T01–T24/C01–C24")
    _require(isinstance(truth.get("tasks"), dict) and set(truth["tasks"]) == set(_TASK_IDS),
             "source_id_conflict", "task source rows are incomplete")
    _require(isinstance(truth.get("criteria"), dict) and set(truth["criteria"]) == set(_CRITERION_IDS),
             "source_id_conflict", "criterion source rows are incomplete")
    inventory = truth.get("document_inventory")
    _require(isinstance(inventory, dict), "inventory_invalid", "document inventory is missing")
    entries = inventory.get("files_with_aliases_and_membership")
    _require(isinstance(entries, list) and len(entries) == 194,
             "inventory_invalid", "the frozen 194 source views are required")
    _require(isinstance(document_bytes, Mapping), "document_input_invalid", "source bytes must be keyed by source alias")
    entry_keys = [entry.get("source_key") for entry in entries if isinstance(entry, dict)]
    _require(len(entry_keys) == len(entries) and len(set(entry_keys)) == len(entries)
             and set(document_bytes) == set(entry_keys),
             "source_alias_conflict", "document aliases differ from the frozen census")

    documents: list[dict[str, Any]] = []
    canonical_by_raw: dict[str, str] = {}
    for entry in sorted(entries, key=lambda item: item["source_key"]):
        key = entry["source_key"]
        raw = document_bytes[key]
        _require(isinstance(raw, bytes) and len(raw) == entry.get("bytes")
                 and _sha(raw) == entry.get("sha256"),
                 "changed_document_conflict", key)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkerImportMappingError("unsupported_document_encoding", key) from exc
        # ContentRevision hashes canonical JSON of its content. The proposed
        # content is the exact UTF-8 string, while original bytes are retained
        # separately by their raw source digest.
        content_sha = sha256(canonical_json(text).encode("utf-8")).hexdigest()
        prior = canonical_by_raw.setdefault(entry["sha256"], content_sha)
        _require(prior == content_sha, "canonical_content_conflict", key)
        documents.append({
            "source_alias": key, "source_path": entry["source_path"],
            "disposition": entry["disposition"],
            "proposed_representation": entry["proposed_representation"],
            "raw_sha256": entry["sha256"], "raw_bytes": entry["bytes"],
            "canonical_content_sha256": content_sha,
            "content_kind": "utf8_string", "native_ref": None,
            "identical_content_sources": sorted(entry["identical_content_sources"]),
        })
    config = next(doc for doc in documents if doc["source_alias"] == "run/run.yaml")
    _require(config["raw_sha256"] == SOURCE_RUN_CONFIG_SHA256,
             "source_policy_conflict", "the frozen role/review policy changed")

    applicability = _expanded_applicability(truth.get("criterion_applicability", {}))
    derived = truth.get("derived_T14_subparts", {})
    _require(derived.get("canonical_children") == [] and
             derived.get("derived") == ["inventory-disposition", "vibe-implementation", "wan-implementation", "shared-rows"],
             "partial_dependency_conflict", "T14 portion aliases changed")
    tasks: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    dependency_options: list[dict[str, Any]] = []
    policy_guards: list[dict[str, str]] = []
    for task_id in _TASK_IDS:
        row = truth["tasks"][task_id]
        _require(isinstance(row, dict) and row.get("status") in
                 {"not_started", "conditional", "deferred_external_followup"},
                 "task_status_invalid", task_id)
        route = row.get("route_role")
        _require(route in {"normal → worker_normal", "xhard → worker_xhard"},
                 "task_route_invalid", task_id)
        gate = row.get("dependencies_gate")
        _require(isinstance(gate, str), "task_dependency_invalid", task_id)
        requires = list(_TASK_TOKEN.findall(gate))
        if task_id in {"T15", "T16"}:
            requires = list(derived[f"{task_id}_requires"])
            _require("T14" not in requires and all(
                value in _TASK_IDS or value.startswith("T14:") for value in requires),
                "partial_dependency_conflict", task_id)
        if task_id == "T23":
            _require(requires == ["T22"] and "or evidenced no-cutover disposition" in gate,
                     "alternative_dependency_conflict", task_id)
            # T22 is one possible future branch, not an unconditional barrier.
            requires = []
            dependency_options.append({
                "dependent": "T23", "one_of": [
                    {"completed_task_alias": "T22"},
                    {"evidenced_no_cutover_disposition": True},
                ],
                "additional_guard": "separate explicit follow-up authority",
                "native_binding": None,
            })
        for needed in requires:
            _require(needed != task_id and (needed in _TASK_IDS or needed.startswith("T14:")),
                     "task_dependency_invalid", task_id)
            edges.append({"dependent": task_id, "requires": needed,
                          "kind": "derived_T14_portion" if needed.startswith("T14:") else "whole_task"})
        residue = _TASK_TOKEN.sub("", gate)
        if task_id in {"T15", "T16"}:
            residue = ""
        if re.sub(r"[\s,;]+", "", residue).lower() not in {"", "none"}:
            policy_guards.append({"task_alias": task_id, "source_gate_text": gate,
                                  "diagnostic": "non-ID gate text needs an explicit owner/policy binding"})
        tasks.append({
            "source_alias": task_id, "native_ref": None,
            "source_status": row["status"], "native_initial_state": None,
            "applicability_guard": row["status"] if row["status"] != "not_started" else None,
            "route_class": "xhard" if route.startswith("xhard") else "normal",
            "worker_binding": route.split("→", 1)[1].strip(),
            "outcome_scope": row["outcome_scope"],
            "source_dependency_gate": gate,
            "requires_aliases": requires,
            "source_acceptance": row["acceptance"],
            "criterion_aliases": _criterion_refs(row["acceptance"]),
        })
    criteria = [
        {"source_alias": criterion_id, "native_ref": None,
         "expected_behavior": truth["criteria"][criterion_id]["expected_behavior"],
         "proof": truth["criteria"][criterion_id]["proof"],
         "applicability": applicability[criterion_id], "verdict": None}
        for criterion_id in _CRITERION_IDS
    ]
    _require(truth.get("task_status_counts") ==
             {"not_started": 20, "conditional": 2, "deferred_external_followup": 2},
             "task_status_conflict", "frozen status counts changed")
    review = truth.get("review_and_advice", {})
    _require(review.get("active_stages") == [] and review.get("dormant_stages") ==
             {"foundation": {"cap": 2, "consumed": 0},
              "final_completion": {"cap": 2, "consumed": 0}},
             "review_policy_conflict", "dormant stage counters changed")
    stages = [
        {"source_id": stage_id, "native_ref": None, "state": "dormant",
         "cap": review["dormant_stages"][stage_id]["cap"],
         "consumed": review["dormant_stages"][stage_id]["consumed"],
         **projection}
        for stage_id, projection in _DORMANT_STAGE_PROJECTION.items()
    ]
    link_audit = inventory.get("link_audit", {}).get("full_text_corpus", {})
    required_assets = truth.get("required_T01_sources", [])
    mapping = {
        "schema": "otto.worker-import-map.v1", "source_authority": "frozen_files_only",
        "source_truth_sha256": TRUTH_SHA256,
        "source_run": truth["source_run"], "source_run_config_sha256": SOURCE_RUN_CONFIG_SHA256,
        "documents": documents, "tasks": tasks, "criteria": criteria,
        "dependency_edges": edges, "dependency_options": dependency_options,
        "derived_aliases": [
            {"alias": f"T14:{portion}", "parent_source_alias": "T14", "native_ref": None,
             "canonical_source_task": False}
            for portion in derived["derived"]
        ],
        "role_bindings": _SOURCE_ROLE_BINDINGS,
        "dormant_review_stages": stages,
        "history_and_advice": {
            "historical_oracle_decisions": review["historical_oracle_decisions"],
            "planning_critiques_consumed": review["planning_critiques_consumed"],
            "delivery_review_rounds": review["delivery_review_rounds"],
            "blocker_advice": review["blocker_advice"],
            "retired_installed_integration": review["retired_installed_integration"],
            "history_is_imported_observation_not_native_execution": True,
        },
        "required_T01_assets": [
            {"path": asset["path"], "raw_sha256": asset["sha256"],
             "bytes": asset["bytes"], "source_exists_at_freeze": asset["exists"],
             "native_ref": None}
            for asset in required_assets
        ],
        "diagnostics": {
            "non_id_policy_guards": policy_guards,
            "unresolved_local_links_at_freeze": link_audit.get("unresolved_local_link_instances"),
            "paths_with_unresolved_links_at_freeze": link_audit.get("paths_with_unresolved_local_links"),
            "native_ref_count": 0,
            "deferred_and_conditional_native_lifecycle_unresolved": True,
            "T14_portion_owner_records_unresolved": True,
            "review_stage_owner_binding_unresolved": True,
            "asset_portability_unresolved": True,
            "owner_write_and_replay_unperformed": True,
        },
    }
    mapping["mapping_sha256"] = sha256(canonical_json(mapping).encode("utf-8")).hexdigest()
    return mapping


__all__ = ["TRUTH_SHA256", "WorkerImportMappingError", "build_worker_import_map"]

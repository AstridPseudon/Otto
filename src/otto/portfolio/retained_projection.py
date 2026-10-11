"""Finite routine projections beside exact retained historical JSON artifacts.

The owning host captures once. A projection is evidence of that capture, not a
new authority, acceptance or claim that the current bytes were fully rehashed.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from itertools import islice
from pathlib import Path
from typing import Any, Mapping

MAX_PROJECTION_BYTES = 65536
MAX_SUMMARY_ITEMS = 32
SCHEMA = "otto.retained-projection.v1"
FIELDS = (
    "outcome", "status", "stage", "phase", "source_commit", "schedule_id", "principal",
    "generation", "role", "version", "delivery_state", "completion_state", "stop_state",
    "provider_called", "retry_provider", "unknown_reason", "model", "reasoning",
    "candidate_sha256", "worker_result_digest", "result_digest", "context_digest",
    "candidate_digest", "worker_result_sha256", "sha256", "digest", "resource_set_digest", "manager_generation",
    "context_digest_verified", "physical_session_id", "observed_turn_id", "request_key",
    "logical_request_key", "captured_at", "started_at", "completed_at",
    "capacity_units", "cumulative_allowance_units", "cumulative_used_units", "held_units",
    "resource_name", "content_digest", "native_session_id", "state_sha256",
    "request_id", "retained_handle", "response_path", "next_command",
)
REF_FIELDS = ("ref", "candidate_ref", "result_ref", "project_ref", "task_ref", "assignment_ref",
              "parent_assignment_ref", "mandate_ref", "resource_ref", "original_candidate_ref")
SLOTS = ("result", "occurrence", "parent", "gateway_attempt", "host_evidence", "request_input",
         "candidate", "worker_result", "completion_evidence", "delivery_evidence", "before_state",
         "review_input", "parent_binding", "result_destination",
         "manager_result_notification", "task_settlement_notification")


def exact_ref(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        return None
    if any(not isinstance(value.get(k), str) or not 1 <= len(value[k]) <= 512 for k in ("authority", "kind", "id")):
        return None
    revision = value.get("revision")
    if revision is not None and (not isinstance(revision, str) or not 1 <= len(revision) <= 512):
        return None
    return {k: value.get(k) for k in ("authority", "kind", "id", "revision")}


def exact_occurrence_summary(value: Any) -> dict[str, Any] | None:
    """Preserve one complete handle, including parent:null; never clip its pins."""
    fields = ("schedule_id", "assignment_ref", "generation", "project_ref", "task_ref", "parent")
    if not isinstance(value, Mapping) or set(value) != set(fields):
        return None
    if (not isinstance(value["schedule_id"], str) or not 1 <= len(value["schedule_id"]) <= 512
            or type(value["generation"]) is not int or value["generation"] < 1
            or any(exact_ref(value[key]) is None or exact_ref(value[key]) != value[key]
                   for key in ("assignment_ref", "project_ref", "task_ref"))
            or value["parent"] is not None and not isinstance(value["parent"], Mapping)):
        return None
    # Parent custody/result-destination joins are immutable handle data, not
    # prose. An over-bound/invalid handle requires original detail, never an
    # incomplete handle that the strict canonical reader would reject.
    try:
        if len(json.dumps(value, ensure_ascii=False).encode()) > 16384:
            return None
    except (TypeError, ValueError):
        return None
    return {key: value[key] for key in fields}


def finite_summary(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = {key: item for key in FIELDS if key in value
              and isinstance((item := value[key]), (str, bool, int, type(None)))
              and (not isinstance(item, str) or len(item) <= 512)}
    for key in REF_FIELDS:
        ref = exact_ref(value.get(key))
        if ref:
            result[key] = ref
    for key in ("source_refs", "evidence_refs"):
        refs = value.get(key)
        if isinstance(refs, (list, tuple)):
            result[key] = [ref for item in refs[:MAX_SUMMARY_ITEMS] if (ref := exact_ref(item))]
            result[key + "_omitted"] = max(0, len(refs) - MAX_SUMMARY_ITEMS)
    # Fixed semantic slots and a finite depth; never walk arbitrary envelopes,
    # raw results, native commands, full before-state or evidence bodies.
    if depth < 4:
        for key in SLOTS:
            if isinstance(value.get(key), Mapping):
                if key == "occurrence" and set(value[key]) == {"schedule_id", "assignment_ref", "generation", "project_ref", "task_ref", "parent"}:
                    handle = exact_occurrence_summary(value[key])
                    if handle is not None:
                        result[key] = handle
                    else:
                        result["occurrence_availability"] = "detail-required; exact handle cannot be partially projected"
                else:
                    result[key] = finite_summary(value[key], depth=depth + 1)
    if depth == 0:
        for key in ("stages", "pools_before"):
            items = value.get(key)
            if isinstance(items, Mapping):
                result[key] = {name: finite_summary(item, depth=1)
                    for name, item in islice(items.items(), MAX_SUMMARY_ITEMS)
                    if isinstance(name, str) and len(name) <= 128}
                result[key + "_omitted"] = max(0, len(items) - MAX_SUMMARY_ITEMS)
        workers = value.get("workers_before")
        if isinstance(workers, (list, tuple)):
            result["workers_before"] = [finite_summary(item, depth=1) for item in workers[:MAX_SUMMARY_ITEMS]]
            result["workers_before_omitted"] = max(0, len(workers) - MAX_SUMMARY_ITEMS)
    return result


def atomic_json(path: Path, value: Any) -> dict[str, Any]:
    """Single-pass serialized capture/hash, then atomic publication."""
    path = Path(path)
    temporary = path.with_name("." + path.name + ".tmp")
    started = time.perf_counter()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as stream:
            for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(value):
                raw = chunk.encode()
                stream.write(raw); digest.update(raw); size += len(raw)
            stream.write(b"\n"); digest.update(b"\n"); size += 1
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"sha256": digest.hexdigest(), "byte_length": size,
            "capture_processing_seconds": time.perf_counter() - started}


def projection(value: Any, *, artifact: Mapping[str, Any], binding: Mapping[str, Any], summary=None,
               oversize: str = "error") -> dict[str, Any]:
    if oversize not in {"error", "detail"}:
        raise ValueError("unsupported projection overflow policy")
    result = {"schema": SCHEMA, "artifact": dict(artifact), "binding": dict(binding),
              "summary": finite_summary(value) if summary is None else summary,
              "verification": "captured-exact-reference; current-bytes-not-revalidated"}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PROJECTION_BYTES:
        if oversize == "error":
            raise ValueError("retained projection exceeds its finite metadata bound")
        # Terminal transport capture already preserved exact raw bytes. Do not
        # turn a successful read/mutation into an error just because optional
        # metadata includes a full direction or before-state. No body clipping
        # or false absence: only top-level finite outcome/pins survive here.
        small = {key: item for key in FIELDS if isinstance(value, Mapping) and key in value
                 and isinstance((item := value[key]), (str, bool, int, type(None)))
                 and (not isinstance(item, str) or len(item) <= 512)}
        for key in REF_FIELDS:
            ref = exact_ref(value.get(key)) if isinstance(value, Mapping) else None
            if ref:
                small[key] = ref
        result["summary"] = small
        result["summary_availability"] = {
            "state": "detail-required", "reason": "complete summary exceeds finite metadata bound",
            "full_response_preserved": True,
            "next_action": "Inspect the exact artifact path/digest; do not resend or infer absent effects/budgets from omitted metadata."}
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PROJECTION_BYTES:
            raise ValueError("retained artifact/binding metadata exceeds its finite bound")
    return result


def write_preparation_checkpoint(path: str | Path, value: Mapping[str, Any], *,
                                 binding: Mapping[str, Any]) -> Mapping[str, Any]:
    """Publish a compact checkpoint; original details stay in one exact artifact.

    The caller supplies its current assignment/generation/parent association.
    Historical snapshots never become current owner state or execution inputs.
    """
    path = Path(path)
    artifact_path = path.with_name(path.stem + ".detail.json")
    if path.exists() or artifact_path.exists():
        raise FileExistsError("checkpoint artifacts are immutable; inspect the retained original")
    capture = atomic_json(artifact_path, value)
    result = projection(value, artifact={"path": str(artifact_path), **capture}, binding=binding)
    atomic_json(path, result)
    return result


def read_projection(path: str | Path, *, expected_binding: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_PROJECTION_BYTES + 1)
    if len(raw) > MAX_PROJECTION_BYTES:
        raise ValueError("retained projection exceeds its bound")
    value = json.loads(raw)
    if value.get("schema") != SCHEMA or value.get("binding") != dict(expected_binding):
        raise PermissionError("retained projection unavailable for this binding")
    artifact = value.get("artifact", {})
    digest = artifact.get("sha256")
    if (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            or type(artifact.get("byte_length")) is not int or artifact["byte_length"] < 0):
        raise ValueError("retained artifact identity is incomplete")
    return {**value, "io_work": {"metadata_bytes_read": len(raw), "metadata_bytes_parsed": len(raw),
            "payload_bytes_read": 0, "payload_bytes_parsed": 0, "payload_bytes_hashed": 0,
            "processing_seconds": time.perf_counter() - started}}


def capture_preparation_checkpoint(path: str | Path, source: str | Path, *,
                                   expected_sha256: str, expected_length: int,
                                   binding: Mapping[str, Any]) -> Mapping[str, Any]:
    """Explicit one-time historical admission, preserving exact original bytes.

    Unlike read_projection this is deliberately linear: it reads/parses/hashes
    the source once and copies it into immutable host custody. Routine readers
    use only the compact checkpoint. No provider/owner/replay effects occur.
    """
    path = Path(path)
    detail = path.with_name(path.stem + ".detail.json")
    if path.exists() or detail.exists():
        raise FileExistsError("checkpoint artifacts already exist")
    started = time.perf_counter()
    raw = Path(source).read_bytes()
    read_seconds = time.perf_counter() - started
    started = time.perf_counter()
    digest = hashlib.sha256(raw).hexdigest()
    hash_seconds = time.perf_counter() - started
    if len(raw) != expected_length or digest != expected_sha256:
        raise ValueError("historical checkpoint source identity changed")
    started = time.perf_counter()
    value = json.loads(raw)
    parse_seconds = time.perf_counter() - started
    result = projection(value, artifact={"path": str(detail), "sha256": digest, "byte_length": len(raw)}, binding=binding)
    with detail.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    atomic_json(path, result)
    return {**result, "admission_work": {"payload_bytes_read": len(raw), "payload_bytes_parsed": len(raw),
        "payload_bytes_hashed": len(raw), "read_seconds": read_seconds,
        "parse_seconds": parse_seconds, "hash_seconds": hash_seconds, "linear_historical_capture": True}}


def read_checkpoint_detail(path: str | Path, *, expected_binding: Mapping[str, Any],
                           offset: int = 0, max_bytes: int = 65536) -> Mapping[str, Any]:
    """Explicit capped historical bytes from the exact locally retained pin."""
    if type(offset) is not int or offset < 0 or type(max_bytes) is not int or not 0 <= max_bytes <= 65536:
        raise ValueError("invalid historical byte range")
    path = Path(path)
    metadata = read_projection(path, expected_binding=expected_binding)
    detail = path.with_name(path.stem + ".detail.json")
    if metadata["artifact"].get("path") != str(detail) or detail.is_symlink():
        raise PermissionError("historical artifact is outside checkpoint custody")
    try:
        size = detail.stat().st_size
        if size != metadata["artifact"]["byte_length"]:
            return {"availability": "corrupt", "verification": "length-mismatch", "bytes": b""}
        with detail.open("rb") as stream:
            stream.seek(offset); raw = stream.read(max_bytes)
    except FileNotFoundError:
        return {"availability": "missing", "bytes": b""}
    return {"artifact_ref": metadata["artifact"], "binding": metadata["binding"],
            "availability": "admitted", "verification": "range-not-revalidated", "decoding": "raw-bytes",
            "bytes": raw, "offset": offset, "next_offset": offset + len(raw) if offset + len(raw) < size else None,
            "io_work": {**metadata["io_work"], "payload_bytes_read": len(raw)}}


def record_preparation_stage(path: str | Path, *, stage: str, value: Mapping[str, Any],
                             binding: Mapping[str, Any]) -> Mapping[str, Any]:
    """Advance the owner's finite preparation ledger without copying old bodies.

    Bindings come from the authenticated owning preparation, never a transport
    request. Each stage retains one immutable detail artifact; the current
    ledger contains only summaries and exact artifact pins. A partial capture
    is held for inspection rather than silently overwritten on retry.
    """
    path = Path(path)
    if not isinstance(stage, str) or not stage or len(stage) > 64 or any(
            not (c.isascii() and (c.isalnum() or c in "-_")) for c in stage):
        raise ValueError("invalid preparation stage")
    if path.exists():
        with path.open("rb") as stream:
            raw = stream.read(MAX_PROJECTION_BYTES + 1)
        if len(raw) > MAX_PROJECTION_BYTES:
            raise ValueError("preparation ledger exceeds its metadata bound")
        ledger = json.loads(raw)
        if ledger.get("schema") != "otto.preparation-stages.v1" or ledger.get("binding") != dict(binding):
            raise PermissionError("preparation ledger binding changed")
    else:
        ledger = {"schema": "otto.preparation-stages.v1", "binding": dict(binding), "stages": {}}
    stages = ledger["stages"]
    if stage in stages:
        raise FileExistsError("stage already retained; inspect it instead of repeating the effect")
    if len(stages) >= MAX_SUMMARY_ITEMS:
        raise ValueError("preparation stage count exceeds its finite bound")
    checkpoint = path.with_name(path.stem + "-" + stage + ".json")
    # Validate the future current projection before producing a detail artifact.
    summary = finite_summary(value)
    slot = {**summary, "checkpoint_path": str(checkpoint)}
    tentative = {**ledger, "stages": {**stages, stage: slot}}
    if len(json.dumps(tentative).encode()) > MAX_PROJECTION_BYTES - 1024:
        raise ValueError("preparation ledger exceeds its metadata bound")
    captured = write_preparation_checkpoint(checkpoint, value, binding=binding)
    slot["artifact_ref"] = captured["artifact"]
    stages[stage] = slot
    if len(json.dumps(ledger).encode()) > MAX_PROJECTION_BYTES:
        raise ValueError("captured stage retained; preparation ledger exceeds its bound")
    atomic_json(path, ledger)
    return slot

"""Producer-side native body references using the existing Evidence owner.

No historical record is rewritten. Issuing this capability is an explicit
trusted host composition choice; legacy ports retain their existing readers.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "otto.retained-native-body.v1"
MAX_BODY_BYTES = 64 * 1024 * 1024
INLINE_BYTES = 4096


class RetainedNativeBodies:
    def __init__(self, evidence: Any, actor: Any) -> None:
        self.evidence, self.actor = evidence, actor

    def retain(self, value: Any, *, project_ref: Any, task_ref: Any = None,
               attempt_ref: Any = None) -> dict[str, Any]:
        from herzchen.contracts import ResourceRef
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        project_ref = ResourceRef(project.authority, project.kind, project.id).to_dict()
        task_ref = ResourceRef.from_dict(task_ref).to_dict() if isinstance(task_ref, Mapping) else task_ref
        attempt_ref = ResourceRef.from_dict(attempt_ref).to_dict() if isinstance(attempt_ref, Mapping) else attempt_ref
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError("native body exceeds bounded owner capture")
        sha = hashlib.sha256(raw).hexdigest()
        scope = hashlib.sha256(json.dumps([project_ref, task_ref, attempt_ref],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        saved = self.evidence.submit(raw, actor=self.actor,
            logical_request_key="native-body:" + scope + ":" + sha,
            project_ref=project_ref, task_ref=task_ref, attempt_ref=attempt_ref,
            original_creator=self.actor.actor, format="application/json",
            provenance={"producer": SCHEMA, "body_sha256": sha})
        pin = saved["revision_ref"]
        pin = pin.to_dict() if hasattr(pin, "to_dict") else dict(pin)
        return {"schema": SCHEMA, "ref": pin, "sha256": sha, "utf8_bytes": len(raw),
            "origin": {"project_ref": project_ref, **({"task_ref": task_ref} if task_ref else {}),
                **({"attempt_ref": attempt_ref} if attempt_ref else {})}}

    def resolve(self, carrier: Mapping[str, Any], *, expected_origin: Any = None) -> Any:
        if carrier.get("schema") != SCHEMA or type(carrier.get("utf8_bytes")) is not int or not 0 <= carrier["utf8_bytes"] <= MAX_BODY_BYTES:
            raise ValueError("invalid retained native body carrier")
        ref = carrier.get("ref") or {}
        if ref.get("kind") != "dat.content.document" or not ref.get("revision"):
            raise ValueError("immutable Evidence pin required")
        origin = carrier.get("origin")
        if not isinstance(origin, Mapping) or (expected_origin is not None and origin != expected_origin):
            raise ValueError("retained native body scope differs from exact occurrence")
        status = self.evidence.status(ref, actor=self.actor)
        manifest = status.get("manifest") or {}
        if manifest.get("origin") != origin or manifest.get("provenance", {}).get("producer") != SCHEMA:
            raise ValueError("native carrier does not match owner-issued retained evidence")
        chunks = []
        offset = 0
        while offset < carrier["utf8_bytes"]:
            result = self.evidence.read_evidence(ref, actor=self.actor, offset=offset,
                max_bytes=min(65536, carrier["utf8_bytes"] - offset))
            chunk = result.get("bytes")
            if not isinstance(chunk, bytes) or not chunk:
                raise ValueError("retained native body unavailable")
            chunks.append(chunk)
            offset += len(chunk)
        raw = b"".join(chunks)
        if len(raw) != carrier["utf8_bytes"] or hashlib.sha256(raw).hexdigest() != carrier["sha256"]:
            raise ValueError("retained native body changed")
        return json.loads(raw)

    def _origin(self, record):
        project = record.get("project_ref")
        if isinstance(project, str):
            project = {"authority": self.actor.authority, "kind": "work.project", "id": project}
        from herzchen.contracts import ResourceRef
        if isinstance(project, Mapping):
            selected = ResourceRef.from_dict(project)
            project = ResourceRef(selected.authority, selected.kind, selected.id).to_dict()
        task = record.get("task_ref") or (record.get("target") or {}).get("task_ref")
        attempt = record.get("assignment_ref")
        return {"project_ref": project, **({"task_ref": task} if task else {}),
            **({"attempt_ref": attempt} if attempt else {})}

    def pack_due(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Replace only native/evidence body fields, retaining typed status/identity."""
        origin = self._origin(record)
        scope = {"project_ref": origin["project_ref"], "task_ref": origin.get("task_ref"),
                 "attempt_ref": origin.get("attempt_ref")}
        # Source pins include the exact historical association in their own
        # body. Original-owner Evidence may validate foreign attention scope.
        def walk(value: Any, depth: int = 0, eligible: bool = False) -> Any:
            if depth > 32:
                raise ValueError("native envelope nesting exceeds bounds")
            if isinstance(value, Mapping):
                if value.get("schema") == SCHEMA:
                    if not value.get("inline_replacement"):
                        return dict(value)
                    if value.get("origin") != origin:
                        raise ValueError("foreign native body marker")
                    return dict(value)
                result = {key: walk(item, depth + 1, eligible or key in {
                    "raw_result", "transport_result", "task_bound_evidence", "resource_evidence",
                    "stdout", "stderr", "worker_content", "captured_artifacts"})
                    for key, item in value.items()}
            elif isinstance(value, list):
                result = [walk(item, depth + 1, eligible) for item in value]
            else:
                result = value
            # Factor large strings first, then any remaining structured body.
            # This avoids retaining duplicated native text inside a second blob
            # and also covers bodies made of many small fields/items.
            if eligible and isinstance(result, (str, Mapping, list)):
                size = len(json.dumps(result, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode())
                if size > INLINE_BYTES:
                    return {**self.retain(result, **scope), "inline_replacement": True}
            return result
        return walk(record)

    def unpack_due(self, record: Mapping[str, Any]) -> dict[str, Any]:
        origin = self._origin(record)
        def walk(value: Any, depth: int = 0) -> Any:
            if depth > 64:
                raise ValueError("retained native envelope nesting exceeds bounds")
            if isinstance(value, Mapping):
                if value.get("schema") == SCHEMA:
                    if value.get("inline_replacement") is True:
                        return walk(self.resolve(value, expected_origin=origin), depth + 1)
                    return dict(value)
                return {key: walk(item, depth + 1) for key, item in value.items()}
            if isinstance(value, list):
                return [walk(item, depth + 1) for item in value]
            return value
        return walk(record)

"""Explicit immutable instruction-document contract shared by owner and reader."""
from __future__ import annotations
import hashlib
from typing import Any, Mapping
from herzchen.contracts import canonical_json


def validate_instruction_content(content: Any) -> str:
    if not isinstance(content, Mapping) or content.get("schema") != "herzchen.instructions.v1":
        raise ValueError("instruction document schema herzchen.instructions.v1 is required")
    for field in ("name", "entrypoint", "export_manifest_digest", "instructions"):
        if not isinstance(content.get(field), str) or not content[field].strip() or "\x00" in content[field]:
            raise ValueError("instruction document requires " + field)
    if not isinstance(content.get("required"), bool) or not isinstance(content.get("supporting_refs"), list):
        raise ValueError("instruction document requires required/supporting_refs evidence")
    digest = hashlib.sha256(content["instructions"].encode("utf-8")).hexdigest()
    if content.get("bundle_digest") != digest:
        raise ValueError("instruction bytes digest mismatch")
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()

"""One stored copy of a turn's task-bound evidence.

A recorded turn keeps its ``task_bound_evidence`` once, at the top of the result.
Any other subtree of the retained transport (``raw_result``) that holds the same
value is stored as ``{"same_as": "result.task_bound_evidence", "sha256": ...}``.
Readers that verify the retained host context expand those references back, and
the digest check makes a mismatched reference fail closed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

EVIDENCE_KEY = "task_bound_evidence"
SAME_AS = "result.task_bound_evidence"


class EvidenceReferenceError(ValueError):
    """A retained evidence reference does not match the recorded evidence."""


def evidence_digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_evidence_reference(value: Any) -> bool:
    return (isinstance(value, Mapping) and set(value) == {"same_as", "sha256"}
            and value.get("same_as") == SAME_AS and isinstance(value.get("sha256"), str))


def compact_raw_result(node: Any, evidence: Any) -> Any:
    """Replace every ``task_bound_evidence`` copy equal to ``evidence`` by a reference.

    The input is not mutated. Containers are rebuilt; scalars are shared.
    """
    if not isinstance(evidence, Mapping) or not evidence:
        return node
    target = evidence_digest(evidence)
    reference = {"same_as": SAME_AS, "sha256": target}

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            rebuilt = {}
            for key, item in value.items():
                if (key == EVIDENCE_KEY and isinstance(item, Mapping) and not is_evidence_reference(item)
                        and evidence_digest(item) == target):
                    rebuilt[key] = dict(reference)
                else:
                    rebuilt[key] = walk(item)
            return rebuilt
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(node)


def expand_evidence_references(node: Any, evidence: Any) -> Any:
    """Return ``node`` with every reference replaced by the recorded evidence.

    Records written before compaction contain no references and come back unchanged.
    """
    if is_evidence_reference(node):
        if not isinstance(evidence, Mapping) or evidence_digest(evidence) != node["sha256"]:
            raise EvidenceReferenceError("retained evidence reference does not match the recorded task evidence")
        return evidence
    if isinstance(node, Mapping):
        return {key: expand_evidence_references(item, evidence) for key, item in node.items()}
    if isinstance(node, list):
        return [expand_evidence_references(item, evidence) for item in node]
    return node

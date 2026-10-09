"""Shared agent-adapter contract and D01 conformance checks.

This module is deliberately pure.  It describes the boundary between Otto's
owner records and an adapter; it does not launch a provider, persist a second
history, or decide task acceptance.  The owner remains responsible for
authentication, assignment/generation fences, custody and settlement.

The helpers are useful to both the existing Codex adapter and a future Claude
Code adapter.  They operate on retained observations and therefore make a
clear distinction between authentic qualification evidence and synthetic
negative fixtures used to prove rejection behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence


SCHEMA = "otto.agent-adapter-contract.v1"
BASELINE_SCHEMA = SCHEMA + ".baseline.v1"
PIN_FIELDS = ("recovery", "source", "runtime", "client", "resource")
CAPABILITY_STATES = frozenset({"supported", "unsupported", "degraded", "unverified"})

_OWNER_AUTHORITY = "otto-project-operating-setup-20261005-owner-v1"
_PROJECT_REF = {
    "authority": _OWNER_AUTHORITY,
    "id": "project-b429cc4a4e5709836f376f746c93",
    "kind": "work.project",
    "revision": "rev-12",
}
_TASK_REF = {
    "authority": _OWNER_AUTHORITY,
    "id": "task-8a8a794040594e239e6d0361848e",
    "kind": "work.task",
    "revision": "rev-1",
}
_SOURCE_COMMIT = "417f1a88ef21a82ce4e326a33ac22f00b7f619d6"

# This is intentionally a candidate artifact, not an owner record.  The
# Recovery pin is named by its canonical predecessor ref but remains explicit
# about the missing accepted pin/digest; no path or guessed hash is promoted to
# immutable evidence.
_D01_BASELINE = {
    "schema": BASELINE_SCHEMA,
    "artifact_id": "adapter-d01-baseline-candidate",
    "artifact_revision": "candidate-1",
    "task_ref": _TASK_REF,
    "project_ref": _PROJECT_REF,
    "source_identity": {
        "commit": _SOURCE_COMMIT,
        "workspace_role": "candidate-source",
    },
    "accepted_pins": {
        "recovery": {
            "status": "unavailable",
            "canonical_ref": {
                "authority": _OWNER_AUTHORITY,
                "id": "project-13d1139617fe76d417515b69606c",
                "kind": "work.project",
                "revision": "rev-10",
            },
            "reason": "The delivered owner context names the Recovery predecessor but does not deliver its accepted content pin or digest.",
        },
        "source": {
            "status": "accepted",
            "ref": {
                "authority": _OWNER_AUTHORITY,
                "id": "adapter-bootstrap-20261009-v1-selected-pack",
                "kind": "dat.content.document",
                "revision": "rev-1",
            },
            "sha256": "a192503f8015c42a719d9a2c6a2fd5850598f411bc43970234b1f914d28de528",
        },
        "runtime": {
            "status": "accepted",
            "ref": {
                "authority": _OWNER_AUTHORITY,
                "id": "adapter-bootstrap-20261009-v1-run-yaml",
                "kind": "dat.content.document",
                "revision": "rev-1",
            },
            "sha256": "ca43206fd199e8f2e570de492be10a02b42aba58d996f965a6ea8044ee738447",
        },
        "client": {
            "status": "accepted",
            "ref": {
                "authority": _OWNER_AUTHORITY,
                "id": "adapter-bootstrap-20261009-v1-role-configuration",
                "kind": "dat.content.document",
                "revision": "rev-1",
            },
            "sha256": "1b8622b55961e922df15ff5c21222d583fcb88ce869f85abfd3d23e8ed469134",
        },
        "resource": {
            "status": "accepted",
            "ref": {
                "authority": _OWNER_AUTHORITY,
                "id": "worker-16e9d99e102c828c4383322a",
                "kind": "dat.content.document",
                "revision": "rev-1",
            },
            "sha256": "5a8d0c43873e6259ce4f4e51e2863e46221857bbcb46bf3efd2de2d170f8cd60",
            "bundle_digest": "1238dfc46f5990330d623e5f4b62c3df50f360f2e0d86d21dafd38616c3ca253",
            "export_manifest_digest": "a92c30517c5544a930da5eb248eca8e5feec1b0577aab571b23cfe1139634325",
        },
    },
    "compatible_overlap": {
        "basis": "owner-adopted supporting refs in the delivered role brief",
        "recovery": {
            "status": "unavailable",
            "reason": "No accepted predecessor pin was delivered; compatibility is not inferred.",
        },
        "source": {
            "status": "compatible", "basis": "exact ref, revision and digest",
            "ref": {"authority": _OWNER_AUTHORITY, "id": "adapter-bootstrap-20261009-v1-selected-pack", "kind": "dat.content.document", "revision": "rev-1"},
            "sha256": "a192503f8015c42a719d9a2c6a2fd5850598f411bc43970234b1f914d28de528",
        },
        "runtime": {
            "status": "compatible", "basis": "exact ref, revision and digest",
            "ref": {"authority": _OWNER_AUTHORITY, "id": "adapter-bootstrap-20261009-v1-run-yaml", "kind": "dat.content.document", "revision": "rev-1"},
            "sha256": "ca43206fd199e8f2e570de492be10a02b42aba58d996f965a6ea8044ee738447",
        },
        "client": {
            "status": "compatible", "basis": "exact ref, revision and digest",
            "ref": {"authority": _OWNER_AUTHORITY, "id": "adapter-bootstrap-20261009-v1-role-configuration", "kind": "dat.content.document", "revision": "rev-1"},
            "sha256": "1b8622b55961e922df15ff5c21222d583fcb88ce869f85abfd3d23e8ed469134",
        },
        "resource": {
            "status": "compatible", "basis": "exact ref, revision and digest",
            "ref": {"authority": _OWNER_AUTHORITY, "id": "worker-16e9d99e102c828c4383322a", "kind": "dat.content.document", "revision": "rev-1"},
            "sha256": "5a8d0c43873e6259ce4f4e51e2863e46221857bbcb46bf3efd2de2d170f8cd60",
        },
    },
    "seams": {
        "result": {
            "state": "available",
            "source_paths": ["src/otto/agents/gateway.py", "src/otto/portfolio/execution_operations.py"],
            "fact": "existing owner attempt/result observations; no parallel history store",
        },
        "artifact": {
            "state": "available",
            "source_paths": ["src/otto/agents/gateway.py", "src/otto/portfolio/execution_operations.py"],
            "fact": "known owner-retained artifacts only; bounded reads require authorization",
        },
        "usage": {
            "state": "observed-or-unavailable",
            "source_paths": ["src/herzchen/adapters/receipt.py"],
            "fact": "native host evidence may expose per-invocation usage; no guessed totals, price or descendant sums",
        },
        "delivery": {
            "state": "available",
            "source_paths": ["src/otto/agents/gateway.py", "src/otto/portfolio/execution.py"],
            "fact": "existing owner Due/report receipts and disposition identity",
        },
    },
    "qualification": {
        "source_backed": True,
        "authentic_qualification": {
            "codex": "preserved-common-invariants-only",
            "claude-code": "not-established",
        },
        "synthetic_negative_suite": {
            "state": "available",
            "evidence_kind": "synthetic-negative-fixtures",
            "checks": ["insufficient surface", "identity collision", "missing native proof", "changed input/parent", "forged caller", "duplicate effects"],
        },
        "known_limits": [
            "manager-only native caller authorization is established; worker child authority is not inferred",
            "installed run-worker compatibility file IPC is not native caller authentication",
            "workers[task] is task-indexed current state, not a child occurrence registry",
            "external desktop/provider sessions do not establish Otto admission, custody, or historical attribution",
            "OMP is unspecified and unqualified",
        ],
        "frontends": {
            "manager-owner": "supported",
            "coordinating-worker": "required-but-not-established",
            "compatibility-file-ipc": "observed-transport-only",
            "external-desktop-session": "observation-only",
        },
    },
}

CLI_CONTRACT = {
    "schema": SCHEMA + ".cli.v1",
    "identity": {
        "occurrence": "durable assignment/generation/request identity retained by the owner",
        "transport": ("outer_command", "start", "callback"),
        "rule": "transport handles never replace the durable occurrence handle",
    },
    "operations": {
        "launch": {"command": "run-worker", "effect": "admit-and-start", "required": ("task", "route", "principal", "request_key", "focus")},
        "transport-status": {"command": "command-status", "effect": "pure-read", "required": ("request_id",)},
        "occurrence-lookup": {"command": "lookup-occurrence", "effect": "pure-read", "required": ("scope", "request_key", "request_input"), "required_addition": True},
        "follow": {"command": "follow-occurrence", "effect": "pure-read", "required": ("occurrence", "timeout_seconds"), "required_addition": True},
        "result": {"command": "read-result", "effect": "pure-read", "required": ("occurrence",), "required_addition": True},
        "artifact": {"command": "read-artifact", "effect": "pure-read", "required": ("occurrence", "known_artifact_ref", "max_bytes"), "required_addition": True},
        "control": {"command": "execution-control", "effect": "explicit-owner-operation", "required": ("operation", "occurrence")},
    },
    "invariants": {
        "lookup": "exact scope/request input; missing or ambiguous is actionable and never launches",
        "parent": "immutable parent assignment/generation/occurrence/result destination binding",
        "result": "bounded attributed conclusion, verification, blockers, refs and explicit absence",
        "delivery": "result/disposition revision identity is deterministic; repeats have no duplicate effect",
    },
}


class AdapterContractError(ValueError):
    """A contract, retained observation, or conformance fixture is invalid."""


class AdapterConformanceFailure(AssertionError):
    """A negative fixture was accepted or a required invariant was missing."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _json(value: Any) -> Any:
    """Convert existing refs/dataclasses to finite JSON without owning them."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json(to_dict())
    raise AdapterContractError(f"value is not JSON-compatible: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def d01_baseline_artifact() -> dict[str, Any]:
    """Return the source-backed D01 baseline candidate with its content digest."""

    artifact = _json(_D01_BASELINE)
    artifact["artifact_sha256"] = digest(artifact)
    return artifact


def validate_d01_baseline_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the bounded baseline without reading or mutating owner state."""

    artifact = _json(value)
    if not isinstance(artifact, Mapping) or artifact.get("schema") != BASELINE_SCHEMA:
        raise AdapterContractError("unsupported D01 baseline artifact")
    if artifact.get("artifact_sha256") != digest({key: item for key, item in artifact.items() if key != "artifact_sha256"}):
        raise AdapterContractError("D01 baseline artifact digest is inconsistent")
    if artifact.get("project_ref") != _PROJECT_REF or artifact.get("task_ref") != _TASK_REF:
        raise AdapterContractError("D01 baseline is bound to the wrong canonical project or task")
    source_identity = artifact.get("source_identity")
    if not isinstance(source_identity, Mapping) or source_identity.get("commit") != _SOURCE_COMMIT:
        raise AdapterContractError("D01 baseline source identity is not pinned")

    pins = artifact.get("accepted_pins")
    if not isinstance(pins, Mapping) or set(pins) != set(PIN_FIELDS):
        raise AdapterContractError("D01 baseline does not record all accepted pin categories")
    recovery = pins["recovery"]
    if not isinstance(recovery, Mapping) or recovery.get("status") != "unavailable":
        raise AdapterContractError("missing Recovery unavailable disposition")
    _ref(recovery.get("canonical_ref"), "accepted_pins.recovery.canonical_ref", revision_required=True)
    _text(recovery.get("reason"), "accepted_pins.recovery.reason")
    accepted: dict[str, dict[str, Any]] = {}
    for category in PIN_FIELDS[1:]:
        pin = pins[category]
        if not isinstance(pin, Mapping) or pin.get("status") != "accepted":
            raise AdapterContractError(f"{category} pin is not accepted")
        accepted[category] = {"ref": pin.get("ref"), "sha256": pin.get("sha256")}
        normalize_pins({category: accepted[category]}, required=(category,))
        if category == "resource":
            _sha256(pin.get("bundle_digest"), "resource.bundle_digest")
            _sha256(pin.get("export_manifest_digest"), "resource.export_manifest_digest")

    overlap = artifact.get("compatible_overlap")
    if not isinstance(overlap, Mapping) or overlap.get("recovery", {}).get("status") != "unavailable":
        raise AdapterContractError("D01 baseline does not show Recovery overlap as unavailable")
    for category in PIN_FIELDS[1:]:
        item = overlap.get(category)
        if not isinstance(item, Mapping) or item.get("status") != "compatible":
            raise AdapterContractError(f"D01 baseline is missing compatible {category} overlap")
        if item.get("ref") != accepted[category]["ref"] or item.get("sha256") != accepted[category]["sha256"]:
            raise AdapterContractError(f"D01 baseline {category} overlap is not exact")

    qualification = artifact.get("qualification")
    if not isinstance(qualification, Mapping) or qualification.get("source_backed") is not True:
        raise AdapterContractError("D01 qualification is not source-backed")
    authentic = qualification.get("authentic_qualification")
    if not isinstance(authentic, Mapping) or authentic.get("claude-code") != "not-established":
        raise AdapterContractError("D01 baseline does not distinguish authentic Claude qualification")
    negatives = qualification.get("synthetic_negative_suite")
    if not isinstance(negatives, Mapping) or negatives.get("evidence_kind") != "synthetic-negative-fixtures":
        raise AdapterContractError("D01 negative evidence is not classified as synthetic")
    return artifact


def cli_contract() -> dict[str, Any]:
    """Return the reusable CLI contract without exposing mutable module state."""

    return _json(CLI_CONTRACT)


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AdapterContractError(f"{field_name} must be non-blank text")
    return value.strip()


def _sha256(value: Any, field_name: str) -> str:
    value = _text(value, field_name).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AdapterContractError(f"{field_name} must be a SHA-256 hex digest")
    return value


def _ref(value: Any, field_name: str, *, revision_required: bool = False) -> dict[str, Any]:
    value = _json(value)
    if not isinstance(value, Mapping):
        raise AdapterContractError(f"{field_name} must be a reference object")
    result = dict(value)
    for name in ("authority", "kind", "id"):
        _text(result.get(name), f"{field_name}.{name}")
    if revision_required:
        _text(result.get("revision"), f"{field_name}.revision")
    elif result.get("revision") is not None:
        _text(result["revision"], f"{field_name}.revision")
    return result


def reference_identity(value: Any) -> tuple[str, str, str]:
    ref = _ref(value, "reference")
    return ref["authority"], ref["kind"], ref["id"]


def normalize_pins(value: Mapping[str, Any], *, required: Sequence[str] = PIN_FIELDS) -> dict[str, dict[str, Any]]:
    """Validate accepted Recovery/source/runtime/client/resource pins.

    A pin is an immutable reference plus its content digest.  A path is
    allowed as explanatory provenance only; it is never used as identity.
    """

    if not isinstance(value, Mapping):
        raise AdapterContractError("accepted pins must be an object")
    required_set = set(required)
    unknown = set(value) - set(PIN_FIELDS)
    if unknown:
        raise AdapterContractError("unsupported pin categories: " + ", ".join(sorted(unknown)))
    missing = required_set - set(value)
    if missing:
        raise AdapterContractError("missing accepted pins: " + ", ".join(sorted(missing)))
    result: dict[str, dict[str, Any]] = {}
    for category, raw in value.items():
        if not isinstance(raw, Mapping):
            raise AdapterContractError(f"{category} pin must be an object")
        ref = _ref(raw.get("ref", raw.get("resource_ref")), f"{category}.ref", revision_required=True)
        item = {"ref": ref, "sha256": _sha256(raw.get("sha256", raw.get("content_sha256")), f"{category}.sha256")}
        if raw.get("path") is not None:
            item["path"] = _text(raw["path"], f"{category}.path")
        if raw.get("version") is not None:
            item["version"] = _text(raw["version"], f"{category}.version")
        result[category] = item
    return result


def subtract_compatible_overlap(
    candidate: Mapping[str, Any], established: Mapping[str, Any], *, required: Sequence[str] = PIN_FIELDS
) -> dict[str, Any]:
    """Remove exact established pins while retaining conflicts explicitly.

    Equal bytes and equal immutable refs are compatible overlap.  A category
    with the same reference but a different digest/revision is a conflict, not
    something that may be silently replaced by the candidate.
    """

    current = normalize_pins(candidate, required=required)
    prior = normalize_pins(established, required=())
    remaining: dict[str, dict[str, Any]] = {}
    overlap: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, dict[str, Any]] = {}
    for category, pin in current.items():
        old = prior.get(category)
        if old is None:
            remaining[category] = pin
            continue
        if old == pin or (old["ref"] == pin["ref"] and old["sha256"] == pin["sha256"]):
            overlap[category] = pin
        else:
            conflicts[category] = {"candidate": pin, "established": old}
    return {"schema": SCHEMA + ".pin-overlap.v1", "remaining": remaining, "overlap": overlap, "conflicts": conflicts}


def scope_identity(
    *, project_ref: Mapping[str, Any], task_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
    generation: int, parent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable occurrence scope used for exact lookup/replay."""

    if type(generation) is not int or generation < 1:
        raise AdapterContractError("generation must be a positive integer")
    value: dict[str, Any] = {
        "project_ref": _ref(project_ref, "project_ref"),
        "task_ref": _ref(task_ref, "task_ref"),
        "assignment_ref": _ref(assignment_ref, "assignment_ref"),
        "generation": generation,
    }
    if parent is not None:
        value["parent"] = parent_binding(parent)
    return value


def request_fingerprint(scope: Mapping[str, Any], request_input: Any) -> str:
    """Hash exact scope and admitted input; caller labels are not authority."""

    return digest({"scope": _json(scope), "input": _json(request_input)})


def validate_native_proof(
    proof: Mapping[str, Any], *, scope: Mapping[str, Any], request_input: Any,
) -> dict[str, Any]:
    """Require an observed native identity before useful adapter effects."""

    if not isinstance(proof, Mapping):
        raise AdapterConformanceFailure("missing_native_proof", "useful admission has no native proof")
    adapter = _text(proof.get("adapter"), "native_proof.adapter")
    session_id = _text(proof.get("session_id"), "native_proof.session_id")
    if proof.get("useful") is not True:
        raise AdapterConformanceFailure("missing_native_proof", "native initializer proof is not useful admission")
    if proof.get("scope_digest") != digest(scope):
        raise AdapterConformanceFailure("native_scope_mismatch", "native proof scope differs from admitted scope")
    if proof.get("input_digest") != digest(request_input):
        raise AdapterConformanceFailure("native_input_mismatch", "native proof input differs from admitted input")
    return {"adapter": adapter, "session_id": session_id, "useful": True,
            "scope_digest": proof["scope_digest"], "input_digest": proof["input_digest"]}


def validate_caller_claims(context: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Check optional caller echoes against trusted host context.

    The context is supplied by the host binding.  Request JSON can only agree
    with it; it cannot establish or replace authentication.
    """

    if not isinstance(context, Mapping) or not isinstance(request, Mapping):
        raise AdapterConformanceFailure("forged_caller", "caller context and request must be objects")
    native = context.get("native_identity") if isinstance(context.get("native_identity"), Mapping) else {}
    expected = {
        "caller_principal": context.get("principal"),
        "logical_agent_id": context.get("principal"),
        "caller_assignment_ref": context.get("assignment_ref"),
        "caller_generation": context.get("generation"),
        "caller_native_session_id": native.get("session_id"),
    }
    for key, value in expected.items():
        if key in request and _json(request[key]) != _json(value):
            raise AdapterConformanceFailure("forged_caller", "caller claim conflicts with trusted host binding", field=key)
    if "caller_context" in request or "host_caller_binding" in request:
        raise AdapterConformanceFailure("forged_caller", "caller binding must come from the host ingress")
    return {key: value for key, value in request.items() if key not in expected}


def parent_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the minimal immutable parent/result-destination binding."""

    if not isinstance(value, Mapping):
        raise AdapterContractError("parent binding must be an object")
    result = {
        "assignment_ref": _ref(value.get("assignment_ref"), "parent.assignment_ref"),
        "generation": value.get("generation"),
        "occurrence_ref": _ref(value.get("occurrence_ref"), "parent.occurrence_ref"),
        "result_destination": _ref(value.get("result_destination"), "parent.result_destination"),
    }
    if type(result["generation"]) is not int or result["generation"] < 1:
        raise AdapterContractError("parent.generation must be a positive integer")
    return result


def validate_parent_binding(observation: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    actual = observation.get("parent")
    if parent_binding(actual) != parent_binding(expected):
        raise AdapterConformanceFailure("parent_binding_mismatch", "result parent binding is not immutable", expected=expected, actual=actual)


def exact_lookup(
    records: Iterable[Mapping[str, Any]], *, scope: Mapping[str, Any], request_key: str,
    request_input: Any | None = None,
) -> dict[str, Any]:
    """Pure exact historical lookup; it never launches or reconciles."""

    key = _text(request_key, "request_key")
    expected_fingerprint = request_fingerprint(scope, request_input) if request_input is not None else None
    records = list(records)
    matches = []
    for record in records:
        if not isinstance(record, Mapping) or record.get("request_key") != key:
            continue
        if record.get("scope") != _json(scope):
            continue
        if expected_fingerprint is not None and record.get("request_fingerprint") != expected_fingerprint:
            continue
        matches.append(record)
    if not matches:
        conflict = any(isinstance(record, Mapping) and record.get("request_key") == key for record in records)
        return {
            "schema": SCHEMA + ".lookup.v1", "outcome": "conflict" if conflict else "missing",
            "pure": True, "request_key": key,
            "next_action": "reconcile the retained occurrence or report missing/ambiguous; do not submit a fresh key",
        }
    if len(matches) != 1:
        return {"schema": SCHEMA + ".lookup.v1", "outcome": "ambiguous", "pure": True,
                "request_key": key, "match_count": len(matches),
                "next_action": "use owner reconciliation to resolve the exact retained occurrence"}
    return {"schema": SCHEMA + ".lookup.v1", "outcome": "found", "pure": True,
            "request_key": key, "occurrence": _json(matches[0])}


def delivery_identity(result_ref: Any, disposition_revision: Any) -> str:
    """Stable callback identity for one authoritative result disposition."""

    _ref(result_ref, "result_ref")
    _text(disposition_revision, "disposition_revision")
    return "delivery-" + digest({"result_ref": _json(result_ref), "disposition_revision": disposition_revision})


def bounded_result_view(observation: Mapping[str, Any], *, max_conclusion: int = 4096) -> dict[str, Any]:
    """Project retained facts without parsing arbitrary logs or inventing proof."""

    if not isinstance(observation, Mapping):
        raise AdapterContractError("result observation must be an object")
    if type(max_conclusion) is not int or max_conclusion < 1:
        raise AdapterContractError("max_conclusion must be positive")
    conclusion = observation.get("conclusion")
    if isinstance(conclusion, str):
        conclusion = conclusion[:max_conclusion]
    elif conclusion is not None:
        conclusion = None
    refs = observation.get("refs") if isinstance(observation.get("refs"), Mapping) else {}
    usage = observation.get("usage") if isinstance(observation.get("usage"), Mapping) else None
    return {
        "schema": SCHEMA + ".result-view.v1",
        "pure": True,
        "freshness": observation.get("freshness"),
        "useful_admission": observation.get("useful_admission"),
        "native_identity": observation.get("native_identity"),
        "native_terminal": observation.get("native_terminal"),
        "required_capture": observation.get("required_capture"),
        "occurrence_settlement": observation.get("occurrence_settlement"),
        "parent_delivery": observation.get("parent_delivery"),
        "task_acceptance": observation.get("task_acceptance"),
        "outcome": observation.get("outcome"),
        "conclusion": conclusion,
        "verification": observation.get("verification"),
        "blockers": observation.get("blockers", []),
        "refs": {name: refs.get(name) for name in ("result", "artifact", "log", "transcript") if name in refs},
        "usage": usage,
        "usage_unavailable_reason": observation.get("usage_unavailable_reason"),
    }


def capability_inventory() -> dict[str, Any]:
    """Source-backed D01 baseline; unknown capabilities fail closed."""

    return {
        "schema": SCHEMA + ".capabilities.v1",
        "adapters": {
            "codex": {
                "qualification": "preserved-common-invariants",
                "capabilities": {
                    "owner_admission": "supported", "native_identity": "supported",
                    "bounded_result": "supported", "known_artifact_read": "supported",
                    "native_attach": "unverified", "native_cancel": "unverified",
                    "native_child": "unsupported",
                },
                "evidence": ["src/otto/agents/gateway.py", "src/otto/agents/herzchen_adapter.py", "src/otto/portfolio/identity_context.py"],
            },
            "claude-code": {
                "qualification": "selected-useful-worker-pending-authentic-vertical-slice",
                "capabilities": {name: "unverified" for name in (
                    "owner_admission", "native_identity", "bounded_result", "known_artifact_read",
                    "native_stream", "native_attach", "native_resume", "native_cancel", "native_child",
                )},
                "evidence": [],
            },
        },
        "current_limits": [
            "manager-only native caller authorization is established; worker child authority is not inferred",
            "installed run-worker compatibility file IPC is not native caller authentication",
            "workers[task] is task-indexed current state, not a child occurrence registry",
            "external desktop/provider sessions do not establish Otto admission, custody, or historical attribution",
            "OMP is unspecified and unqualified",
        ],
        "seams": {
            "result": {"state": "available", "source": "src/otto/agents/gateway.py:AttemptEnvelope and owner attempt capture"},
            "artifact": {"state": "available", "source": "src/otto/agents/gateway.py and src/otto/portfolio/execution_operations.py"},
            "usage": {"state": "observed-or-unavailable", "source": "native host evidence in src/herzchen/adapters/receipt.py", "limits": "no guessed totals, price, or descendant sums"},
            "delivery": {"state": "available", "source": "existing owner Due/report receipts"},
        },
        "frontends": {
            "manager-owner": {"state": "supported", "source": "owner-bound installed manager client"},
            "coordinating-worker": {"state": "required-but-not-established", "source": "current manager-only native caller ingress"},
            "compatibility-file-ipc": {"state": "observed-transport-only", "source": "installed run-worker path; not caller authentication"},
            "external-desktop-session": {"state": "observation-only", "source": "external session cannot establish Otto custody"},
        },
    }


@dataclass(frozen=True)
class ConformanceCase:
    name: str
    layer: str
    authentic: bool
    check: Callable[[Any], None]


@dataclass
class ConformanceReport:
    """Machine-readable result of the bounded D01 checks."""

    passed: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    evidence_kind: str = "synthetic-negative-fixtures"

    @property
    def outcome(self) -> str:
        return "passed" if not self.failures else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".report.v1", "outcome": self.outcome,
                "passed": list(self.passed), "failures": list(self.failures),
                "evidence_kind": self.evidence_kind}


class AdapterSurface(Protocol):
    """Minimal duck-typed surface required by the reusable contract."""

    def launch(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def lookup(self, scope: Mapping[str, Any], request_key: str, request_input: Any = None) -> Mapping[str, Any]: ...
    def result(self, occurrence: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _check_surface(adapter: Any) -> None:
    for method in ("launch", "lookup", "result"):
        if not callable(getattr(adapter, method, None)):
            raise AdapterConformanceFailure("insufficient_adapter", f"adapter lacks required {method} operation")


def _check_launch_identity(adapter: AdapterSurface, request: Mapping[str, Any]) -> None:
    receipt = adapter.launch(request)
    if not isinstance(receipt, Mapping):
        raise AdapterConformanceFailure("missing_launch_receipt", "launch did not return a retained receipt")
    occurrence = receipt.get("occurrence")
    if not isinstance(occurrence, Mapping) or not occurrence.get("schedule_id"):
        raise AdapterConformanceFailure("missing_occurrence_identity", "launch lacks a durable occurrence identity")
    transport = [receipt.get(name) for name in ("outer_command", "start", "callback")]
    if any(value is None for value in transport):
        raise AdapterConformanceFailure("missing_transport_identity", "launch must label outer/start/callback handles")
    if len({json.dumps(_json(value), sort_keys=True) for value in transport}) != len(transport):
        raise AdapterConformanceFailure("identity_collision", "durable occurrence and transport identities must remain distinct")
    validate_native_proof(receipt.get("native_proof"), scope=request["scope"], request_input=request["input"])


def _check_lookup_is_exact(adapter: AdapterSurface, request: Mapping[str, Any]) -> None:
    scope = request["scope"]
    key = request["request_key"]
    input_value = request["input"]
    first = adapter.lookup(scope, key, input_value)
    second = adapter.lookup(scope, key, input_value)
    if _json(first) != _json(second):
        raise AdapterConformanceFailure("lookup_not_deterministic", "exact lookup changed between pure reads")
    changed = adapter.lookup(scope, key, {**input_value, "changed": True})
    if changed.get("outcome") not in {"conflict", "missing", "ambiguous"}:
        raise AdapterConformanceFailure("changed_input_accepted", "changed input reused the original request key")
    changed_scope = dict(scope)
    changed_scope["generation"] = scope["generation"] + 1
    changed_parent = adapter.lookup(changed_scope, key, input_value)
    if changed_parent.get("outcome") not in {"conflict", "missing", "ambiguous"}:
        raise AdapterConformanceFailure("changed_parent_accepted", "changed parent/generation reused the original request key")


def _check_forged_caller_is_rejected(adapter: AdapterSurface, request: Mapping[str, Any]) -> None:
    context = request.get("caller_context")
    if not isinstance(context, Mapping):
        raise AdapterConformanceFailure("missing_caller_context_fixture", "conformance request needs trusted caller context")
    forged = dict(request)
    forged["caller_principal"] = "forged-caller"
    try:
        result = adapter.launch(forged)
    except (AdapterContractError, AdapterConformanceFailure, PermissionError):
        return
    if not isinstance(result, Mapping) or result.get("outcome") not in {"denied", "conflict", "unsupported", "error"}:
        raise AdapterConformanceFailure("forged_caller_accepted", "forged caller claims reached useful adapter work")


def _check_result_is_bounded(adapter: AdapterSurface, request: Mapping[str, Any]) -> None:
    receipt = adapter.launch(request)
    occurrence = receipt.get("occurrence") if isinstance(receipt, Mapping) else None
    if not isinstance(occurrence, Mapping):
        raise AdapterConformanceFailure("missing_occurrence_identity", "result check has no occurrence")
    value = adapter.result(occurrence)
    if not isinstance(value, Mapping) or value.get("pure") is not True:
        raise AdapterConformanceFailure("result_not_pure", "result read must be a bounded pure observation")


def _check_duplicate_effects_are_replayed(adapter: AdapterSurface, request: Mapping[str, Any]) -> None:
    first = adapter.launch(request)
    effects_before = getattr(adapter, "effect_count", None)
    second = adapter.launch(request)
    effects_after = getattr(adapter, "effect_count", None)
    if isinstance(effects_before, int) and isinstance(effects_after, int):
        if effects_after != effects_before:
            raise AdapterConformanceFailure("duplicate_effect", "reusing an exact request key repeated provider effects")
    elif not isinstance(second, Mapping) or second.get("replayed") is not True:
        raise AdapterConformanceFailure("duplicate_effect_unproven", "duplicate launch lacks a replay marker or effect counter")
    if isinstance(first, Mapping) and isinstance(second, Mapping) and first.get("occurrence") != second.get("occurrence"):
        raise AdapterConformanceFailure("occurrence_replaced", "replay returned a new occurrence identity")


def conformance_cases(request: Mapping[str, Any]) -> tuple[ConformanceCase, ...]:
    return (
        ConformanceCase("surface", "contract", False, lambda adapter: _check_surface(adapter)),
        ConformanceCase("launch-identity", "transport", False, lambda adapter: _check_launch_identity(adapter, request)),
        ConformanceCase("exact-lookup", "owner", False, lambda adapter: _check_lookup_is_exact(adapter, request)),
        ConformanceCase("forged-caller", "owner", False, lambda adapter: _check_forged_caller_is_rejected(adapter, request)),
        ConformanceCase("duplicate-effects", "owner", False, lambda adapter: _check_duplicate_effects_are_replayed(adapter, request)),
        ConformanceCase("bounded-result", "workflow", False, lambda adapter: _check_result_is_bounded(adapter, request)),
    )


def run_conformance(adapter: Any, *, request: Mapping[str, Any], authentic: bool = False) -> ConformanceReport:
    """Run the small common suite and retain the evidence classification.

    ``authentic=False`` is the default because ordinary D01 fixtures are
    synthetic negatives.  A real installed journey must opt into the
    ``authentic`` label at the caller; this function does not infer it from a
    successful method call.
    """

    report = ConformanceReport(evidence_kind="authentic-qualification" if authentic else "synthetic-negative-fixtures")
    for case in conformance_cases(request):
        try:
            case.check(adapter)
        except (AdapterContractError, AdapterConformanceFailure, KeyError, TypeError, AttributeError) as exc:
            report.failures.append({"case": case.name, "layer": case.layer,
                                    "code": getattr(exc, "code", "check_failed"), "message": str(exc),
                                    "authentic": authentic})
        else:
            report.passed.append(case.name)
    return report


__all__ = [
    "SCHEMA", "BASELINE_SCHEMA", "PIN_FIELDS", "CAPABILITY_STATES", "CLI_CONTRACT", "AdapterContractError", "AdapterConformanceFailure",
    "AdapterSurface", "ConformanceCase", "ConformanceReport", "canonical_json", "digest", "cli_contract",
    "d01_baseline_artifact", "validate_d01_baseline_artifact",
    "normalize_pins", "subtract_compatible_overlap", "scope_identity", "request_fingerprint",
    "parent_binding", "validate_parent_binding", "validate_native_proof", "validate_caller_claims",
    "exact_lookup", "delivery_identity",
    "bounded_result_view", "capability_inventory", "conformance_cases", "run_conformance",
]

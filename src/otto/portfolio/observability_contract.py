"""The bounded Events contract and its predecessor seams.

This module is deliberately a contract, not an event store or a reader.  It
records the source/runtime/resource identities qualified for the Events
successor and gives later implementation work one place to validate the
bounded query and detail surface.  FND remains the authoritative event
ledger; Due/Recovery remains the custody and reconciliation owner; Evidence
remains the publication, range, and detail resolver.

The ``ObservationRef`` type is intentionally reference-only.  It lets the
future Usage/cost successor attach a typed observation facet to an Events
history row without creating a second event ledger, parser, accounting path,
or per-view table.  Events does not calculate usage, spans, money, or totals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Mapping, Optional, Sequence, Tuple

from herzchen.contracts import ResourceRef


CONTRACT_SCHEMA = "otto.events.contract.v1"
CONTRACT_REVISION = "events-d01.v1"
SOURCE_COMMIT = "f7bbb885e0dd093b83c83e9cf684f91d5d4e95e3"
CANDIDATE_ROOT = (
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
    "otto-events-observability-20261010/work/integration-owner"
)
SELECTED_PACK_ROOT = (
    "/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/"
    "otto-events-observability-20261010/controller/selected-pack-source"
)

RUNTIME_PIN = {
    "interpreter": "/usr/bin/python3",
    "version": "3.9.6",
    "model": "gpt-5.6-luna",
    "reasoning": "high",
    "profile": "workspace-write",
    "adapter": "otto.events.installed-codex-cli.v1",
    "command": "PYTHONPATH=src /usr/bin/python3 -m unittest discover -s src/otto/portfolio/tests -p 'test_observability_contract.py' -v",
}

# These are immutable resource identities delivered with the assignment.  The
# paths are retained because adoption must be checked at a safe boundary; the
# digests, not a mutable copied file, establish the resource content.
RESOURCE_PINS = {
    "selected_pack": {
        "root": SELECTED_PACK_ROOT,
        "pack_path": SELECTED_PACK_ROOT + "/policy-staging/megado/pack.yaml",
        "pack_sha256": "28c9de840bb71fe814abd4f537b9e620234763511d5c5cf55173dae1b3a6813f",
        "pack_version": "1.2.2",
        "protocol_version": "1.2.0",
        "source_commit": SOURCE_COMMIT,
    },
    "megado_skill": {
        "path": SELECTED_PACK_ROOT + "/policy-staging/megado/skill/SKILL.md",
        "sha256": "06e3af1354ce56bfe9725fb5bdfd08d43cd753b14f5f56d7a5da8e09e00145bf",
    },
    "run_configuration": {
        "path": CANDIDATE_ROOT.rsplit("/work/", 1)[0] + "/run.yaml",
        "sha256": "fb1ea41374c9692392d79278df4ec5e20cedfede99d49c0c2d1c16034171e07f",
        "content_sha256": "12a1e87d3164b8c47041370cef6726fc230528c48b3b1592937bc7de99a0e04f",
    },
    "worker_brief": {
        "resource_ref": "worker-aeb01ebb22ac7ff2eb9c3704",
        "bundle_sha256": "1fbe3e27837760b0b546193bc921f51fbe602079e2a361da9b9f4604e3c1da98",
        "export_manifest_sha256": "44c322072939e8e23832f2dfa26361172be380590c22e11990e673652ebfae0e",
    },
    "predecessor_terminal": {
        "resource_ref": "events-bootstrap-20261010-v1-predecessor-terminal",
        "content_sha256": "853d6cfa817db00429541b15e4c9f9648bdefdc7bb5bef0b0b62e19ac1fb37e8",
    },
}


class ObservabilityContractError(ValueError):
    """A contract value is malformed or exceeds the Events qualification."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NON_BLANK = re.compile(r"\S")


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _NON_BLANK.search(value) or "\x00" in value:
        raise ObservabilityContractError(f"{field_name} must be non-blank text")
    return value


def _digest(value: Any, field_name: str) -> str:
    value = _text(value, field_name).lower()
    if not _SHA256.fullmatch(value):
        raise ObservabilityContractError(f"{field_name} must be a SHA-256 digest")
    return value


def _ref(value: Any, field_name: str) -> ResourceRef:
    if isinstance(value, ResourceRef):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceRef.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservabilityContractError(f"{field_name} is not a ResourceRef") from exc
    raise ObservabilityContractError(f"{field_name} is not a ResourceRef")


def _iso(value: Any, field_name: str) -> str:
    value = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservabilityContractError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ObservabilityContractError(f"{field_name} must include a timezone")
    return value


@dataclass(frozen=True)
class SourcePin:
    """One source seam at the qualified Events baseline."""

    path: str
    sha256: str
    owner: str
    purpose: str

    def __post_init__(self) -> None:
        _text(self.path, "source path")
        _digest(self.sha256, "source sha256")
        _text(self.owner, "source owner")
        _text(self.purpose, "source purpose")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "owner": self.owner, "purpose": self.purpose}


# Exact source seams used by D01.  The path is relative to the candidate root
# so the contract remains portable while the candidate root pin above records
# the physical source custody.
SOURCE_SEAMS: Tuple[SourcePin, ...] = (
    SourcePin("src/herzchen/kernel/schema.py", "bb4932f4a023a4a0c3ea8893ae1185f6347b870e9136c236c0b2c8247b8a32bc", "FND", "composition and fingerprint admission"),
    SourcePin("src/herzchen/kernel/store.py", "63ac97e0c9d70526c8a095094e4a8a4bc3cc69068e069b0e60bb6be049ddd7a7", "FND", "transaction, event ordering, receipts and bounded identity reads"),
    SourcePin("src/herzchen/kernel/recovery.py", "97830dfcb02b324677df53dc54c4b0cba1769e86d814678ce583ba067e20e205", "Recovery", "closed-owner snapshot, custody and reconciliation primitives"),
    SourcePin("src/otto/attention.py", "a06932c793471b2d68c913702cb10e951c6d7f55a28b0418aebd39f385d5f395", "Due", "retained attempts, attention and current Due records"),
    SourcePin("src/otto/portfolio/execution.py", "7abe74ab287f1d2af1f91b2cf2b4f0fbe0977abc1269c02e3f1a1f7617cc3798", "WRK/Due", "compact result/status projection and execution custody"),
    SourcePin("src/herzchen/domains/work/module.py", "6359925d2219bc7ef1f88af974aa2607736663d9c7247b9c4b974cc740bbe203", "WRK", "work identity and mutation seams"),
    SourcePin("src/herzchen/domains/work/lifecycle.py", "00c48d42cda4879f4045cf728d5551b631370cfe700faf89b71d6dcce8adad88", "WRK", "lifecycle transitions"),
    SourcePin("src/herzchen/domains/work/batches.py", "7aa65853add6324a65adac76665d698a75d49fe96dac06fa766b7b8970b0dfaa", "WRK", "project-sheet batch and child mapping"),
    SourcePin("src/herzchen/domains/work/assignments.py", "4cbb30c7fcf0b3c7018bc90bf129d7fadf768cee8698c79271f8bc5d9195692e", "WRK", "assignment responsibility and generation"),
    SourcePin("src/herzchen/evidence/model.py", "ab8bb2940f4c2ead59e8009881b7b452ac8cc1471a428f846230c2636fb37c27", "Evidence", "managed manifest, resource pins and availability"),
    SourcePin("src/herzchen/evidence/commands.py", "b4054a25245811d720b2d8a0e20f980ae8b8dbc54c583d17accf4d7a58b1f7a7", "Evidence", "publication, range and authorized detail resolution"),
)


HISTORICAL_FIELDS: Tuple[str, ...] = (
    "affected_refs_and_revisions",
    "before_after_parent_membership",
    "before_after_project_membership",
    "lifecycle_and_status",
    "assignment_responsibility_and_generation",
    "typed_relation_changes",
    "source_append_position",
    "stream_sequence",
    "transaction_id",
    "recorded_at",
    "qualified_occurrence_at_optional",
    "bounded_typed_summary",
    "exact_detail_locator",
)

HISTORY_FACETS: Tuple[str, ...] = (
    "creation_or_revision",
    "lifecycle_transition",
    "project_sheet_batch_child",
    "replacement_or_adoption",
    "retained_attempt_or_result",
    "blocker_fact",
)

LEGACY_GAP_RULES: Tuple[str, ...] = (
    "track_missing_coverage_by_field_and_source_range",
    "capture_baselines_establish_state_only_at_capture_time",
    "missing_membership_is_unknown_not_silently_inactive",
    "legacy_migration_preserves_stream_order_but_does_not_invent_cross_stream_chronology",
    "projection_rows_never_replace_authoritative_source_history",
    "Evidence_unavailability_or_purge_does_not_erase_retained_decisions_or_summaries",
)


@dataclass(frozen=True)
class ReadLimits:
    """Independent limits applied before hydration and detail resolution."""

    default_rows: int = 50
    max_rows: int = 200
    max_metadata_candidates: int = 1000
    max_detail_bytes: int = 64 * 1024
    min_projects: int = 1
    max_projects: int = 32

    def __post_init__(self) -> None:
        for name in ("default_rows", "max_rows", "max_metadata_candidates", "max_detail_bytes", "min_projects", "max_projects"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ObservabilityContractError(f"{name} must be a positive integer")
        if self.default_rows > self.max_rows:
            raise ObservabilityContractError("default_rows cannot exceed max_rows")
        if self.min_projects > self.max_projects:
            raise ObservabilityContractError("min_projects cannot exceed max_projects")

    def validate(self, *, rows: int, project_count: int, detail_bytes: int = 0, metadata_candidates: int = 0) -> None:
        values = {
            "rows": (rows, self.max_rows),
            "project_count": (project_count, self.max_projects),
            "detail_bytes": (detail_bytes, self.max_detail_bytes),
            "metadata_candidates": (metadata_candidates, self.max_metadata_candidates),
        }
        for name, (value, maximum) in values.items():
            minimum = 1 if name in {"rows", "project_count"} else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                qualifier = "positive" if minimum else "non-negative"
                raise ObservabilityContractError(f"{name} must be a {qualifier} integer")
            if value > maximum:
                raise ObservabilityContractError(f"{name} exceeds the Events bound of {maximum}")
        if project_count < self.min_projects:
            raise ObservabilityContractError(f"project_count must be at least {self.min_projects}")


EVENTS_READ_LIMITS = ReadLimits()


@dataclass(frozen=True)
class FixtureSpec:
    """A focused qualification fixture and the invariant it must establish."""

    name: str
    scope: str
    expected_evidence: str

    def __post_init__(self) -> None:
        _text(self.name, "fixture name")
        _text(self.scope, "fixture scope")
        _text(self.expected_evidence, "fixture expected evidence")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "scope": self.scope, "expected_evidence": self.expected_evidence}


FIXTURE_INVENTORY: Tuple[FixtureSpec, ...] = (
    FixtureSpec("atomic-batch-lifecycle-replacement", "one mutation covering batch child, lifecycle and replacement facets", "all facets share one accepted source event and exact refs/revisions"),
    FixtureSpec("old-reference-current-head-gap", "old revision lookup against a changed current identity", "current head is not presented as historical state; the missing field/range is explicit"),
    FixtureSpec("active-project-without-events", "authorized active project with no in-range event", "active_during discovery can match without fabricating a history row"),
    FixtureSpec("large-sparse-bounded-read", "large unrelated inventory and sparse matching rows", "candidate, hydration, returned-row, detail-byte and metadata limits are independently counted"),
    FixtureSpec("grant-and-snapshot-stability", "grant change and late source fact after a fixed snapshot", "pages reauthorize, preserve the boundary, and require refresh when incompatible"),
    FixtureSpec("migration-interruption-copy-backfill-switch", "disposable successor interrupted at each migration boundary", "source equality, custody, journal and truthful legacy gaps survive interruption"),
    FixtureSpec("deterministic-rebuild", "fresh projection generation rebuilt from the same source cutoff", "rebuild equality holds and old cursors are invalidated on generation switch"),
    FixtureSpec("retained-response-no-application-result-no-acceptance", "one overview and one authorized bounded detail", "response/application and native result/task acceptance remain distinct facts"),
)


@dataclass(frozen=True)
class ObservationRef:
    """Optional future Usage/cost facet reference; no accounting semantics."""

    facet_type: str
    subject_ref: ResourceRef
    source_ref: ResourceRef
    recorded_at: str
    occurrence_at: Optional[str] = None
    detail_ref: Optional[ResourceRef] = None
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.facet_type, "facet_type")
        _ref(self.subject_ref, "subject_ref")
        _ref(self.source_ref, "source_ref")
        _iso(self.recorded_at, "recorded_at")
        if self.occurrence_at is not None:
            _iso(self.occurrence_at, "occurrence_at")
        if self.detail_ref is not None:
            _ref(self.detail_ref, "detail_ref")
        if not isinstance(self.summary, Mapping):
            raise ObservabilityContractError("summary must be a mapping")
        # The summary is a bounded, opaque handoff.  Events may retain it but
        # never interprets metric, span, rate, token, or monetary semantics.
        try:
            encoded = json.dumps(dict(self.summary), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ObservabilityContractError("summary must be JSON-compatible") from exc
        if len(encoded.encode("utf-8")) > EVENTS_READ_LIMITS.max_detail_bytes:
            raise ObservabilityContractError("observation summary exceeds the detail bound")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": "otto.events.observation-ref.v1",
            "facet_type": self.facet_type,
            "subject_ref": self.subject_ref.to_dict(),
            "source_ref": self.source_ref.to_dict(),
            "recorded_at": self.recorded_at,
            "summary": dict(self.summary),
        }
        if self.occurrence_at is not None:
            result["occurrence_at"] = self.occurrence_at
        if self.detail_ref is not None:
            result["detail_ref"] = self.detail_ref.to_dict()
        return result


def contract_record() -> dict[str, Any]:
    """Return the deterministic D01 record consumed by later tasks."""
    return {
        "schema": CONTRACT_SCHEMA,
        "revision": CONTRACT_REVISION,
        "source": {"root": CANDIDATE_ROOT, "commit": SOURCE_COMMIT, "seams": [item.to_dict() for item in SOURCE_SEAMS]},
        "runtime": dict(RUNTIME_PIN),
        "resources": json.loads(json.dumps(RESOURCE_PINS, sort_keys=True)),
        "historical_fields": list(HISTORICAL_FIELDS),
        "history_facets": list(HISTORY_FACETS),
        "legacy_gap_rules": list(LEGACY_GAP_RULES),
        "read_limits": {
            "default_rows": EVENTS_READ_LIMITS.default_rows,
            "max_rows": EVENTS_READ_LIMITS.max_rows,
            "max_metadata_candidates": EVENTS_READ_LIMITS.max_metadata_candidates,
            "max_detail_bytes": EVENTS_READ_LIMITS.max_detail_bytes,
            "min_projects": EVENTS_READ_LIMITS.min_projects,
            "max_projects": EVENTS_READ_LIMITS.max_projects,
        },
        "fixtures": [fixture.to_dict() for fixture in FIXTURE_INVENTORY],
        "usage_cost": {
            "state": "pending_successor",
            "observation_ref_schema": "otto.events.observation-ref.v1",
            "events_owns": ["retained_reference", "recorded_at", "optional_qualified_occurrence_at"],
            "successor_owns": ["new_capture", "late_observation_writes", "span_deduplication", "attribution", "accounting", "money"],
            "synthetic_totals": False,
            "billing_claims": False,
        },
    }


def contract_digest() -> str:
    """Hash the exact contract record for handoff provenance."""
    encoded = json.dumps(contract_record(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "CANDIDATE_ROOT", "CONTRACT_REVISION", "CONTRACT_SCHEMA", "EVENTS_READ_LIMITS",
    "FIXTURE_INVENTORY", "HISTORY_FACETS", "HISTORICAL_FIELDS", "LEGACY_GAP_RULES",
    "ObservationRef", "ObservabilityContractError", "RESOURCE_PINS", "RUNTIME_PIN",
    "SOURCE_COMMIT", "SOURCE_SEAMS", "SourcePin", "FixtureSpec", "ReadLimits",
    "contract_digest", "contract_record",
]

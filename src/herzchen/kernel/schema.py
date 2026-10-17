"""The closed, neutral FND-03 SQLite composition.

This module contains declarations only.  Admission compares the complete
composition and fingerprint before an existing database is opened for use;
migration is an explicit closed-owner operation, never ordinary open.
"""

from __future__ import annotations

import hashlib
import json
from typing import Tuple


LEGACY_SCHEMA_REVISION = "fnd-03.v1"

# This is the only table composition an FND-03 store may contain.  Product
# domains persist their own records elsewhere and use the transaction port.
LEGACY_COMPOSITION: Tuple[str, ...] = (
    "store_metadata",
    "identities",
    "record_references",
    "event_sequences",
    "command_receipts",
    "events",
)

LEGACY_DDL = """
CREATE TABLE store_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE identities (
    authority TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    current_revision TEXT,
    version INTEGER NOT NULL CHECK (version >= 0),
    edit_token TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (authority, kind, id)
);

CREATE TABLE record_references (
    reference_key TEXT PRIMARY KEY NOT NULL,
    authority TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    revision TEXT,
    reference_json TEXT NOT NULL,
    FOREIGN KEY (authority, kind, id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE event_sequences (
    store_authority TEXT NOT NULL,
    stream TEXT NOT NULL,
    next_sequence INTEGER NOT NULL CHECK (next_sequence >= 1),
    PRIMARY KEY (store_authority, stream)
);

CREATE TABLE command_receipts (
    logical_request_key TEXT PRIMARY KEY NOT NULL,
    request_digest TEXT NOT NULL,
    operation TEXT NOT NULL,
    target_authority TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_revision TEXT,
    status TEXT NOT NULL,
    transaction_id TEXT,
    event_ids_json TEXT NOT NULL,
    result_ref_json TEXT,
    error_code TEXT,
    replayed INTEGER NOT NULL CHECK (replayed IN (0, 1)),
    observed_revision TEXT,
    unknown_reason TEXT,
    FOREIGN KEY (target_authority, target_kind, target_id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY NOT NULL,
    store_authority TEXT NOT NULL,
    stream TEXT NOT NULL,
    subject_authority TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_revision TEXT,
    schema_revision TEXT NOT NULL,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    actor_authority TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    operation TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    occurred_at TEXT,
    before_refs_json TEXT NOT NULL,
    after_refs_json TEXT NOT NULL,
    effects_json TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    UNIQUE (store_authority, stream, sequence),
    FOREIGN KEY (subject_authority, subject_kind, subject_id)
        REFERENCES identities (authority, kind, id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
"""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(revision: str, composition: Tuple[str, ...], ddl: str) -> str:
    return hashlib.sha256(_canonical({"revision": revision, "composition": composition,
                                     "ddl": ddl}).encode("utf-8")).hexdigest()


LEGACY_SCHEMA_FINGERPRINT = fingerprint(LEGACY_SCHEMA_REVISION, LEGACY_COMPOSITION, LEGACY_DDL)
SCHEMA_REVISION = "fnd-03.events.v2"
COMPOSITION = LEGACY_COMPOSITION + ("project_history",)
# Source ordering belongs to the existing authoritative event table. The
# projection has no receipts or independent event authority.
DDL = LEGACY_DDL.replace("    event_id TEXT PRIMARY KEY NOT NULL,",
    "    event_id TEXT PRIMARY KEY NOT NULL,\n"
    "    append_position INTEGER NOT NULL UNIQUE CHECK (append_position >= 1),") + """
CREATE INDEX events_subject_revision ON events
    (subject_authority, subject_kind, subject_id, subject_revision, append_position);
CREATE TABLE project_history (
    generation INTEGER NOT NULL CHECK (generation >= 1),
    facet_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    facet_index INTEGER NOT NULL CHECK (facet_index >= 0),
    source_append_position INTEGER NOT NULL CHECK (source_append_position >= 1),
    stream TEXT NOT NULL,
    stream_sequence INTEGER NOT NULL CHECK (stream_sequence >= 1),
    project_authority TEXT,
    project_id TEXT,
    subject_authority TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_revision TEXT,
    recorded_at TEXT NOT NULL,
    occurred_at TEXT,
    facet_type TEXT NOT NULL,
    role TEXT,
    outcome TEXT,
    summary_json TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    PRIMARY KEY (generation, facet_id),
    UNIQUE (generation, source_event_id, facet_index, project_authority, project_id),
    FOREIGN KEY (source_event_id) REFERENCES events(event_id) ON DELETE RESTRICT
);
CREATE INDEX history_project_time ON project_history
    (generation, project_authority, project_id, recorded_at, source_append_position, facet_index, facet_id);
CREATE INDEX history_subject_time ON project_history
    (generation, project_authority, project_id, subject_kind, subject_id, recorded_at, source_append_position, facet_index);
CREATE INDEX history_lifecycle ON project_history
    (generation, project_authority, project_id, facet_type, subject_kind, subject_id, recorded_at, source_append_position);
CREATE INDEX history_source ON project_history (generation, source_append_position, facet_index);
CREATE INDEX history_role_outcome ON project_history
    (generation, project_authority, project_id, role, outcome, recorded_at, source_append_position);
"""
SCHEMA_FINGERPRINT = fingerprint(SCHEMA_REVISION, COMPOSITION, DDL)
SUPPORTED_SCHEMAS = {
    LEGACY_SCHEMA_REVISION: (LEGACY_COMPOSITION, LEGACY_SCHEMA_FINGERPRINT, LEGACY_DDL),
    SCHEMA_REVISION: (COMPOSITION, SCHEMA_FINGERPRINT, DDL),
}


# Optional, owner-built read accelerators. They change neither canonical rows
# nor the schema revision. Admission still rejects every undeclared index and
# checks these exact definitions when present; ordinary open never builds them.
IDENTITY_LOOKUP_INDEXES = {
    "identities_due_native_lookup": "CREATE INDEX identities_due_native_lookup ON identities (authority, kind, json_extract(payload_json, '$.target.native_adapter'), json_extract(payload_json, '$.host_evidence.gateway_attempt.delivery_authorization.physical_session_id')) WHERE kind = 'otto.due-record'",
    "identities_due_project_lookup": "CREATE INDEX identities_due_project_lookup ON identities (authority, kind, json_extract(payload_json, '$.project_ref')) WHERE kind = 'otto.due-record'",
    "identities_status_task_project_lookup": "CREATE INDEX identities_status_task_project_lookup ON identities (authority, kind, json_extract(payload_json, '$.project_ref.id')) WHERE kind = 'work.task'",
    "identities_status_assignment_project_lookup": "CREATE INDEX identities_status_assignment_project_lookup ON identities (authority, kind, json_extract(payload_json, '$.scope.id')) WHERE kind = 'wrk.assignment'",
    "identities_status_report_project_lookup": "CREATE INDEX identities_status_report_project_lookup ON identities (authority, kind, json_extract(payload_json, '$.value.project_ref.id')) WHERE kind = 'wrk.report'",
    "identities_work_assignment_lookup": "CREATE INDEX identities_work_assignment_lookup ON identities (authority, kind, CASE WHEN json_type(payload_json, '$.assignment') = 'object' THEN json_extract(json_extract(payload_json, '$.assignment'), '$.authority') END, CASE WHEN json_type(payload_json, '$.assignment') = 'object' THEN json_extract(json_extract(payload_json, '$.assignment'), '$.kind') END, CASE WHEN json_type(payload_json, '$.assignment') = 'object' THEN json_extract(json_extract(payload_json, '$.assignment'), '$.id') END, id, current_revision) WHERE kind IN ('wrk.dispatch', 'wrk.result', 'wrk.report')",
}


def verify_physical_schema(connection, revision: str) -> bool:
    """Compare tables, constraints and indexes, not just self-reported metadata."""
    import sqlite3
    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(SUPPORTED_SCHEMAS[revision][2])
        sql = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        normalize = lambda rows: [tuple(row) for row in rows]
        actual = normalize(connection.execute(sql))
        if revision == SCHEMA_REVISION:
            present = {row[1] for row in actual if row[0] == 'index'}
            for name, ddl in IDENTITY_LOOKUP_INDEXES.items():
                if name in present:
                    expected.execute(ddl)
        return actual == normalize(expected.execute(sql))
    finally:
        expected.close()


__all__ = ["COMPOSITION", "DDL", "SCHEMA_FINGERPRINT", "SCHEMA_REVISION",
           "LEGACY_COMPOSITION", "LEGACY_DDL", "LEGACY_SCHEMA_FINGERPRINT",
           "LEGACY_SCHEMA_REVISION", "SUPPORTED_SCHEMAS", "verify_physical_schema"]

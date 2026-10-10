"""Versioned source summaries and deterministic migration facets.

Only validated pre/post state supplied by the writer can establish membership.
Legacy extraction uses event facts alone; a current identity head is never a
historical lookup. D03 owns reader/maintenance behavior over these source facts.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional
from herzchen.contracts import ResourceRef, canonical_json

HISTORY_SCHEMA = "fnd.history-summary.v1"
MAX_SUMMARY_BYTES = 65536
MAX_INLINE_FACETS = 128
# Typed relations, not arbitrary payload copies (reports, sheets and native
# output may be large). A missing field is recorded explicitly as unknown.
STATE_FIELDS = ("parent", "project_ref", "project", "scope", "lifecycle", "status",
                "responsibility_ref", "generation", "principal", "role", "agent",
                "session", "manager", "reporter", "launcher", "assignment",
                "dependencies", "pins", "documents", "document", "current_revision", "subject", "active",
                "delivery_state", "application_state", "native_result", "task_acceptance")


def safe(value: Any) -> Any:
    if isinstance(value, ResourceRef):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [safe(v) for v in value]
    return value


def state(ref: Optional[ResourceRef], payload: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if payload is None:
        return {"exists": False, "ref": None, "fields": {}, "unknown": []}
    fields = {k: safe(payload[k]) for k in STATE_FIELDS if k in payload}
    if ref is not None and ref.kind == "authoring-scope" and "project" in fields:
        # EDT retains the full folder draft for recovery. It is authoritative
        # authoring content, not a typed historical relation or summary body.
        value = fields["project"]
        pin = value.get("ref") if isinstance(value, Mapping) and "ref" in value else value
        try:
            project = ResourceRef.from_dict(pin) if isinstance(pin, Mapping) else None
        except (ValueError, TypeError, KeyError):
            project = None
        if (project is not None and project.authority == ref.authority
                and project.kind == "work.project" and project.revision is not None):
            fields["project"] = project.to_dict()
        else:
            fields.pop("project")
    # A Work result is an immutable owner observation, not task acceptance.
    # Keep only its bounded typed attempt facts, never native output/context.
    value = payload.get("value")
    assignment = safe(payload.get("assignment"))
    if (ref is not None and ref.kind == "wrk.result" and payload.get("record_type") == "work.observation"
            and payload.get("observation_kind") == "result" and isinstance(value, Mapping)
            and safe(value.get("assignment_ref")) == assignment
            and type(value.get("generation")) is int and value["generation"] == payload.get("generation")
            and all(isinstance(value.get(k), str) and 0 < len(value[k]) <= 256
                    for k in ("logical_request_key", "operation", "delivery_state", "outcome"))):
        fields["delivery_state"] = value["delivery_state"]
        fields["native_result"] = {"result_ref": safe(ref), "outcome": value["outcome"],
            "source": "retained owner attempt observation"}
        for key in ("physical_session_id", "observed_model", "observed_reasoning"):
            item = value.get(key)
            if isinstance(item, str) and 0 < len(item) <= 256:
                fields["native_result"][key] = item
        if (type(value.get("application_state")) is bool or isinstance(value.get("application_state"), str)
                and len(value["application_state"]) <= 256):
            fields["application_state"] = value["application_state"]
    completion = payload.get("completion")
    if (ref is not None and ref.kind == "work.task" and payload.get("lifecycle") == "completed"
            and isinstance(completion, Mapping) and completion.get("candidate_ref")
            and isinstance(completion.get("disposition"), str)):
        fields["task_acceptance"] = {"disposition": completion["disposition"],
            "candidate_ref": safe(completion["candidate_ref"]), "source": "committed manager completion"}
    return {"exists": True, "ref": safe(ref), "fields": fields,
            "unknown": [k for k in STATE_FIELDS if k not in fields]}


def transition(before_ref, before_payload, after_ref, after_payload, *, facet_type="creation_or_revision"):
    before, after = state(before_ref, before_payload), state(after_ref, after_payload)
    changed = [k for k in STATE_FIELDS if before["fields"].get(k) != after["fields"].get(k) or
               (k in before["fields"]) != (k in after["fields"])]
    result = {"schema": HISTORY_SCHEMA, "facet_type": facet_type,
              "subject": safe(after_ref), "before": state(before_ref, before_payload),
              "after": after, "coverage": "captured-pre-post", "changed_fields": changed,
              "relation_changes": [{"relation": k, "before": before["fields"].get(k),
                                    "after": after["fields"].get(k)} for k in changed
                                   if k in {"parent","project_ref","project","scope","assignment",
                                            "responsibility_ref","dependencies","pins","documents",
                                            "document","current_revision","subject"}]}
    if len(canonical_json(result).encode()) > MAX_SUMMARY_BYTES:
        raise ValueError("typed historical state exceeds 64 KiB; use a bounded admitted manifest")
    return result


def project_relations(facet: Mapping[str, Any]):
    """Explicit retained memberships, including removal from an old project."""
    projects = {}
    subject = facet["subject"]
    if subject["kind"] == "work.project":
        projects[(subject["authority"], subject["id"])] = subject
    for side in ("before", "after"):
        for value in facet.get(side, {}).get("fields", {}).values():
            if isinstance(value, Mapping) and value.get("kind") == "work.project":
                projects[(value["authority"], value["id"])] = dict(value)
    # Writer-validated scope resolution is captured at mutation time only.
    for value in facet.get("resolved_projects", ()):
        projects[(value["authority"], value["id"])] = value
    return [projects[k] for k in sorted(projects)]


def source_facets(row: Mapping[str, Any]):
    """Return only actual retained facts; no head lookup or domain replay."""
    effects = json.loads(row["effects_json"])
    history = effects.get("history_summary")
    subject = ResourceRef(row["subject_authority"], row["subject_kind"],
                          row["subject_id"], row["subject_revision"])
    if isinstance(history, Mapping) and history.get("schema") == HISTORY_SCHEMA:
        facets = [history["primary"]] + list(history.get("facets", ()))
        if history.get("manifest"):
            # D03 resolves selected pinned manifests with bounded continuation.
            # Never mark a position fully covered without those facets.
            raise ValueError("history manifest requires an authorized bounded resolver")
        return facets
    # Known immutable post-state carried by historical assignment actions is
    # usable only at its recorded capture. It establishes no pre-state.
    payload = effects.get("result_payload")
    after = state(subject, payload) if isinstance(payload, Mapping) else {
        "exists": None, "ref": subject.to_dict(), "fields": {}, "unknown": list(STATE_FIELDS)}
    fields = after["fields"]
    for k in ("project", "parent", "assignment", "generation", "responsibility"):
        if k in effects:
            fields[k] = effects[k]
    after["unknown"] = [k for k in STATE_FIELDS if k not in fields]
    facet = {"schema": HISTORY_SCHEMA, "facet_type": "legacy_fact", "subject": subject.to_dict(),
             "before": {"exists": None, "ref": None, "fields": {}, "unknown": list(STATE_FIELDS)},
             "after": after, "coverage": "legacy-field-gaps",
             "legacy": {"operation": row["operation"], "event_type": row["event_type"],
                        "cross_stream_chronology": "unknown", "occurrence_time": "unqualified"}}
    # Legacy payloads had no capture bound. Preserve the authoritative source
    # bytes and disclose omitted oversized fields, never expand the projection
    # into a second payload store or infer their values from current heads.
    omitted = []
    for key in sorted(fields, key=lambda k: len(canonical_json(fields[k]).encode()), reverse=True):
        if len(canonical_json(facet).encode()) <= MAX_SUMMARY_BYTES:
            break
        fields.pop(key)
        omitted.append(key)
        after["unknown"] = sorted(set(after["unknown"]) | {key})
        facet["legacy"]["bounded_field_gaps"] = sorted(omitted)
    if len(canonical_json(facet).encode()) > MAX_SUMMARY_BYTES:
        raise ValueError("legacy source locator exceeds the bounded summary contract")
    return [facet]


def projection_rows(row: Mapping[str, Any], *, generation: int = 1, start_index: int = 0):
    for index, facet in enumerate(source_facets(row), start=start_index):
        for project in project_relations(facet) or [None]:
            subject = facet["subject"]
            identity = [row["store_authority"], row["event_id"], index, subject,
                        None if project is None else [project["authority"], project["id"]]]
            facet_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
            fields = facet.get("after", {}).get("fields", {})
            yield (generation, facet_id, row["event_id"], index, row["append_position"],
                   row["stream"], row["sequence"], None if project is None else project["authority"],
                   None if project is None else project["id"], subject["authority"], subject["kind"],
                   subject["id"], subject.get("revision"), row["recorded_at"], None,
                   facet["facet_type"], fields.get("role"), fields.get("lifecycle", fields.get("status")),
                   canonical_json(facet), canonical_json({"event_id": row["event_id"], "subject": subject}))


PROJECTION_INSERT = "INSERT INTO project_history VALUES (" + ",".join(["?"] * 20) + ")"


class EvidenceHistoryPublisher:
    """Reuse installed Evidence publication and dependency protection.

    Configured by the trusted owner with its admitted Evidence command port.
    No standalone files, pack DDL, or new Evidence ledger are introduced.
    Essential history payloads fail closed for reclaim until their dependency
    is explicitly reconciled by the existing owner dependency resolver.
    """
    def __init__(self, evidence, actor):
        self.evidence, self.actor = evidence, actor

    def __call__(self, event_id, facets, project):
        data = b"".join(canonical_json(facet).encode() + b"\n" for facet in facets)
        digest = hashlib.sha256(data).hexdigest()
        result = self.evidence.submit(data, actor=self.actor,
            logical_request_key="history-manifest-" + event_id, project_ref=project,
            original_creator=self.actor.actor, format="jsonl",
            provenance={"history_schema": HISTORY_SCHEMA, "source_event_id": event_id,
                        "essential_history": True, "dependency_unknown": True})
        ref = result["revision_ref"]
        if isinstance(ref, Mapping):
            ref = ResourceRef.from_dict(ref)
        if ref.revision is None:
            raise ValueError("Evidence history publication did not return an exact pin")
        manifest = result["manifest"]
        if manifest["byte_digest"] != digest or manifest["byte_length"] != len(data):
            raise ValueError("Evidence history manifest does not match source facets")
        return {"ref": ref.to_dict(), "byte_digest": digest, "byte_length": len(data),
                "facet_count": len(facets), "format": "jsonl", "schema": HISTORY_SCHEMA}

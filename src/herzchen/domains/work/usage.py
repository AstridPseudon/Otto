"""Narrow late Usage append inside the existing WRK owner transaction.

These are typed WRK reports, not execution results. The current caller's
assignment fence is independent of the immutable historical admission. All
source reads select exact retained pins; no current head supplies attribution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from herzchen.contracts import ResourceRef, ReplayConflictError, canonical_json
from .model import WorkValidationError

MAX_SOURCE_BYTES = 256 * 1024
MAX_PRIOR_FACTS = 256
FACT_SCHEMA = "otto.usage-retained-fact.v1"


def _pin(value, kind=None):
    ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    if ref.revision is None or kind is not None and ref.kind != kind:
        raise WorkValidationError("exact retained revision required")
    return ref


def _key(ref):
    return ref.authority, ref.kind, ref.id


def _json(value):
    return json.loads(canonical_json(value))


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _selected_values(keys, values):
    if sum(len(v.encode()) for v in values if isinstance(v, str)) > MAX_SOURCE_BYTES:
        raise WorkValidationError("selected typed source exceeds byte bound")
    return {k: (json.loads(v) if isinstance(v, str) and v[:1] in '{[' else v)
        for k, v in zip(keys, values)}


def _source(writer, ref):
    """Select bounded typed fields from one original source event/result."""
    row = writer.connection.execute(
        "SELECT event_id,recorded_at,append_position FROM events WHERE store_authority=? "
        "AND subject_authority=? AND subject_kind=? AND subject_id=? AND subject_revision=? "
        "ORDER BY append_position LIMIT 1", (writer.authority, * _key(ref), ref.revision)).fetchone()
    if row is None:
        raise WorkValidationError("original source event is not retained")
    if ref.kind == "otto.due-record":
        paths = {"assignment_ref": "assignment_ref", "generation": "generation", "principal": "recipient",
            "project_id": "project_ref", "task_ref": "target.task_ref", "parent": "target.parent",
            "attempt": "host_evidence.gateway_attempt"}
        # Do not decode raw_result or the native body. SQLite selects each
        # small field from the exact immutable event at the original boundary.
        attempt_fields = ("assignment_ref", "generation", "logical_request_key", "state",
            "physical_session_id", "request_fingerprint", "delivery_admission", "delivery_authorization", "usage_observations")
        selectors = [(k, '$.record.' + v) for k, v in paths.items() if k != "attempt"]
        selectors += [(k, '$.record.' + paths['attempt'] + '.' + k) for k in attempt_fields]
        selectors += [(k, '$.record.' + paths['attempt'] + '.result.' + k) for k in (
            "requested_model", "requested_tier", "observed_model", "observed_tier")]
        sql = "SELECT " + ','.join("json_extract(effects_json,?)" for _ in selectors) + " FROM events WHERE event_id=?"
        data = writer.connection.execute(sql, tuple(p for _, p in selectors) + (row[0],)).fetchone()
        result = _selected_values([k for k, _ in selectors], data)
        # The attempt binding must match the top-level admitted Due identity.
        header = writer.connection.execute(
            "SELECT json_extract(effects_json,'$.record.assignment_ref'),json_extract(effects_json,'$.record.generation') "
            "FROM events WHERE event_id=?", (row[0],)).fetchone()
        if result.get("assignment_ref") != json.loads(header[0] or 'null') or result.get("generation") != header[1]:
            raise WorkValidationError("retained claim and Due generation differ")
    elif ref.kind == "wrk.result":
        record = writer.connection.execute("SELECT current_revision FROM identities WHERE authority=? AND kind=? AND id=?", _key(ref)).fetchone()
        if record is None or record[0] != ref.revision:
            raise WorkValidationError("immutable original result pin differs")
        # Existing old inline readers stay intact. Numeric usage extraction uses
        # selected SQL paths instead of hydrating potentially large native text.
        paths = {"assignment_ref": "assignment", "generation": "generation",
            "record_type": "record_type", "observation_kind": "observation_kind",
            "logical_request_key": "value.logical_request_key", "physical_session_id": "value.physical_session_id",
            "project_ref": "value.project_ref", "task_ref": "value.task_ref", "principal": "value.logical_agent_id",
            "requested_model": "value.requested_model", "requested_tier": "value.requested_tier",
            "observed_model": "value.observed_model", "observed_tier": "value.observed_tier",
            "result_assignment_ref": "value.assignment_ref", "result_generation": "value.generation",
            "admitted_session": "value.task_bound_evidence.session_id", "admitted_turn": "value.task_bound_evidence.turn_id",
            "observed_turn_id": "value.observed_turn_id", "context_digest_verified": "value.context_digest_verified",
            "usage_capture": "value.usage_capture"}
        sql = "SELECT " + ','.join("json_extract(payload_json,?)" for _ in paths) + " FROM identities WHERE authority=? AND kind=? AND id=?"
        data = writer.connection.execute(sql, tuple('$.' + p for p in paths.values()) + _key(ref)).fetchone()
        result = _selected_values(paths, data)
        result["context_digest_verified"] = writer.connection.execute(
            "SELECT json_type(payload_json,'$.value.context_digest_verified') FROM identities WHERE authority=? AND kind=? AND id=?",
            _key(ref)).fetchone()[0] == "true"
        if result.get("record_type") != "work.observation" or result.get("observation_kind") != "result":
            raise WorkValidationError("source is not an immutable owner result")
        if result.get("result_assignment_ref") != result.get("assignment_ref") or result.get("result_generation") != result.get("generation"):
            raise WorkValidationError("result body differs from authoritative historical assignment")
        admitted_session, admitted_turn = result.pop("admitted_session", None), result.pop("admitted_turn", None)
        if admitted_session is None and admitted_turn is None and result.get("context_digest_verified") is True:
            # New reference-only task evidence retains these owner-verified small
            # facts in the immutable result. Never resolve a current assignment.
            admitted_session, admitted_turn = result.get("physical_session_id"), result.get("observed_turn_id")
        result["delivery_admission"] = {"physical_session_id": admitted_session, "observed_turn_id": admitted_turn}
        captures = result.pop("usage_capture", None) or {}
        carriers = [captures] if "observations" in captures else [captures.get("initializer"), captures.get("work")]
        result["usage_observations"] = [o for c in carriers if isinstance(c, Mapping) for o in c.get("observations", ())]
    else:
        raise WorkValidationError("late source must be an exact owner Due or WRK result pin")
    if len(canonical_json(result).encode()) > MAX_SOURCE_BYTES:
        raise WorkValidationError("selected typed source exceeds bound")
    result.update(source_ref=ref.to_dict(), source_event_id=row[0], recorded_at=row[1], append_position=row[2])
    return result


def append_late_usage(engine, writer, bodies, target, source_ref, source, *, adapter_id,
                      phase, session_id, turn_id, authorizing_assignment_ref,
                      authorizing_generation, logical_request_key, actor,
                      supersedes_ref=None):
    from otto.agents.usage_capture import UsageStream, CAPTURE_SCHEMA
    from otto.agents.usage_contract import ADAPTER_DESCRIPTORS
    from otto.agents.usage_accounting import instant, qualified_observation

    if bodies is None or actor is None or actor != engine.default_actor or actor.authority != writer.authority:
        raise PermissionError("late usage requires explicit owner-issued source capability")
    authorizer = _pin(authorizing_assignment_ref, "wrk.assignment")
    if type(authorizing_generation) is not int or authorizing_generation < 1:
        raise WorkValidationError("current authorizing generation required")
    target = _pin(target, "wrk.assignment")
    source_ref = _pin(source_ref)
    source = _json(source)
    if len(canonical_json(source).encode()) > 4096:
        raise WorkValidationError("bounded retained source carrier required")
    if source.get("utf8_bytes", MAX_SOURCE_BYTES + 1) > MAX_SOURCE_BYTES:
        raise WorkValidationError("selected usage source exceeds byte bound")
    # Parser/source-version idempotency is independent of report/carrier aliases.
    request = {"parser_version": CAPTURE_SCHEMA, "native_schema": ADAPTER_DESCRIPTORS.get(adapter_id, {}).get("native_schema"), "target": target, "source_ref": source_ref, "source": source,
        "adapter_id": adapter_id, "phase": phase, "session_id": session_id, "turn_id": turn_id,
        "authorizing_assignment_ref": authorizer, "authorizing_generation": authorizing_generation,
        "supersedes_ref": supersedes_ref}
    key = engine._request_key(logical_request_key)
    ident = "usage-" + _hash([key, target.authority])[:28]
    ref = ResourceRef(writer.authority, "wrk.report", ident)
    fingerprint = _hash(request)
    with writer.transaction() as tx:
        current = engine.get(ResourceRef(authorizer.authority, authorizer.kind, authorizer.id))
        if current.ref != authorizer or current.generation != authorizing_generation or current.status.value in {"cancelled", "completed", "reassigned"}:
            raise PermissionError("current authorizing assignment is stale or inactive")
        original = _source(writer, source_ref)
        if source_ref.kind == "otto.due-record" and (original.get("state") not in {"claimed", "result"}
                or not original.get("request_fingerprint") or not original.get("logical_request_key")):
            raise WorkValidationError("late observation requires the original admitted owner claim")
        if original.get("assignment_ref") != target.to_dict() or type(original.get("generation")) is not int:
            raise WorkValidationError("original source does not bind the historical assignment")
        # Attribution is taken from the exact original assignment revision facet,
        # even after its principal, generation, session or scope is replaced.
        historical = tx.execute("SELECT json_extract(effects_json,'$.history_summary.primary.after.fields') "
            "FROM events WHERE store_authority=? AND subject_authority=? AND subject_kind=? AND subject_id=? "
            "AND subject_revision=? ORDER BY append_position DESC LIMIT 1",
            (writer.authority, *_key(target), target.revision)).fetchone()
        if historical is None or historical[0] is None:
            raise WorkValidationError("historical assignment admission is unavailable")
        admitted = json.loads(historical[0])
        if admitted.get("generation") != original["generation"]:
            raise WorkValidationError("historical source generation differs from admission")
        scope = admitted.get("scope") or {}
        project = original.get("project_ref")
        if scope.get("kind") == "work.project":
            if project is not None and _key(_pin(project)) != _key(_pin(scope)):
                raise WorkValidationError("result project differs from historical scope")
            project = scope
        elif scope.get("kind") == "work.task":
            task_event = tx.execute("SELECT json_extract(effects_json,'$.history_summary.primary.after.fields.project_ref') "
                "FROM events WHERE subject_authority=? AND subject_kind=? AND subject_id=? AND subject_revision=? "
                "ORDER BY append_position DESC LIMIT 1", (*_key(_pin(scope)), scope.get("revision"))).fetchone()
            if task_event is None or not task_event[0]:
                raise WorkValidationError("historical task project is unavailable")
            project = json.loads(task_event[0])
            if original.get("task_ref") != scope:
                raise WorkValidationError("original task differs from admitted historical task")
        else:
            raise WorkValidationError("historical project attribution unavailable")
        if original.get("project_id") is not None and original["project_id"] != project["id"]:
            raise WorkValidationError("original Due project differs from historical admission")
        current_scope = _json(current.scope)
        if _key(_pin(current_scope)) != _key(_pin(project)) or current.role not in {"manager", "orchestrator"}:
            raise PermissionError("late append authorizer must currently manage the admitted project")
        prior = writer.get_identity(ref)
        if prior is not None:
            if prior.payload.get("value", {}).get("input_sha256") != fingerprint:
                raise ReplayConflictError("late usage request key reused with changed input")
            return engine._usage_record(prior)
        origin = source.get("origin") or {}
        if (_key(ResourceRef.from_dict(origin.get("project_ref"))) != _key(_pin(project)) or origin.get("attempt_ref") not in (target.to_dict(), authorizer.to_dict())):
            raise WorkValidationError("retained usage bytes differ from admitted historical scope")
        body = bodies.resolve(source, expected_origin=origin)
        if not isinstance(body, str) or len(body.encode()) > MAX_SOURCE_BYTES:
            raise WorkValidationError("selected native completion line required")
        stream = UsageStream(adapter_id, phase=phase, session_id=session_id,
            requested_model=original.get("requested_model"), requested_tier=original.get("requested_tier"),
            turn_resolver=lambda _: turn_id)
        stream.observed_model = original.get("observed_model")
        # Claude needs its separately verified admitted turn binding; parsing
        # this selected completion does not pretend to be a full live stream.
        stream.turn_id = turn_id
        observation = stream.feed(body)
        if observation is None:
            raise WorkValidationError("selected source is not a qualified completion")
        native_event = json.loads(body)
        metric_scope = native_event.get("usage_scope", native_event.get("metric_scope", "turn"))
        if metric_scope == "cumulative":
            # Retain the snapshot, never derive additive deltas.
            from otto.agents.usage_capture import digest
            identity = {**observation["identity"], "metric_scope": "cumulative"}
            identity["span_id"] = "usage-span-" + digest({k: v for k, v in identity.items() if k != "span_id"})
            observation["identity"] = identity
            observation["usage"]["scope"] = "cumulative"
        elif metric_scope != "turn":
            observation["usage"].update(state="unsupported_schema", metrics=None,
                reason="selected native metric scope is not qualified")
        if native_event.get("includes_descendants") is True or native_event.get("population_scope", "self") != "self":
            observation["population_scope"] = "includes-or-unknown-descendants"
        observation = qualified_observation(observation)
        identity = observation["identity"]
        if identity["session_id"] != session_id or identity["turn_id"] != turn_id:
            raise WorkValidationError("selected completion identity differs from requested physical span")
        prior_observations = original.get("usage_observations") or []
        matched = [o for o in prior_observations if o.get("identity") == identity and o.get("phase") == phase]
        if not observation["observed"].get("tier"):
            observation["observed"]["tier"] = original.get("observed_tier")
        for model_field in ("model", "tier"):
            values = {(o.get("observed") or {}).get(model_field) for o in matched}
            values.discard(None)
            if not observation["observed"].get(model_field) and len(values) == 1:
                observation["observed"][model_field] = next(iter(values))
        admission = original.get("delivery_admission") or {}
        if phase == "initializer":
            if not matched:
                raise WorkValidationError("initializer requires its exact retained physical identity")
            task = None  # overhead is project-only without explicit admission
        else:
            if (original.get("physical_session_id") != session_id
                    or admission.get("physical_session_id") != session_id
                    or admission.get("observed_turn_id") != turn_id):
                raise WorkValidationError("late work requires the original admitted session and turn")
            task = original.get("task_ref")
        # Exact scope of the retained source is never replaced by today's task.
        permitted_tasks = (task,) if origin.get("attempt_ref") == target.to_dict() else (task, None)
        if origin.get("task_ref") not in permitted_tasks:
            raise WorkValidationError("retained source task differs from historical phase")
        association = {"assignment_ref": target.to_dict(), "generation": admitted["generation"],
            "principal": admitted.get("principal"), "agent": admitted.get("agent"),
            "project_ref": project, "task_ref": task, "logical_request_key": original.get("logical_request_key"),
            "parent": original.get("parent")}
        observation["association"] = association
        observation["provenance"]["retained_source"] = source
        span_stream = "usage:" + identity["span_id"]
        rows = tx.execute("SELECT subject_id FROM events WHERE store_authority=? AND stream=? ORDER BY sequence LIMIT ?",
            (writer.authority, span_stream, MAX_PRIOR_FACTS + 1)).fetchall()
        if len(rows) > MAX_PRIOR_FACTS:
            raise WorkValidationError("physical span late-fact bound reached")
        facts = [writer.get_identity(ResourceRef(writer.authority, "wrk.report", r[0])).payload["value"] for r in rows]
        now = datetime.now(timezone.utc).isoformat()
        anchors = [(o.get("first_qualified_recorded_at"), o.get("provenance")) for o in matched
            if o.get("first_qualified_recorded_at") and o.get("usage", {}).get("state") in {"observed", "zero"}]
        first_fact = next((f for f in facts if f.get("first_qualified_recorded_at")), None)
        retained_anchor = None if first_fact is None else (first_fact["first_qualified_recorded_at"],
            first_fact["first_qualified_provenance"] if _key(_pin(first_fact["association"]["project_ref"])) == _key(_pin(project))
            else {"state": "shared-source-withheld"})
        # Never copy another project's source/assignment identifiers into a
        # single-project report. The original first fact retains its exact pin.
        participating_projects = {_key(_pin(f["association"]["project_ref"])) for f in facts}
        participating_projects.add(_key(_pin(project)))
        anchor, anchor_provenance = retained_anchor or (min(anchors, key=lambda a: instant(a[0])) if anchors else (
            (now, observation["provenance"]) if observation["usage"]["state"] in {"observed", "zero"} else (None, None)))
        predecessor = None
        if supersedes_ref is not None:
            predecessor = _pin(supersedes_ref, "wrk.report")
            previous = writer.get_identity(predecessor)
            previous_fact = None if previous is None or previous.ref != predecessor else previous.payload.get("value")
            if (not isinstance(previous_fact, Mapping) or previous_fact.get("schema") != FACT_SCHEMA
                    or previous_fact["observation"]["identity"] != identity
                    or previous_fact["association"] != association):
                raise WorkValidationError("correction must explicitly supersede the same historical physical span")
            # A correction is explicit, immutable and source-backed, never
            # last arrival wins. A second correction branch remains conflicted.
            anchor = previous_fact.get("first_qualified_recorded_at") or anchor
            anchor_provenance = previous_fact.get("first_qualified_provenance") or anchor_provenance
        fact = {"schema": FACT_SCHEMA, "input_sha256": fingerprint, "parser_version": CAPTURE_SCHEMA, "observation": observation,
            "association": association, "source_ref": source_ref.to_dict(), "source_event_id": original["source_event_id"],
            "first_qualified_recorded_at": anchor, "first_qualified_provenance": anchor_provenance,
            "shared_scope_count": len(participating_projects), "execution_time": admission.get("observed_at"),
            "supersedes_ref": None if predecessor is None else predecessor.to_dict()}
        payload = {"record_type": "work.observation", "observation_kind": "report",
            "assignment": target.to_dict(), "generation": admitted["generation"], "project_ref": project,
            "principal": admitted.get("principal"), "role": admitted.get("role"), "value": fact}
        if len(canonical_json(payload).encode()) > 16384:
            raise WorkValidationError("late fact exceeds bounded summary")
        receipt = writer.mutate(engine._envelope("work.report.append", ref, payload, key, actor, expected_version=0),
            event_type="work.report.appended", result_ref=ResourceRef(ref.authority, ref.kind, ref.id, "rev-1"),
            after_refs=(target, source_ref, _pin(source["ref"]), authorizer),
            effects={"append_only": True, "late_usage": True, "historical_generation": admitted["generation"],
                "authorizing_assignment_ref": authorizer, "authorizing_generation": authorizing_generation},
            stream=span_stream, transaction=tx)
        if receipt.status.value != "committed":
            raise WorkValidationError("late observation commit unproved; do not retry")
        return engine._usage_record(writer.get_identity(ref))

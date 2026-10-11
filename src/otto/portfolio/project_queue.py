"""Finite owner queue composition over WRK enrollment and ordinary DAT CAS.

No queue status is persisted: all consumers join one current document to Work.
Calls run on the existing serialized owner lane, never a second Store writer.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

from herzchen.content import CONTENT_SCHEMA_REVISION, ContentDocument, ContentRevision
from herzchen.contracts import ResourceRef, TransactionContext, canonical_json, canonical_request_digest
from .herzchen_binding import _json_value, _receipt_dict

SCHEMA = "otto.portfolio.queue.v1"
MAX_PROJECTS = 32
MAX_BYTES = 8192
CONSUMERS = ("root", "continuation", "observer")


def identity(value: Any) -> ResourceRef:
    ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    return ResourceRef(ref.authority, ref.kind, ref.id)


def queue_locator(portfolio: ResourceRef) -> ResourceRef:
    return ResourceRef(portfolio.authority, "dat.content.document",
                       "queue-" + sha256(canonical_json(identity(portfolio).to_dict()).encode()).hexdigest()[:28])


class ProjectQueue:
    """One owner-bound locator, reused by root, continuation and observer reads."""

    def __init__(self, operations: Any):
        self.ops = operations
        self.binding = operations.queue_binding

    def _authorize(self, actor: str):
        if self.binding is None:
            raise PermissionError("owner queue portfolio/root binding is unavailable")
        bound = self.binding["owner"]
        if self.ops._actor(actor) != bound:
            raise PermissionError("queue requires the authenticated bound owner")
        root = self.ops.assignments_port.get(identity(self.binding["root"]))
        if (root.role != "orchestrator" or identity(root.scope) != identity(self.binding["portfolio"])
                or getattr(root.status, "value", root.status) not in {"queued", "running", "active", "assigned", "reassigned"}):
            raise PermissionError("queue root assignment is no longer current")
        default_ref = ResourceRef(bound.authority, "wrk.orchestrator-default", "default-" +
            sha256(canonical_json(identity(self.binding["portfolio"]).to_dict()).encode()).hexdigest()[:28])
        default = self.ops._owner_reader.get_record(default_ref)
        if default is not None and (identity(default.payload.get("assignment_ref")) != identity(root.ref)
                or default.payload.get("generation") != root.generation):
            raise PermissionError("queue root differs from the current portfolio default")
        return bound, root

    def _order(self, values):
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_PROJECTS:
            raise ValueError("queue order must contain 1..32 canonical project identities")
        refs = [identity(v) for v in values]
        if any(r.kind != "work.project" or r.authority != self.binding["owner"].authority for r in refs):
            raise ValueError("queue project is foreign or not a Work project")
        if len(set(refs)) != len(refs):
            raise ValueError("queue project identity is duplicated")
        return [r.to_dict() for r in refs]

    def _content(self, order, rule):
        if rule not in {"continue", "pause"}:
            raise ValueError("queue continuation rule must be continue or pause")
        value = {"schema": SCHEMA, "portfolio_ref": identity(self.binding["portfolio"]).to_dict(),
                 "root_ref": identity(self.binding["root"]).to_dict(), "order": self._order(order), "rule": rule}
        if len(canonical_json(value).encode()) > MAX_BYTES:
            raise ValueError("queue document exceeds 8192 bytes")
        return value

    def _head(self):
        observed = _json_value(self.ops.content_port.read(self.binding["locator"]))
        if not observed:
            raise ValueError("canonical queue is missing; owner must seed the authorized existing order")
        document = observed.get("document", {})
        if (document.get("maintainer") != self.binding["owner"].actor
                or document.get("role") != "project-queue"
                or identity(document.get("authoring_scope")) != identity(self.binding["portfolio"])
                or document.get("visibility") != "private" or document.get("import_mode") != "owned"
                or document.get("writable") is not True):
            raise PermissionError("canonical queue document ownership/visibility/scope differs")
        content = observed.get("revision", {}).get("content")
        if not isinstance(content, Mapping) or dict(content) != self._content(content.get("order"), content.get("rule")):
            raise ValueError("canonical queue schema or portfolio/root differs")
        return observed, dict(content)

    def _project(self, ref, *, enrolled=True):
        record = self.ops._owner_reader.get_record(identity(ref))
        if record is None or identity(record.ref) != identity(ref):
            raise ValueError("queue project does not exist")
        relation = record.payload.get("metadata", {}).get("otto_orchestrator")
        if relation is not None:
            if (not isinstance(relation, Mapping)
                    or identity(relation.get("portfolio_ref")) != identity(self.binding["portfolio"])
                    or identity(relation.get("project_ref")) != identity(ref)):
                raise ValueError("queue project supervision has foreign portfolio/project")
            supervisor_ref = ResourceRef.from_dict(relation.get("assignment_ref"))
            supervisor = self.ops.assignments_port.get(identity(supervisor_ref))
            if (supervisor.ref != supervisor_ref or supervisor.role != "orchestrator"
                    or identity(supervisor.scope) != identity(self.binding["portfolio"])
                    or supervisor.generation != relation.get("generation")
                    or getattr(supervisor.status, "value", supervisor.status) not in
                    {"queued", "running", "active", "assigned", "reassigned"}):
                raise ValueError("queue project supervisor is stale, foreign or revoked")
        elif enrolled:
            raise ValueError("queue project lacks canonical portfolio enrollment")
        return record, relation

    def read(self, *, actor: str, consumer: str = "root"):
        common = {"schema": SCHEMA, "read_only": True, "provider_called": False, "dispatch": False,
                  "consumer": consumer}
        try:
            self._authorize(actor)
            if consumer not in CONSUMERS:
                raise ValueError("unsupported queue consumer")
            observed, content = self._head()
            rows = []
            for index, ref in enumerate(content["order"]):
                record, relation = self._project(ref)
                rows.append({"position": index, "project_ref": _json_value(record.ref),
                             "title": record.payload.get("title"), "lifecycle": record.payload.get("lifecycle"),
                             "readiness": _json_value(record.payload.get("readiness")),
                             "acceptance": _json_value(record.payload.get("acceptance")),
                             "enrolled": relation is not None})
            return {**common, "outcome": "read", "queue_ref": observed["current_revision"],
                    "locator": self.binding["locator"].to_dict(), **content, "projects": rows,
                    "terminal_project_ref": content["order"][-1],
                    "next_action": "Inspect genuine final disposition and existing setup separately; queue membership never activates."}
        except Exception as exc:
            return {**common, "outcome": "held", "reason": str(exc), "projects": [], "retry": False}

    def _envelope(self, *, actor, key, content, base, intent):
        target = self.binding["locator"]
        document = ContentDocument(target, "project-queue", "private", "read", actor.actor,
                                   authoring_scope=identity(self.binding["portfolio"]))
        revision = ContentRevision(target, "rev-" + intent[:24], content, actor,
                                   parent_revision=base, initial=base is None)
        operation = "dat.content.document.create" if base is None else "dat.content.revision.append"
        payload = {"document": document, "revision": revision}
        context = TransactionContext(actor, key, "0" * 64, expected_revision=base,
                                     expected_version=0 if base is None else None, causation_id=intent)
        digest = canonical_request_digest(logical_request_key=key, operation=operation,
            schema_revision=CONTENT_SCHEMA_REVISION, target=target, actor=actor, payload=payload, context=context)
        context = TransactionContext(actor, key, digest, expected_revision=base,
                                     expected_version=0 if base is None else None, causation_id=intent)
        builder = self.ops.content_port.build_create_document if base is None else self.ops.content_port.build_append_revision
        return builder(context, document, revision)

    def apply(self, *, actor: str, request_id: str, operation: str, order: list,
              expected_revision=None, project_ref=None, predecessor_ref=None, rule="continue"):
        result = {"schema": SCHEMA, "outcome": "held", "enrollment": None, "publication": None,
                  "queued": False, "provider_called": False, "dispatch": False, "retry": False}
        stage = "validation"
        try:
            authenticated, root = self._authorize(actor)
            if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
                raise ValueError("queue request key must contain 1..200 characters")
            if operation not in {"seed", "after"}:
                raise ValueError("unsupported queue operation")
            prefix = self._order(order)
            if operation == "seed":
                if any(v is not None for v in (expected_revision, project_ref, predecessor_ref)):
                    raise ValueError("seed does not accept append fields")
                content = self._content(prefix, rule)
            else:
                if not isinstance(expected_revision, str) or not expected_revision:
                    raise ValueError("queue-after requires the exact queue revision")
                if identity(predecessor_ref).to_dict() != prefix[-1]:
                    raise ValueError("predecessor must be the exact existing tail")
                project = identity(project_ref).to_dict()
                if project in prefix:
                    raise ValueError("duplicate or self queue entry")
                content = self._content(prefix + [project], rule)
            intent_input = {"operation": operation, "order": prefix, "expected_revision": expected_revision,
                            "project_ref": project_ref, "predecessor_ref": predecessor_ref, "rule": rule}
            intent = sha256(canonical_json(intent_input).encode()).hexdigest()
            envelope = self._envelope(actor=authenticated, key=request_id + ":publish", content=content,
                                      base=expected_revision, intent=intent)
            prior = _receipt_dict(self.ops._receipt(request_id + ":publish"))
            if prior:
                if prior["request_digest"] != envelope.context.request_digest:
                    raise ValueError("changed-input replay conflicts with retained publication")
                result["publication"] = prior
                if prior["status"] != "committed":
                    return {**result, "reason": "retained publication is unresolved; inspect exact receipt", "stage": "publication"}
                # Recover the original immutable revision, even after later extensions.
                published = _json_value(self.ops.content_port.read(envelope.payload["revision"].ref))
                if published.get("content") != content:
                    raise ValueError("retained publication readback differs")
                readback = self.read(actor=actor)
                if readback["outcome"] != "read" or readback["order"][:len(content["order"])] != content["order"]:
                    raise ValueError("current canonical readback no longer preserves the published prefix")
                return {**result, "outcome": "queued" if operation == "after" else "seeded", "queued": operation == "after",
                        "replayed": True, "readback": readback, "enrollment": {"outcome": "verified", "enrolled": True}}
            for ref in prefix:
                self._project(ref)
            if operation == "seed":
                if self.ops.content_port.read(self.binding["locator"]):
                    raise ValueError("canonical queue already exists; seed cannot replace its order")
            else:
                observed, current = self._head()
                if observed["current_revision"]["revision"] != expected_revision or current["order"] != prefix:
                    raise ValueError("stale queue CAS base or reordered predecessor prefix")
                if current["rule"] != rule:
                    raise ValueError("queue-after cannot change the owner continuation rule")
                record, relation = self._project(project_ref, enrolled=False)
                requested_project = ResourceRef.from_dict(project_ref)
                receipt = _receipt_dict(self.ops._receipt(request_id + ":enroll"))
                if requested_project.revision is None or (receipt is None and record.ref != requested_project):
                    raise ValueError("queue-after requires the current pinned project revision")
                if record.payload.get("lifecycle") != "pending" or any(record.payload.get(k) is not None for k in ("manager", "worker", "execution", "budget")):
                    raise ValueError("queue-after requires an inert pending project")
                attach = {"target_assignment_ref": _json_value(root.ref), "target_assignment_revision": root.revision,
                          "target_assignment_generation": root.generation,
                          "projects": [{"project_ref": project_ref}], "request_binding": intent}
                if relation is None:
                    # Existing WRK preview validates assignment absence, revisions and default before effects.
                    self.ops.execute("work.orchestrator.projects.attach", {**attach, "preview": True},
                                     request_id=request_id + ":enroll-preview", actor=actor)
                elif receipt is None:
                    result["enrollment"] = {"outcome": "existing", "enrolled": True, "supervision": relation}
                stage = "enrollment"
                if relation is None or receipt is not None:
                    if receipt is not None and receipt["status"] != "committed":
                        return {**result, "stage": stage, "reason": "retained enrollment is unresolved; inspect exact receipt"}
                    # The existing operation compares request_binding before mutable project pins on replay.
                    enrollment = self.ops.execute("work.orchestrator.projects.attach", attach,
                                                  request_id=request_id + ":enroll", actor=actor)
                    result["enrollment"] = enrollment
                    if enrollment.get("outcome") not in {"attached", "replayed"}:
                        return {**result, "stage": stage, "reason": "enrollment did not commit"}
                self._project(project_ref)
            stage = "publication"
            result["publication"] = _receipt_dict(self.ops.content_port.execute(envelope))
            if result["publication"]["status"] != "committed":
                return {**result, "stage": stage, "reason": "queue publication did not commit"}
            readback = self.read(actor=actor)
            if readback["outcome"] != "read" or readback["order"] != content["order"]:
                raise ValueError("queue publication lacks canonical readback")
            return {**result, "outcome": "queued" if operation == "after" else "seeded", "queued": operation == "after",
                    "locator": self.binding["locator"].to_dict(), "readback": readback}
        except Exception as exc:
            # A thrown effect is never replayed here. Receipt reads distinguish known partial success.
            if stage in {"enrollment", "publication"}:
                enrollment_receipt = _receipt_dict(self.ops._receipt(request_id + ":enroll"))
                publication_receipt = _receipt_dict(self.ops._receipt(request_id + ":publish"))
                result.update(enrollment_receipt=enrollment_receipt, publication=publication_receipt)
                result["unknown_effect"] = publication_receipt is None if stage == "publication" else enrollment_receipt is None
                from herzchen.kernel.store import VersionConflictError, ReplayConflictError
                if isinstance(exc, (VersionConflictError, ReplayConflictError)):
                    result["unknown_effect"] = False
                result["recovery"] = {"request_key": request_id, "input": intent_input,
                    "enrollment_key": request_id + ":enroll", "publication_key": request_id + ":publish",
                    "locator": self.binding["locator"].to_dict(), "next_actor": "authenticated owner"}
                result["next_action"] = ("Inspect the exact retained effect before retry. A stale CAS requires a new pinned publication attempt after readback; preserve enrollment.")
            return {**result, "stage": stage, "reason": str(exc)}

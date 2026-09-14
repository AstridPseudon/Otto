"""Public finite Herzchen command/read binding for the OTT-03 facade.

The trusted bootstrap constructs the accepted Herzchen graph and injects only
its finite command port and read-only consumer reader. Otto owns neither
storage nor a second command/event implementation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class HerzchenBindingConfig:
    """Explicit authority and credential used to authenticate an Otto actor."""

    authority: str
    credential_ref: str

    def authenticated_actor(self, actor: str) -> Any:
        from herzchen.contracts import AuthenticatedActor

        return AuthenticatedActor(self.authority, actor, self.credential_ref)


def _json_value(value: Any) -> Any:
    """Serialize public Herzchen model values without reaching through them."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        import json

        return json.loads(to_json())
    if hasattr(value, "value"):
        return _json_value(value.value)
    return str(value)


def _record_dict(record: Any) -> dict[str, Any]:
    payload = _json_value(getattr(record, "payload", {}))
    return {
        "project_ref": _json_value(getattr(record, "ref", None)),
        "kind": _json_value(getattr(record, "kind", None) or payload.get("kind")),
        "title": _json_value(getattr(record, "title", None) or payload.get("title")),
        "name": _json_value(getattr(record, "name", None) or payload.get("name")),
        "lifecycle": _json_value(getattr(record, "lifecycle", None) or payload.get("lifecycle")),
        "readiness": _json_value(getattr(record, "readiness", None) or payload.get("readiness")),
        "revision": _json_value(getattr(getattr(record, "ref", None), "revision", None)),
        "version": _json_value(getattr(record, "version", None)),
        "payload": payload,
    }


def _receipt_dict(receipt: Any) -> Optional[dict[str, Any]]:
    if receipt is None:
        return None
    to_dict = getattr(receipt, "to_dict", None)
    return _json_value(to_dict() if callable(to_dict) else receipt)


class FiniteWorkOperations:
    """The real OTT-03 operation port over a finite command/read pair."""

    def __init__(
        self,
        *,
        port: Any,
        reader: Any,
        binding: HerzchenBindingConfig,
        sheet_port: Any = None,
        content_port: Any = None,
        assignments_port: Any = None,
        authoring_port: Any = None,
        create_open_port: Any = None,
    ) -> None:
        if port is None or reader is None:
            raise ValueError("port and reader are required for the canonical binding")
        self.port = port
        self.reader = reader
        self.binding = binding
        self.sheet_port = sheet_port
        self.content_port = content_port
        self.assignments_port = assignments_port
        self.authoring_port = authoring_port
        self.create_open_port = create_open_port

    def _actor(self, actor: str) -> Any:
        return self.binding.authenticated_actor(actor)

    def _events_for(self, receipt: Any) -> list[str]:
        receipt_dict = _receipt_dict(receipt) or {}
        wanted = set(receipt_dict.get("event_ids", []))
        if not wanted:
            return []
        return [event.event_id for event in self.reader.list_events() if getattr(event, "event_id", None) in wanted]

    def _result(self, record: Any, *, request_id: str, replayed: bool) -> dict[str, Any]:
        receipt = self.reader.get_receipt(request_id)
        observed = self.reader.get_record(record.ref)
        return {
            "outcome": "replayed" if replayed else "created",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(observed),
            "receipt": _receipt_dict(receipt),
            "replayed": replayed,
            "event_ids": self._events_for(receipt),
            "executable": False,
            "open": {"status": "not_requested"},
        }

    def _metadata(self, payload: Mapping[str, Any], request_id: str, template: Any) -> dict[str, Any]:
        edit = payload.get("edit", {})
        metadata = dict(edit.get("metadata", {})) if isinstance(edit.get("metadata", {}), Mapping) else {}
        for key, value in edit.items():
            if key not in {"title", "outcome", "metadata"}:
                metadata.setdefault(key, value)
        metadata.setdefault("template", template)
        metadata["otto_request"] = {"logical_request_key": request_id, "payload": dict(payload)}
        return metadata

    def execute(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if operation == "work.project.export":
            return self._export_project(payload, request_id=request_id)
        if operation == "work.project.import":
            return self._import_project(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.fence":
            return self._fence_assignment(payload, request_id=request_id)
        if operation == "work.responsibility.dispatch":
            return self._dispatch_assignment(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.create" and payload.get("open"):
            return self._create_and_open(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.create" and isinstance(payload.get("template"), Mapping):
            return self._create_from_template(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.open":
            return self._open_existing(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.edit":
            return self._revise(payload, request_id=request_id, actor=actor)
        if operation in {"work.pending.revisit", "work.pending.prerequisite-satisfied"}:
            return self._attention(operation, payload, request_id=request_id, actor=actor)
        if operation == "work.pending.admission":
            return self._admit(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.assign":
            return self._assign_roles(payload, request_id=request_id, actor=actor)
        if operation == "work.responsibility.handoff":
            return self._handoff(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.document.create":
            return self._create_document(payload, request_id=request_id, actor=actor)
        if operation == "work.pending.document.link":
            return self._link_document(payload, request_id=request_id, actor=actor)
        if operation != "work.pending.create":
            return self._unsupported(operation, request_id=request_id)
        if payload.get("open"):
            return self._unsupported(operation, request_id=request_id, code="canonical_open_endpoint_unavailable", message="the finite accepted work port has no canonical open/session endpoint")
        edit = payload.get("edit", {})
        actor_value = self._actor(actor)
        before = self.reader.get_receipt(request_id)
        try:
            record = self.port.create_pending_project(
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                logical_request_key=request_id,
                actor=actor_value,
                creator=actor_value,
                curator=actor_value,
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {
                    "outcome": "error",
                    "error": {"code": "replay_conflict", "message": str(exc), "operation": operation},
                    "replayed": False,
                    "event_ids": [],
                }
            raise
        return self._result(record, request_id=request_id, replayed=before is not None)

    @staticmethod
    def _key(request_id: str, suffix: str) -> str:
        return request_id + ":" + suffix

    def _record_ref(self, value: Any) -> Any:
        from herzchen.contracts import ResourceRef

        return ResourceRef.from_dict(value) if isinstance(value, Mapping) else value

    @staticmethod
    def _same_identity(left: Any, right: Any) -> bool:
        return (
            getattr(left, "authority", None),
            getattr(left, "kind", None),
            getattr(left, "id", None),
        ) == (
            getattr(right, "authority", None),
            getattr(right, "kind", None),
            getattr(right, "id", None),
        )

    def _receipt(self, request_id: str) -> Any:
        return self.reader.get_receipt(request_id)

    def _receipt_result(self, request_id: str, *, outcome: str, **values: Any) -> dict[str, Any]:
        receipt = self._receipt(request_id)
        result = {
            "outcome": outcome,
            "receipt": _receipt_dict(receipt),
            "replayed": bool(receipt and getattr(receipt, "replayed", False)),
            "event_ids": self._events_for(receipt),
        }
        result.update(values)
        return result

    def _export_project(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        """Export a typed pending project through the read-only Herzchen reader.

        The snapshot is deliberately a portable representation of public
        records.  It contains no Store, writer, SQLite path, or callback.  A
        consumer can pass it to another owner bootstrap's ``work.project.import``
        endpoint for passive adoption and later comparison.
        """

        from herzchen.contracts import ResourceRef

        try:
            project_ref = ResourceRef.from_dict(payload["project_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            return {"outcome": "error", "error": {"code": "invalid_project_ref", "message": str(exc)}, "event_ids": []}
        record = self.reader.get_record(project_ref)
        if record is None:
            return {"outcome": "error", "error": {"code": "project_not_found", "message": "project is not admitted"}, "event_ids": []}
        source = _record_dict(record)
        raw_payload = dict(source.get("payload", {}))
        tasks = []
        for raw_ref in raw_payload.get("tasks", ()):
            try:
                task = self.reader.get_record(self._record_ref(raw_ref))
            except Exception:
                task = None
            if task is not None:
                tasks.append(_record_dict(task))
        documents = []
        requested_documents = payload.get("document_refs", raw_payload.get("documents", ()))
        if not isinstance(requested_documents, (list, tuple)):
            return {"outcome": "error", "error": {"code": "invalid_document_refs", "message": "document_refs must be an array", "operation": "work.project.export"}, "event_ids": []}
        for raw_ref in requested_documents:
            try:
                document = self.reader.get_record(self._record_ref(raw_ref))
            except Exception:
                document = None
            if document is not None:
                document_value = _record_dict(document)
                current_revision = document_value.get("payload", {}).get("current_revision")
                if current_revision is not None:
                    try:
                        current_ref = self._record_ref(current_revision)
                        # DAT's public read resolves the revision's storage
                        # identity (the neutral reader intentionally does not
                        # expose revision rows as a second mutable identity).
                        revision_read = self.content_port.read(current_ref) if self.content_port is not None else {}
                        revision_payload = dict(revision_read) if isinstance(revision_read, Mapping) else None
                        if isinstance(revision_payload, Mapping) and isinstance(revision_payload.get("content"), (Mapping, list, tuple, str, int, float, bool, type(None))):
                            revision_payload["content_digest"] = sha256(
                                json.dumps(_json_value(revision_payload.get("content")), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                            ).hexdigest()
                            document_value["current_revision_record"] = {
                                "payload": _json_value(revision_payload),
                                "project_ref": _json_value(current_ref),
                                "revision": revision_payload.get("revision"),
                            }
                    except Exception as exc:
                        document_value["_revision_read_error"] = type(exc).__name__ + ": " + str(exc)
                documents.append(document_value)
        links = []
        requested_links = payload.get("association_refs", ())
        if not isinstance(requested_links, (list, tuple)):
            return {"outcome": "error", "error": {"code": "invalid_association_refs", "message": "association_refs must be an array", "operation": "work.project.export"}, "event_ids": []}
        for raw_ref in requested_links:
            try:
                association = self.reader.get_record(self._record_ref(raw_ref))
            except Exception:
                association = None
            if association is not None:
                links.append(_record_dict(association))
        snapshot = {
            "schema": "otto.project-transfer.v1",
            "source_ref": _json_value(record.ref),
            "project": source,
            "tasks": tasks,
            "documents": documents,
            "document_links": links,
            "transfer_limits": {
                "assignments": "provenance-only; source assignment identity and generation are not cloned",
                "sessions": "not cloned",
                "dispatch": "not cloned",
                "execution": "not cloned",
                "manager_launch": "not cloned",
                "budget_reserved": "not cloned",
            },
            "dispatch": False,
            "execution": False,
            "manager_launch": False,
            "budget_reserved": False,
        }
        digest = sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        snapshot["snapshot_digest"] = digest
        return {"outcome": "exported", "snapshot": snapshot, "snapshot_digest": digest, "request_id": request_id, "event_ids": []}

    def _import_project(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Passively import a project snapshot through ProjectSheet adoption.

        Import creates one new pending project in the destination authority,
        records the source identity and exact snapshot digest, and adopts the
        source's task/observation payload through the accepted ProjectSheet
        command port.  It never clones a source identity, assignment, session,
        dispatch, or budget authority and therefore cannot create a second
        writer graph.
        """

        if self.sheet_port is None:
            return self._unsupported("work.project.import", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet command port was not injected")
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("schema") != "otto.project-transfer.v1":
            return {"outcome": "error", "error": {"code": "invalid_transfer_snapshot", "message": "snapshot must be an otto.project-transfer.v1 object", "operation": "work.project.import"}, "event_ids": []}
        source = snapshot.get("project")
        if not isinstance(source, Mapping):
            return {"outcome": "error", "error": {"code": "invalid_transfer_snapshot", "message": "snapshot.project must be an object", "operation": "work.project.import"}, "event_ids": []}
        canonical = dict(snapshot)
        supplied_digest = canonical.pop("snapshot_digest", None)
        computed_digest = sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if supplied_digest != computed_digest:
            return {"outcome": "error", "error": {"code": "transfer_digest_mismatch", "message": "snapshot digest does not match its public records", "operation": "work.project.import"}, "event_ids": []}
        before = self._receipt(request_id)
        edit_payload = source.get("payload") if isinstance(source.get("payload"), Mapping) else source
        title = edit_payload.get("title") or edit_payload.get("name") or "Imported pending project"
        outcome = edit_payload.get("outcome", "")
        metadata = dict(edit_payload.get("metadata", {})) if isinstance(edit_payload.get("metadata"), Mapping) else {}
        metadata["otto_transfer"] = {"source_ref": _json_value(snapshot.get("source_ref")), "snapshot_digest": computed_digest, "mode": "passive-adoption"}
        actor_value = self._actor(actor)
        try:
            created = self.port.create_pending_project(
                title=title,
                outcome=outcome,
                logical_request_key=request_id,
                actor=actor_value,
                creator=actor_value,
                curator=actor_value,
                metadata=metadata,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project.import"}, "replayed": False, "event_ids": []}
            raise
        target_ref = created.ref
        raw_tasks = list(snapshot.get("tasks", ()))
        task_ids = {}
        for item in raw_tasks:
            value = item.get("payload") if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping) else item
            if isinstance(value, Mapping) and value.get("id"):
                task_ids[str(value["id"])] = str(value["id"])
        adopted_tasks = []
        for item in raw_tasks:
            value = item.get("payload") if isinstance(item, Mapping) and isinstance(item.get("payload"), Mapping) else item
            if not isinstance(value, Mapping):
                continue
            task = dict(value)
            dependencies = []
            for dependency in task.get("dependencies", ()):
                dep_id = dependency.get("id") if isinstance(dependency, Mapping) else dependency
                if dep_id is not None and str(dep_id) in task_ids:
                    dependencies.append(task_ids[str(dep_id)])
            task["dependencies"] = dependencies
            adopted_tasks.append(task)
        adopted_source = dict(edit_payload)
        adopted_source["tasks"] = adopted_tasks
        # DAT content remains an independent source-owned identity.  Preserve
        # its full public record and association under adoption metadata rather
        # than manufacturing a destination content revision; C38 explicitly
        # permits deferred seeds to retain unknown fields without cloning live
        # grants, sessions, or accepted results.
        adopted_source["documents"] = list(snapshot.get("documents", ()))
        adopted_source["document_links"] = list(snapshot.get("document_links", ()))
        try:
            adopted = self.sheet_port.adopt_existing_effort(
                adopted_source,
                project=target_ref,
                logical_request_key=request_id + ":adoption",
                actor=actor_value,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project.import"}, "replayed": False, "event_ids": []}
            raise
        # A deferred seed keeps unknown source fields in the adoption record,
        # but an existing document must remain usable by the receiving owner.
        # Recreate each immutable public revision as a new target-owned
        # document through DAT's command port, then recreate its named links.
        # This deliberately maps identities instead of cloning the source
        # document/assignment/session/allowance rows.
        restored_documents: list[dict[str, Any]] = []
        document_map: dict[tuple[str, str, str], Any] = {}
        for index, item in enumerate(snapshot.get("documents", ())):
            if not isinstance(item, Mapping):
                continue
            record_payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            document_value = record_payload.get("document") if isinstance(record_payload.get("document"), Mapping) else {}
            source_ref_value = document_value.get("ref") if isinstance(document_value.get("ref"), Mapping) else item.get("project_ref")
            if not isinstance(source_ref_value, Mapping):
                continue
            source_ref = self._record_ref(source_ref_value)
            source_key = (source_ref.authority, source_ref.kind, source_ref.id)
            revision_record = item.get("current_revision_record") if isinstance(item.get("current_revision_record"), Mapping) else {}
            revision_payload = revision_record.get("payload") if isinstance(revision_record.get("payload"), Mapping) else {}
            content = revision_payload.get("content", {})
            restore_request = request_id + ":document:" + str(index)
            restored = self._create_document(
                {
                    "project_ref": _json_value(target_ref),
                    "document_id": "restored-" + sha256((computed_digest + ":" + ":".join(source_key)).encode("utf-8")).hexdigest()[:28],
                    "role": document_value.get("role", "supporting"),
                    "visibility": document_value.get("visibility", "private"),
                    "access_mode": document_value.get("access_mode", "read"),
                    "content": content,
                },
                request_id=restore_request,
                actor=actor,
            )
            if restored.get("outcome") not in {"created", "replayed"}:
                return {
                    "outcome": "error",
                    "error": {"code": "document_restore_failed", "message": "target-owned document restoration failed", "operation": "work.project.import", "source_ref": _json_value(source_ref), "detail": restored},
                    "replayed": False,
                    "event_ids": [],
                }
            target_document_ref = restored.get("document_ref")
            document_map[source_key] = target_document_ref
            source_content_digest = revision_payload.get("content_digest")
            target_content_digest = None
            content_equal = False
            try:
                target_content_read = self.content_port.read(self._record_ref(target_document_ref)) if self.content_port is not None else {}
                target_revision_read = target_content_read.get("revision") if isinstance(target_content_read, Mapping) else None
                target_content = target_revision_read.get("content") if isinstance(target_revision_read, Mapping) else None
                target_content_digest = sha256(
                    json.dumps(_json_value(target_content), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                content_equal = source_content_digest == target_content_digest
            except Exception:
                content_equal = False
            target_record = restored.get("record") if isinstance(restored.get("record"), Mapping) else {}
            target_payload = target_record.get("payload") if isinstance(target_record.get("payload"), Mapping) else {}
            restored_documents.append({
                "source_ref": _json_value(source_ref),
                "target_ref": target_document_ref,
                "source_revision": revision_payload.get("revision"),
                "target_revision": target_payload.get("current_revision"),
                "content_digest": source_content_digest,
                "target_content_digest": target_content_digest,
                "content_equal": content_equal,
                "receipt": restored.get("receipt"),
                "event_ids": restored.get("event_ids", []),
            })
        restored_links: list[dict[str, Any]] = []
        for index, item in enumerate(snapshot.get("document_links", ())):
            if not isinstance(item, Mapping):
                continue
            link_payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            association = link_payload.get("association") if isinstance(link_payload.get("association"), Mapping) else {}
            source_document = association.get("document") if isinstance(association.get("document"), Mapping) else {}
            source_document_ref = source_document.get("ref") if isinstance(source_document.get("ref"), Mapping) else None
            if not isinstance(source_document_ref, Mapping):
                continue
            source_key = (str(source_document_ref.get("authority")), str(source_document_ref.get("kind")), str(source_document_ref.get("id")))
            target_document_ref = document_map.get(source_key)
            if target_document_ref is None:
                continue
            restored_link = self._link_document(
                {
                    "project_ref": _json_value(target_ref),
                    "document_ref": target_document_ref,
                    "namespace": association.get("namespace", "project.documents"),
                    "key": association.get("key", "document"),
                    "access_mode": association.get("access_mode", "read"),
                },
                request_id=request_id + ":document-link:" + str(index),
                actor=actor,
            )
            if restored_link.get("outcome") not in {"linked", "replayed"}:
                return {
                    "outcome": "error",
                    "error": {"code": "document_link_restore_failed", "message": "target-owned document link restoration failed", "operation": "work.project.import", "detail": restored_link},
                    "replayed": False,
                    "event_ids": [],
                }
            restored_links.append({
                "source": _json_value(source_document_ref),
                "target": target_document_ref,
                "namespace": association.get("namespace"),
                "key": association.get("key"),
                "association_ref": restored_link.get("association_ref"),
                "receipt": restored_link.get("receipt"),
                "event_ids": restored_link.get("event_ids", []),
            })
        receipt = self._receipt(request_id)
        adoption_receipt = self._receipt(request_id + ":adoption")
        observed = self.reader.get_record(target_ref)
        tasks = list(observed.payload.get("tasks", ())) if observed is not None else []
        event_ids = self._events_for(receipt) + [item for item in self._events_for(adoption_receipt) if item not in self._events_for(receipt)]
        for item in restored_documents + restored_links:
            for event_id in item.get("event_ids", ()):
                if event_id not in event_ids:
                    event_ids.append(event_id)
        return {
            "outcome": "replayed" if before is not None else "imported",
            "project_ref": _json_value(target_ref),
            "source_ref": _json_value(snapshot.get("source_ref")),
            "snapshot_digest": computed_digest,
            "record": None if observed is None else _record_dict(observed),
            "adoption": _json_value(adopted),
            "receipt": _receipt_dict(receipt),
            "adoption_receipt": _receipt_dict(adoption_receipt),
            "task_refs": _json_value(tasks),
            "content_provenance": {
                "documents": len(snapshot.get("documents", ())),
                "document_links": len(snapshot.get("document_links", ())),
                "destination_content_identity_created": bool(restored_documents),
                "restored_documents": restored_documents,
                "restored_document_links": restored_links,
                "source_records_retained_in_adoption_metadata": True,
            },
            "dispatch": False,
            "execution": False,
            "manager_launch": False,
            "budget_reserved": False,
            "replayed": before is not None,
            "event_ids": event_ids,
        }

    def _fence_assignment(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        """Validate the current generation before a manager handoff.

        Herzchen's assignment owner performs the generation check.  The finite
        endpoint returns the typed current assignment and never exposes the
        Store or a dispatch callback to the consumer.
        """

        if self.assignments_port is None:
            return self._unsupported("work.responsibility.fence", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        try:
            assignment_ref = self._record_ref(payload["manager_assignment_ref"])
            generation = int(payload["expected_generation"])
            assignment = self.assignments_port.fence(assignment_ref, generation)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "stale_assignment_fence", "message": str(exc), "operation": "work.responsibility.fence"}, "replayed": False, "event_ids": [], "dispatch": False}
        return {"outcome": "fenced", "manager_assignment_ref": _json_value(getattr(assignment, "ref", assignment_ref)), "assignment": self._assignment_dict(assignment), "expected_generation": generation, "dispatch": False, "execution": False, "request_id": request_id, "event_ids": []}

    def _dispatch_assignment(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        """Attempt a typed dispatch through the public assignment command port.

        The generation fence is evaluated by Herzchen after a consumer reopens
        the owner store.  This endpoint deliberately returns no dispatch or
        execution side effect when an old owner presents a stale generation.
        """

        if self.assignments_port is None:
            return self._unsupported("work.responsibility.dispatch", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        try:
            assignment_ref = self._record_ref(payload["manager_assignment_ref"])
            generation = int(payload["expected_generation"])
            input_refs = tuple(self._record_ref(item) for item in payload.get("input_refs", ()))
            dispatch = self.assignments_port.dispatch(
                assignment_ref,
                input_refs=input_refs,
                action=payload.get("action"),
                expected_generation=generation,
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            error_name = type(exc).__name__
            code = "stale_assignment_dispatch" if error_name in {"StaleAssignmentError", "WorkNotFoundError"} else "assignment_dispatch_rejected"
            return {"outcome": "error", "error": {"code": code, "message": str(exc), "operation": "work.responsibility.dispatch"}, "replayed": False, "event_ids": [], "dispatch": False, "execution": False}
        receipt = self._receipt(request_id)
        return {"outcome": "dispatched", "dispatch": _json_value(dispatch), "receipt": _receipt_dict(receipt), "replayed": False, "event_ids": self._events_for(receipt), "execution": False}

    def _create_and_open(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.create_open_port is None:
            result = self._unsupported(
                "work.pending.create",
                request_id=request_id,
                code="canonical_create_and_open_finite_endpoint_unavailable",
                message=(
                    "the trusted owner create-and-open bridge was not injected; "
                    "sequential consumer create then open is forbidden"
                ),
            )
            result.update({
                "open": {"status": "unsupported", "recovery_pending": False, "recovery_status": "not_requested"},
                "executable": False,
            })
            return result

        edit = payload.get("edit", {})
        before = self.reader.get_receipt(request_id)
        selected_resource = payload.get("template") if isinstance(payload.get("template"), Mapping) else None
        selected_parameters = payload.get("template_parameters", {})
        try:
            opened = self.create_open_port.create_pending_and_open(
                actor=self._actor(actor),
                request_id=request_id,
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                metadata=self._metadata(payload, request_id, payload.get("template", "blank")),
                template_resource=selected_resource,
                template_parameters=selected_parameters,
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {
                    "outcome": "error",
                    "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"},
                    "replayed": False,
                    "event_ids": [],
                }
            if selected_resource is not None and type(exc).__name__ in {
                "TemplateError", "TemplateValidationError", "TemplateParameterError",
                "TemplateReferenceError", "SheetError", "ValueError", "TypeError",
            }:
                result = dict(self._template_error(exc))
                result["open"] = {
                    "status": "not_requested",
                    "recovery_pending": False,
                    "recovery_status": "not_requested",
                }
                return result
            raise

        status = opened.get("status", "unknown")
        project_ref = opened.get("project_ref")
        if status in {"occupied", "actor_occupied"}:
            return {
                "outcome": "occupied",
                "project_ref": None,
                "receipt": None,
                "project_receipt": None,
                "replayed": False,
                "event_ids": [],
                "executable": False,
                "open": _json_value(opened),
            }

        receipt_keys = (
            request_id + ":actor",
            request_id,
            request_id + ":project",
            request_id + ":project-created",
            request_id + ":template",
            request_id + ":materialized",
            request_id + ":materialize-failure",
            request_id + ":materialize-failure:actor",
        )
        event_ids = {
            event_id
            for key in receipt_keys
            for event_id in ((_receipt_dict(self.reader.get_receipt(key)) or {}).get("event_ids", []))
        }
        record = None
        if project_ref is not None:
            record = self.reader.get_record(self._record_ref(project_ref))
        template = opened.get("template")
        task_refs = opened.get("task_refs", [])
        task_records = []
        if isinstance(task_refs, (list, tuple)):
            seed_tasks = []
            if isinstance(selected_resource, Mapping):
                seed = selected_resource.get("seed", {})
                if isinstance(seed, Mapping):
                    raw_tasks = seed.get("tasks", seed.get("task_bundle", ()))
                    if isinstance(raw_tasks, (list, tuple)):
                        seed_tasks = list(raw_tasks)
            for index, task_ref in enumerate(task_refs):
                task_record = self.reader.get_record(self._record_ref(task_ref))
                raw = seed_tasks[index] if index < len(seed_tasks) and isinstance(seed_tasks[index], Mapping) else {}
                task_records.append({
                    "local_id": str(raw.get("local_id", raw.get("id", raw.get("key", "task-" + str(index))))),
                    "ref": _json_value(task_ref),
                    "record": None if task_record is None else _record_dict(task_record),
                })
        return {
            "outcome": "replayed" if before is not None else ("created" if status == "opened" else status),
            "project_ref": _json_value(project_ref),
            "record": None if record is None else _record_dict(record),
            "receipt": _receipt_dict(self.reader.get_receipt(request_id)),
            "project_receipt": _receipt_dict(self.reader.get_receipt(request_id + ":project")),
            "template_receipt": _receipt_dict(opened.get("template_receipt")),
            "template": _json_value(template),
            "template_ref": None if template is None else _json_value(getattr(template, "ref", None)),
            "template_revision": None if template is None else getattr(template, "revision", None),
            "tasks": task_records,
            "task_refs": [_json_value(item["ref"]) for item in task_records],
            "replayed": before is not None,
            "event_ids": [
                event.event_id
                for event in self.reader.list_events()
                if getattr(event, "event_id", None) in event_ids
            ],
            "executable": False,
            "activation": False,
            "dispatch": False,
            "manager_launch": False,
            "budget_reserved": False,
            "session_task_created": False,
            "execution": False,
            "open": _json_value(opened),
        }

    @staticmethod
    def _typed_template(value: Mapping[str, Any], parameters: Optional[Mapping[str, Any]] = None) -> Any:
        """Construct and validate the declared WorkTemplate before any write."""

        from herzchen.packs.templates import WorkTemplate, render_template, validate_template

        if not isinstance(value, Mapping):
            raise ValueError("template must be a JSON resource object")
        template_id = value.get("id")
        revision = value.get("revision", value.get("version"))
        if "revision" in value and "version" in value and value["revision"] != value["version"]:
            raise ValueError("template revision and version must agree")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("template.id must be non-blank text")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("template.revision or template.version must be non-blank text")
        parameter_schema = value.get("parameters")
        seed = value.get("seed")
        if not isinstance(parameter_schema, Mapping):
            raise ValueError("template.parameters must be an object")
        if not isinstance(seed, Mapping):
            raise ValueError("template.seed must be an object")
        template = validate_template(WorkTemplate(template_id, revision, dict(parameter_schema), dict(seed)))
        # Render once before the canonical project create so malformed seed
        # markers or missing declared defaults cannot leave a project behind.
        render_template(template, parameters)
        return template

    @staticmethod
    def _template_error(exc: Exception) -> Mapping[str, Any]:
        return {
            "outcome": "error",
            "error": {"code": "invalid_template_resource", "message": str(exc), "operation": "work.project-sheet.instantiate-template"},
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }

    def _create_from_template(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.sheet_port is None:
            return self._unsupported("work.pending.create", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet template command port was not injected")
        try:
            template = self._typed_template(payload["template"], payload.get("template_parameters"))
        except Exception as exc:
            return self._template_error(exc)
        prior = self._receipt(request_id)
        edit = payload.get("edit", {})
        try:
            project = self.port.create_pending_project(
                title=edit.get("title"),
                outcome=edit.get("outcome", ""),
                logical_request_key=request_id + "-project",
                actor=self._actor(actor),
                creator=self._actor(actor),
                curator=self._actor(actor),
                metadata=self._metadata(payload, request_id, payload["template"]),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.create"}, "replayed": False, "event_ids": [], "executable": False}
            raise
        project_ref = getattr(project, "ref", None)
        try:
            batch = self.sheet_port.instantiate_new_template(
                template,
                payload.get("template_parameters"),
                project=project_ref,
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            if type(exc).__name__ in {"ReplayConflictError", "TemplateError", "TemplateValidationError", "UnknownTemplateError", "SheetError"}:
                if type(exc).__name__ == "ReplayConflictError":
                    return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.project-sheet.instantiate-template"}, "replayed": False, "event_ids": [], "executable": False}
                return self._template_error(exc)
            raise
        batch_project = getattr(batch, "project", None)
        if project_ref is None:
            project_ref = getattr(batch_project, "ref", None)
        if project_ref is None and isinstance(batch, Mapping):
            project_ref = batch.get("project_ref")
        fresh = None if project_ref is None else self.reader.get_record(project_ref)
        returned_project_ref = getattr(fresh, "ref", project_ref)
        mappings = getattr(batch, "mappings", {})
        if not isinstance(mappings, Mapping) and isinstance(batch, Mapping):
            mappings = batch.get("mappings", {})
        task_records = []
        if isinstance(mappings, Mapping):
            for local_id, task_ref in mappings.items():
                record = self.reader.get_record(task_ref)
                task_records.append({
                    "local_id": str(local_id),
                    "ref": _json_value(task_ref),
                    "record": None if record is None else _record_dict(record),
                })
        receipt = getattr(batch, "receipt", None)
        if receipt is None and isinstance(batch, Mapping):
            receipt = batch.get("receipt")
        receipt = receipt or self._receipt(request_id)
        project_receipt = self.reader.get_receipt(request_id + "-project")
        event_ids = self._events_for(receipt) + [event_id for event_id in self._events_for(project_receipt) if event_id not in self._events_for(receipt)]
        return {
            "outcome": "replayed" if prior is not None else "created",
            "project_ref": _json_value(returned_project_ref),
            "record": None if fresh is None else _record_dict(fresh),
            "template": _json_value(template),
            "template_ref": _json_value(template.ref),
            "template_revision": template.revision,
            "tasks": task_records,
            "task_refs": [_json_value(item["ref"]) for item in task_records],
            "receipt": _receipt_dict(receipt),
            "project_receipt": _receipt_dict(project_receipt),
            "replayed": prior is not None,
            "event_ids": event_ids,
            "executable": False,
            "activation": False,
            "dispatch": False,
            "budget_reserved": False,
            "task_created": bool(task_records),
            "session_created": False,
        }

    @staticmethod
    def _open_dict(result: Any) -> dict[str, Any]:
        handle = getattr(result, "handle", None)
        return {
            "status": getattr(result, "status", "unknown"),
            "scope": _json_value(getattr(result, "scope", None)),
            "project_ref": _json_value(getattr(result, "project_ref", None)),
            "session_id": getattr(handle, "session_id", None),
            "target_kind": getattr(handle, "target_kind", None),
            "base_revision": getattr(handle, "base_revision", None),
            "error": getattr(result, "error", None),
            "recovery_pending": bool(getattr(result, "recovery_pending", False)),
            "recovery_status": "pending" if getattr(result, "recovery_pending", False) else "not_requested",
        }

    def _open_existing(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.authoring_port is None:
            return self._unsupported("work.pending.open", request_id=request_id, code="canonical_authoring_port_unavailable", message="accepted AuthoringSessionService command port was not injected")
        actor_value = self._actor(actor)
        ref = self._record_ref(payload["project_ref"])
        before = self._receipt(request_id)
        try:
            result = self.authoring_port.open(ref, actor_value, request_id=request_id, target_kind="project", base_revision=getattr(ref, "revision", None), purpose="otto", activity="editing", pending=True)
        except Exception as exc:
            if type(exc).__name__ in {"OccupiedError", "ActorOccupiedError"}:
                return self._receipt_result(request_id, outcome="occupied", project_ref=_json_value(ref), opened={"status": "occupied", "error": str(exc)})
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "authoring.open"}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="replayed" if before is not None else getattr(result, "status", "opened"), project_ref=_json_value(ref), opened=self._open_dict(result), replayed=before is not None)

    def _attention(self, operation: str, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        observation = {"kind": "revisit" if operation.endswith("revisit") else "prerequisite-satisfied", "payload": dict(payload), "dispatch": False}
        prior = self._receipt(request_id)
        try:
            result_ref = self.port.set_readiness(self._record_ref(payload["project_ref"]), observation, logical_request_key=request_id, actor=self._actor(actor))
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": operation}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="attention-created", project_ref=_json_value(self._record_ref(payload["project_ref"])), attention_ref=_json_value(result_ref), readiness={"dispatch": False}, executable=False, replayed=prior is not None)

    def _admit(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.sheet_port is None:
            return self._unsupported("work.pending.admission", request_id=request_id, code="canonical_project_sheet_port_unavailable", message="accepted ProjectSheet command port was not injected")
        frame = dict(payload["frame"])
        sheet = {
            "outcome": frame["outcome"],
            "manager_action": payload["choice"],
            "resources": {key: frame[key] for key in ("recipient", "route", "authority")},
        }
        prior = self._receipt(request_id)
        try:
            result = self.sheet_port.apply(self._record_ref(payload["project_ref"]), sheet, logical_request_key=request_id, actor=self._actor(actor), next_action=payload["choice"])
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.admission"}, "replayed": False, "event_ids": []}
            raise
        return self._receipt_result(request_id, outcome="admitted", project_ref=_json_value(getattr(getattr(result, "project", None), "ref", None)), admission={"choice": payload["choice"], "frame": frame}, executable=False, replayed=prior is not None)

    def _assign_roles(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.assignments_port is None:
            return self._unsupported("work.responsibility.assign", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        actor_value = self._actor(actor)
        ref = self._record_ref(payload["project_ref"])
        roles = payload["roles"]
        assignments: dict[str, Any] = {}
        parent_receipt = None
        executor_values = roles["executor"] if isinstance(roles["executor"], list) else [roles["executor"]]
        role_inputs = [("parent", [self._record_ref(roles["parent"])])]
        role_inputs.extend((("manager", [roles["manager"]]), ("executor", executor_values)))
        event_ids: list[str] = []
        for role, principals in role_inputs:
            for index, principal in enumerate(principals):
                key = self._key(request_id, role + (":" + str(index) if len(principals) > 1 else ""))
                prior = self._receipt(key)
                try:
                    assignment = self.assignments_port.assign(ref, role=role, principal=principal, manager=roles["manager"], logical_request_key=key, actor=actor_value)
                except Exception as exc:
                    if type(exc).__name__ == "ReplayConflictError":
                        return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.responsibility.assign"}, "replayed": False, "event_ids": []}
                    raise
                receipt = self._receipt(key)
                assignments[key] = {"ref": _json_value(getattr(assignment, "ref", None)), "role": role, "principal": _json_value(principal), "receipt": _receipt_dict(receipt), "replayed": prior is not None}
                event_ids.extend(self._events_for(receipt))
                if role == "parent":
                    parent_receipt = receipt
        manager_assignment_ref = next(
            (item["ref"] for item in assignments.values() if item["role"] == "manager"),
            None,
        )
        return {"outcome": "assigned", "project_ref": _json_value(ref), "roles": assignments, "manager_assignment_ref": manager_assignment_ref, "parent_receipt": _receipt_dict(parent_receipt), "event_ids": event_ids, "replayed": all(item["replayed"] for item in assignments.values()) if assignments else False, "executable": False}

    @staticmethod
    def _assignment_dict(assignment: Any) -> dict[str, Any]:
        """Return only the declared assignment value, including durable history."""

        payload = _json_value(getattr(assignment, "payload", {}))
        return {
            "ref": _json_value(getattr(assignment, "ref", None)),
            "assignment_ref": _json_value(getattr(assignment, "assignment_ref", getattr(assignment, "ref", None))),
            "scope": _json_value(getattr(assignment, "scope", None)),
            "role": getattr(assignment, "role", None),
            "principal": _json_value(getattr(assignment, "principal", None)),
            # The accepted reassignment operation changes the typed principal;
            # retain the raw payload as well because its manager attribution is
            # historical metadata owned by Herzchen.
            "manager": _json_value(getattr(assignment, "principal", payload.get("manager") if isinstance(payload, Mapping) else None)),
            "stored_manager": payload.get("manager") if isinstance(payload, Mapping) else None,
            "generation": getattr(assignment, "generation", None),
            "status": _json_value(getattr(assignment, "status", None)),
            "history": _json_value(getattr(assignment, "history", ())),
            "payload": payload,
        }

    @staticmethod
    def _handoff_context_token(context: Mapping[str, Any]) -> str:
        """Encode typed context in the accepted assignment history reason field."""

        encoded = base64.urlsafe_b64encode(
            json.dumps(dict(context), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return "otto-handoff-context-" + encoded

    @staticmethod
    def _handoff_context_from_assignment(assignment: Any, *, request_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        history = getattr(assignment, "history", ())
        if not history:
            return None
        prefix = "otto-handoff-context-"
        fallback = None
        for item in reversed(history):
            reason = item.get("reason") if isinstance(item, Mapping) else None
            if not isinstance(reason, str) or not reason.startswith(prefix):
                continue
            value = reason[len(prefix):]
            try:
                padded = value + "=" * (-len(value) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(decoded, Mapping):
                continue
            decoded_context = dict(decoded)
            fallback = fallback or decoded_context
            if request_id is None or decoded_context.get("request_id") == request_id:
                return decoded_context
        # Contexts written by the accepted pre-v2 implementation have no
        # request_id.  They are still replayable when they are the only
        # durable handoff context on the assignment.
        return fallback

    def _handoff(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.assignments_port is None:
            return self._unsupported("work.responsibility.handoff", request_id=request_id, code="canonical_assignments_port_unavailable", message="accepted ResponsibilityAssignments command port was not injected")
        assignment_value = payload.get("manager_assignment_ref")
        if not isinstance(assignment_value, Mapping):
            return {
                "outcome": "error",
                "error": {"code": "manager_assignment_ref_required", "message": "real handoff requires the typed manager assignment reference returned by assign_roles", "operation": "work.responsibility.handoff"},
                "replayed": False,
                "event_ids": [],
                "executable": False,
            }
        from herzchen.contracts import ResourceRef

        project_ref = self._record_ref(payload["project_ref"])
        try:
            assignment_ref = ResourceRef.from_dict(assignment_value)
        except (TypeError, ValueError) as exc:
            return {"outcome": "error", "error": {"code": "malformed_manager_assignment_ref", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if assignment_ref.kind != "wrk.assignment":
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_ref", "message": "manager_assignment_ref must name a wrk.assignment", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if assignment_ref.authority != self.binding.authority:
            return {"outcome": "error", "error": {"code": "foreign_manager_assignment_ref", "message": "manager assignment belongs to another authority", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}

        # The bounded lookup is the accepted public assignment API.  There is
        # no manager-name inference, scope scan, private SQL, or side mirror.
        try:
            current = self.assignments_port.get(assignment_ref)
        except Exception as exc:
            return {"outcome": "error", "error": {"code": "unknown_manager_assignment_target", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        if getattr(current, "role", None) != "manager" or not self._same_identity(getattr(current, "scope", None), project_ref):
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_target", "message": "assignment is not the current manager assignment for this project", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        from_manager = payload["from_manager"]
        current_principal = getattr(current, "principal", None)
        current_status = getattr(current, "status", None)
        current_status = getattr(current_status, "value", current_status)
        if current_status not in {"queued", "reassigned"}:
            return {"outcome": "error", "error": {"code": "invalid_manager_assignment_status", "message": "manager assignment is not available for handoff", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
        prior = self._receipt(request_id)
        stored_context = self._handoff_context_from_assignment(current, request_id=request_id) if prior is not None else None
        if prior is None and current_principal != from_manager:
            return {"outcome": "error", "error": {"code": "stale_manager_assignment", "message": "from_manager does not match the current assignment principal/manager", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}

        context = {
            "kind": "otto.safe-responsibility-handoff",
            "project_ref": _json_value(project_ref),
            "manager_assignment_ref": _json_value(assignment_ref),
            "from_manager": from_manager,
            "to_manager": payload["to_manager"],
            "evidence_refs": _json_value(payload["evidence_refs"]),
            "consumption_refs": _json_value(payload["consumption_refs"]),
            "parent_obligation": _json_value(payload["parent_obligation"]),
            "from_generation": getattr(current, "generation", None),
            "request_id": request_id,
        }
        if prior is not None:
            if not isinstance(stored_context, Mapping):
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": "prior handoff receipt has no durable typed context", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            for key in ("kind", "project_ref", "manager_assignment_ref", "from_manager", "to_manager", "evidence_refs", "consumption_refs", "parent_obligation"):
                if stored_context.get(key) != context.get(key):
                    return {"outcome": "error", "error": {"code": "replay_conflict", "message": "same handoff request key was reused with changed input", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            latest_context = self._handoff_context_from_assignment(current)
            # A retry of the latest handoff must still observe its current
            # replacement.  An older exact request may be retried after a
            # later valid handoff: its durable context is in assignment
            # history, and replaying Herzchen's original receipt must not
            # revert the newer principal.
            if current_principal != stored_context.get("to_manager") and stored_context == latest_context:
                return {"outcome": "error", "error": {"code": "stale_manager_assignment", "message": "durable handoff target no longer matches the original replacement", "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            context = dict(stored_context)
        try:
            replacement = self.assignments_port.reassign(
                assignment_ref,
                principal=context["to_manager"],
                reason=self._handoff_context_token(context),
                expected_generation=context["from_generation"],
                logical_request_key=request_id,
                actor=self._actor(actor),
            )
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            if type(exc).__name__ in {"StaleAssignmentError", "WorkNotFoundError"}:
                return {"outcome": "error", "error": {"code": "stale_or_unknown_manager_assignment", "message": str(exc), "operation": "work.responsibility.handoff"}, "replayed": False, "event_ids": [], "executable": False}
            raise
        receipt = self._receipt(request_id)
        observed_context = self._handoff_context_from_assignment(replacement) or context
        return {
            "outcome": "replayed" if prior is not None else "handed-off",
            "safe_handoff": True,
            "project_ref": _json_value(project_ref),
            "manager_assignment_ref": _json_value(getattr(replacement, "ref", assignment_ref)),
            "assignment": self._assignment_dict(replacement),
            "handoff": observed_context,
            "receipt": _receipt_dict(receipt),
            "replayed": prior is not None,
            "event_ids": self._events_for(receipt),
            "executable": False,
            "activation": False,
            "dispatch": False,
            "budget_reserved": False,
            "task_created": False,
            "session_created": False,
        }

    def _content_context(self, operation: str, target: Any, request_id: str, actor: Any, payload: Mapping[str, Any], schema_revision: str) -> Any:
        from herzchen.contracts import TransactionContext, canonical_request_digest

        context = TransactionContext(actor, request_id, "0" * 64)
        digest = canonical_request_digest(logical_request_key=request_id, operation=operation, schema_revision=schema_revision, target=target, actor=actor, payload=payload, context=context)
        return TransactionContext(actor, request_id, digest)

    def _create_document(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.content_port is None:
            return self._unsupported("work.pending.document.create", request_id=request_id, code="canonical_content_port_unavailable", message="accepted ContentCommandHandler command port was not injected")
        from herzchen.content import CONTENT_SCHEMA_REVISION, ContentDocument, ContentRevision
        from herzchen.contracts import ResourceRef

        actor_value = self._actor(actor)
        project_ref = self._record_ref(payload["project_ref"])
        doc_id = payload.get("document_id") or "document-" + sha256(request_id.encode()).hexdigest()[:28]
        document_ref = ResourceRef(self.binding.authority, "dat.content.document", doc_id)
        source_ref = self._record_ref(payload["source_ref"]) if payload.get("source_ref") is not None else None
        import_mode = payload.get("import_mode", "owned")
        writable = bool(payload.get("writable", True))
        document = ContentDocument(
            document_ref,
            payload.get("role", "supporting"),
            payload.get("visibility", "private"),
            payload.get("access_mode", "read"),
            actor,
            authoring_scope=project_ref,
            source_ref=source_ref,
            import_mode=import_mode,
            writable=writable,
        )
        revision = ContentRevision(document_ref, "rev-1", payload.get("content", {}), actor_value, initial=True)
        command_payload = {"document": document, "revision": revision}
        context = self._content_context("dat.content.document.create", document_ref, request_id, actor_value, command_payload, CONTENT_SCHEMA_REVISION)
        envelope = self.content_port.build_create_document(context, document, revision)
        receipt_before = self._receipt(request_id)
        try:
            receipt_result = self.content_port.execute(envelope)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.create"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) or receipt_result
        return {"outcome": "replayed" if receipt_before is not None else "created", "document_ref": _json_value(document_ref), "project_ref": _json_value(project_ref), "record": _record_dict(self.reader.get_record(document_ref)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}

    def _link_document(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        if self.content_port is None:
            return self._unsupported("work.pending.document.link", request_id=request_id, code="canonical_content_port_unavailable", message="accepted ContentCommandHandler command port was not injected")
        from herzchen.content import CONTENT_SCHEMA_REVISION, DocumentAssociation
        from herzchen.contracts import ReferenceBinding, ResourceRef

        actor_value = self._actor(actor)
        project_ref = self._record_ref(payload["project_ref"])
        document_ref = self._record_ref(payload["document_ref"])
        association = DocumentAssociation(project_ref, payload.get("namespace", "project.documents"), payload.get("key", "document"), ReferenceBinding(document_ref, "current"), payload.get("access_mode", "read"))
        target = ResourceRef(self.binding.authority, "document-association", association.identity)
        command_payload = {"association": association}
        context = self._content_context("dat.content.link", target, request_id, actor_value, command_payload, CONTENT_SCHEMA_REVISION)
        envelope = self.content_port.build_link(context, association)
        receipt_before = self._receipt(request_id)
        try:
            receipt_result = self.content_port.execute(envelope)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.document.link"}, "replayed": False, "event_ids": []}
            raise
        receipt = self._receipt(request_id) or receipt_result
        return {"outcome": "replayed" if receipt_before is not None else "linked", "project_ref": _json_value(project_ref), "document_ref": _json_value(document_ref), "association_ref": _json_value(target), "record": _record_dict(self.reader.get_record(target)), "receipt": _receipt_dict(receipt), "replayed": receipt_before is not None, "event_ids": self._events_for(receipt)}

    def _unsupported(self, operation: str, *, request_id: Optional[str] = None, code: str = "canonical_operation_unavailable", message: str = "no accepted finite Herzchen endpoint is available for this Otto operation") -> dict[str, Any]:
        receipt = self.reader.get_receipt(request_id) if request_id else None
        return {
            "outcome": "unavailable",
            "operation": operation,
            "error": {"code": code, "message": message},
            "receipt": _receipt_dict(receipt),
            "replayed": False,
            "event_ids": self._events_for(receipt),
        }

    def _revise(self, payload: Mapping[str, Any], *, request_id: str, actor: str) -> Mapping[str, Any]:
        from herzchen.contracts import ResourceRef

        edit = payload["edit"]
        fields = {key: value for key, value in edit.items() if key not in {"title", "outcome"}}
        actor_value = self._actor(actor)
        changes: dict[str, Any] = {
            "logical_request_key": request_id,
            "actor": actor_value,
            "fields": fields,
        }
        if "title" in edit:
            changes["title"] = edit["title"]
        if "outcome" in edit:
            changes["outcome"] = edit["outcome"]
        before = self.reader.get_receipt(request_id)
        try:
            record = self.port.revise(ResourceRef.from_dict(payload["project_ref"]), **changes)
        except Exception as exc:
            if type(exc).__name__ == "ReplayConflictError":
                return {"outcome": "error", "error": {"code": "replay_conflict", "message": str(exc), "operation": "work.pending.edit"}, "replayed": False, "event_ids": []}
            raise
        receipt = self.reader.get_receipt(request_id)
        observed = self.reader.get_record(record.ref)
        return {
            "outcome": "replayed" if before is not None else "edited",
            "project_ref": _json_value(record.ref),
            "record": _record_dict(observed),
            "receipt": _receipt_dict(receipt),
            "replayed": before is not None,
            "event_ids": self._events_for(receipt),
            "executable": False,
        }

    def read(self, operation: str, payload: Mapping[str, Any], *, actor: str) -> Mapping[str, Any]:
        if operation != "work.pending.read":
            return {
                "outcome": "unavailable",
                "operation": operation,
                "error": {"code": "canonical_operation_unavailable", "message": "this binding currently exposes pending create and read only"},
            }
        from herzchen.contracts import ResourceRef

        record = self.reader.get_record(ResourceRef.from_dict(payload["project_ref"]))
        return {
            "outcome": "read",
            "project_ref": _json_value(getattr(record, "ref", None)),
            "record": _record_dict(record),
            "receipt": None,
            "replayed": False,
            "event_ids": [],
            "executable": False,
        }


__all__ = ["FiniteWorkOperations", "HerzchenBindingConfig"]

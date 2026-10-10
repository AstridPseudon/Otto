"""Shared bounded DAT metadata navigation; purpose is independent of storage."""
from __future__ import annotations

import time
from typing import Any, Mapping
from herzchen.contracts import AuthenticatedActor, ResourceRef
from .model import revision_identity

MAX_METADATA_BYTES = 65536
MAX_PAGE = 100


def metadata_identity(reference: ResourceRef) -> ResourceRef:
    """Derived DAT projection in the existing FND identity composition.

    This is no new document identity or authority: the original immutable pin
    and digest are always carried and checked by its reader.
    """
    base = ResourceRef(reference.authority, reference.kind, reference.id)
    source = revision_identity(base, reference.revision)
    return ResourceRef(source.authority, source.kind, source.id + "-metadata", source.revision)


def revision_metadata(revision: Any) -> Mapping[str, Any]:
    from herzchen.contracts import canonical_json
    content = revision.content
    result = {"record_type": "dat.content.metadata", "reference": revision.ref,
              "content_digest": revision.content_digest, "parent_revision": revision.parent_revision}
    if isinstance(content, Mapping) and content.get("representation_version") == "managed-bytes.v1":
        from herzchen.evidence.model import validate_manifest
        validate_manifest(content)
        if len(canonical_json(content).encode()) > 32768:
            raise ValueError("managed metadata exceeds its admission bound")
        result.update(representation="managed", manifest=dict(content))
    else:
        result.update(representation="inline", format="application/json",
                      byte_length=len(canonical_json(content).encode()))
    return result


def local_ref(reader: Any, value: Any) -> ResourceRef:
    ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
    if ref.authority != reader.authority or ref.kind != "dat.content.document":
        raise PermissionError("document unavailable")
    return ref


def authorize(document: Mapping[str, Any], actor: Any, roles=(), scopes=()) -> None:
    # The same current policy used by ContextPacketService, before revision I/O.
    from .packets import AccessDeniedError, VisibilityContext, authorize_document
    if (isinstance(actor, AuthenticatedActor) and document.get("visibility") != "public"
            and actor.authority != document.get("ref", {}).get("authority", actor.authority)):
        raise PermissionError("document unavailable")
    name = actor.actor if isinstance(actor, AuthenticatedActor) else actor
    try:
        authorize_document(document, VisibilityContext(name, tuple(roles), tuple(scopes)))
    except AccessDeniedError:
        raise PermissionError("document unavailable") from None


def document_metadata(reader: Any, reference: Any, *, actor: Any, roles=(), scopes=(),
                      authorize_read=None, include_inline: bool = False) -> Mapping[str, Any]:
    started = time.perf_counter()
    ref = local_ref(reader, reference)
    head = reader.get_identity_bounded(ResourceRef(ref.authority, ref.kind, ref.id))
    record = head["record"]
    if record is None:
        raise PermissionError("document unavailable")
    document = record.payload.get("document", {})
    if authorize_read is None:
        authorize(document, actor, roles, scopes)
    else:
        authorize_read(document, actor, ref)
    current = record.payload.get("current_revision")
    current = ResourceRef.from_dict(current) if isinstance(current, Mapping) else record.ref
    exact = current if ref.revision is None else ref
    if exact.revision is None:
        raise PermissionError("document unavailable")
    metadata = reader.get_identity_bounded(metadata_identity(exact))
    # Old inline bodies have no projection. Generic routine reads leave them
    # uninspected; the compatibility resolver can explicitly read bounded old
    # records, and large historical detail remains an explicit linear read.
    if metadata["record"] is None and not include_inline:
        source = revision_identity(ResourceRef(ref.authority, ref.kind, ref.id), exact.revision)
        if reader.get_identity_ref(source) is None:
            raise PermissionError("document unavailable")
        work = {"metadata_bytes_parsed": head["bytes_parsed"], "payload_bytes_read": 0,
                "payload_bytes_parsed": 0, "payload_bytes_hashed": 0,
                "processing_seconds": time.perf_counter() - started}
        return {"reference": exact, "current_head": current, "document": document,
                "availability": "historical-detail-required", "verification": "not-inspected",
                "representation": "unknown", "io_work": work}
    revision = metadata if metadata["record"] is not None else reader.get_identity_bounded(
        revision_identity(ResourceRef(ref.authority, ref.kind, ref.id), exact.revision))
    work = {"metadata_bytes_parsed": head["bytes_parsed"] + revision["bytes_parsed"],
            "payload_bytes_read": 0, "payload_bytes_parsed": 0, "payload_bytes_hashed": 0}
    result = {"reference": exact, "current_head": current, "document": document,
              "availability": "legacy-inline", "verification": "inline-details-required",
              "representation": "inline", "io_work": work}
    if revision["state"] == "missing":
        raise PermissionError("document unavailable")
    if revision["record"] is None:
        result.update(representation="unknown", availability="detail-required", verification="not-inspected")
    else:
        payload = revision["record"].payload
        projected = payload.get("record_type") == "dat.content.metadata"
        if projected and payload.get("reference") != exact.to_dict():
            raise ValueError("metadata pin mismatch")
        content = payload.get("manifest", {}) if projected else payload.get("content", {})
        result["content_digest"] = payload.get("content_digest")
        result["parent_revision"] = payload.get("parent_revision")
        if isinstance(content, Mapping) and content.get("representation_version") == "managed-bytes.v1":
            # No generic JSON digest is promoted to a full byte verification.
            from herzchen.evidence.model import validate_manifest
            from herzchen.contracts import canonical_json
            import hashlib
            validate_manifest(content)
            encoded = canonical_json(content).encode()
            actual = hashlib.sha256(encoded).hexdigest()
            if payload.get("content_digest") != actual:
                raise ValueError("manifest digest mismatch")
            work["metadata_bytes_hashed"] = len(encoded)
            result.update(representation="managed", manifest=dict(content),
                          format=content["format"], byte_length=content["byte_length"],
                          availability=content["availability"], verification="manifest-verified")
        elif projected:
            result.update(format=payload.get("format"), byte_length=payload.get("byte_length"),
                          verification="canonical-admitted-not-rehashed")
        elif include_inline:
            result.update(content=content, verification="legacy-inline")
            work["payload_bytes_parsed"] = revision["bytes_parsed"]
            work["legacy_inline_read"] = True
    work["processing_seconds"] = time.perf_counter() - started
    return result


def list_project_metadata(reader: Any, project_ref: Any, *, actor: Any, exact_role: str,
                          representation=None, format=None, cursor: str = "", limit: int = 50,
                          roles=(), task_refs=(), metadata_reader=None) -> Mapping[str, Any]:
    """One finite association window, with continuation even if every row is hidden.

    LIMIT bounds the primary-key seek before project/role/format predicates or
    hydration. Counts describe this window, never a full-collection inventory.
    Current heads and each association's immutable pin remain distinct.
    """
    started = time.perf_counter()
    project = project_ref if isinstance(project_ref, ResourceRef) else ResourceRef.from_dict(project_ref)
    if (project.authority != reader.authority or project.kind != "work.project"
            or not isinstance(exact_role, str) or not 1 <= len(exact_role) <= 256
            or representation not in {None, "managed", "inline"} or len(task_refs) > MAX_PAGE
            or (format is not None and (not isinstance(format, str) or not 1 <= len(format) <= 256))):
        raise PermissionError("project metadata unavailable")
    scopes = [project]
    for value in task_refs:
        ref = value if isinstance(value, ResourceRef) else ResourceRef.from_dict(value)
        if ref.authority != project.authority or ref.kind != "work.task":
            raise PermissionError("project metadata unavailable")
        item = reader.get_identity_bounded(ResourceRef(ref.authority, ref.kind, ref.id))["record"]
        parent = {} if item is None else item.payload.get("project_ref", item.payload.get("parent", {}))
        if any(parent.get(k) != project.to_dict()[k] for k in ("authority", "kind", "id")):
            raise PermissionError("project metadata unavailable")
        scopes.append(ref)
    page = reader.read_identity_page(kind="document-association", after=cursor, limit=limit)
    documents = []
    metadata_bytes = page["bytes_parsed"]
    metadata_hashed = 0
    identities = {(ref.authority, ref.kind, ref.id) for ref in scopes}
    for record in page["records"]:
        data = record.payload
        association = data.get("association", data)
        subject = association.get("subject", {})
        if data.get("active") is False or tuple(subject.get(k) for k in ("authority", "kind", "id")) not in identities:
            continue
        try:
            binding = association["document"]
            ref = local_ref(reader, binding["ref"])
            if binding["mode"] not in {"current", "pinned"} or (binding["mode"] == "pinned") != (ref.revision is not None):
                continue
            # Read the small current descriptor first; rejected role rows do
            # not open the historical revision or any managed payload.
            head = reader.get_identity_bounded(ResourceRef(ref.authority, ref.kind, ref.id))
            metadata_bytes += head["bytes_parsed"]
            if head["record"] is None or head["record"].payload.get("document", {}).get("role") != exact_role:
                continue
            selected = (metadata_reader(ref, scopes) if metadata_reader else
                        document_metadata(reader, ref, actor=actor, roles=roles, scopes=scopes))
            metadata_bytes += selected["io_work"]["metadata_bytes_parsed"]
            metadata_hashed += selected["io_work"].get("metadata_bytes_hashed", 0)
            if representation is not None and selected["representation"] != representation:
                continue
            if format is not None and selected.get("format") != format:
                continue
            documents.append({"document_ref": ResourceRef(ref.authority, ref.kind, ref.id),
                "current_head": selected["current_head"], "associated_pin": selected["reference"] if binding["mode"] == "pinned" else None,
                "resolved_reference": selected["reference"], "association_ref": record.ref,
                "binding_mode": binding["mode"], "role": exact_role,
                "representation": selected["representation"], "format": selected.get("format"),
                "byte_length": selected.get("byte_length"), "availability": selected["availability"],
                "verification": selected["verification"]})
        except (PermissionError, ValueError, KeyError, TypeError):
            # Missing, denied and foreign targets have identical projections.
            continue
    return {"outcome": "listed", "documents": documents, "count": len(documents),
            "next_cursor": page["next_cursor"], "read_only": True,
            "io_work": {"associations_examined": page["examined"], "metadata_bytes_read": metadata_bytes,
                        "metadata_bytes_parsed": metadata_bytes, "metadata_bytes_hashed": metadata_hashed,
                        "payload_bytes_read": 0, "payload_bytes_parsed": 0, "payload_bytes_hashed": 0,
                        "processing_seconds": time.perf_counter() - started}}

"""Read shared project documents through their canonical DAT associations."""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from herzchen.content import DocumentAssociation
from herzchen.content import ContentDocument, ContentRevision
from herzchen.contracts import ReferenceBinding, ResourceRef, TransactionContext, canonical_json

NAMESPACE = "portfolio.shared"


def _base(ref):
    ref = ResourceRef.from_dict(ref) if isinstance(ref, Mapping) else ref
    return ResourceRef(ref.authority, ref.kind, ref.id)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("portfolio document path must be a relative UTF-8 path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {".", "..", ""} or p.startswith(".") for p in value.split("/")) or len(path.parts) > 5:
        raise ValueError("portfolio document path must be relative and nested at most four levels")
    return value


def document_namespace(*, root=None, root_namespace=None):
    """Validate an optional namespace selector used by stored associations."""
    if root_namespace is not None:
        if not isinstance(root_namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", root_namespace):
            raise ValueError("root namespace must be a single safe component of at most 64 characters")
        return root_namespace
    if root is None:
        return None
    from pathlib import Path
    if not isinstance(root, (str, Path)) or not str(root) or not Path(root).is_absolute():
        raise ValueError("portfolio document root must be an absolute path")
    return "root-" + _digest(str(Path(root).resolve()))[:32]


def _context(actor, action, ref, value, head=None):
    version = head.get("version", 0) if head else 0
    digest = _digest(canonical_json([action, ref.to_dict(), value, version]))
    return TransactionContext(actor, "portfolio-docs:" + digest, digest,
        expected_version=version, expected_revision=(head or {}).get("current_revision", {}).get("revision"))


def _document_ref(portfolio, path, *, root_namespace=None):
    namespace = document_namespace(root_namespace=root_namespace)
    identity = [portfolio.to_dict(), path] if namespace is None else [portfolio.to_dict(), namespace, path]
    return ResourceRef(portfolio.authority, "dat.content.document", "portfolio-" + _digest(canonical_json(identity))[:32])


def _write(owner, actor, portfolio, ref, body):
    """Write a fixture or owner-authored DAT document; no manifest is maintained."""
    head = owner.content.read(ref)
    if head and (head.get("revision") or {}).get("content") == body:
        return None
    document = ContentDocument(ref, "portfolio-document", "shared", "read", actor.actor,
        authoring_scope=portfolio, writable=False)
    context = _context(actor, "write", ref, body, head)
    revision = ContentRevision(ref, "rev-" + str(head.get("version", 0) + 1), body, actor,
        parent_revision=(head.get("current_revision") or {}).get("revision"), initial=not bool(head))
    builder = owner.content.build_append_revision if head else owner.content.build_create_document
    return owner.content.execute(builder(context, document, revision)).to_dict()


def _association(project, path, document, *, root_namespace=None):
    key = path if root_namespace is None else ".roots/" + root_namespace + "/" + path
    return DocumentAssociation(_base(project), NAMESPACE, key, ReferenceBinding(document, "current"), "read")


def _link(owner, actor, association, *, remove=False):
    ref = ResourceRef(association.subject.authority, "document-association", association.identity)
    head = owner.content.read(ref)
    active = bool(head and head.get("payload", {}).get("active") is not False)
    if active == (not remove):
        return None
    context = _context(actor, "unlink" if remove else "link", ref, association, head)
    builder = owner.content.build_unlink if remove else owner.content.build_link
    return owner.content.execute(builder(context, association)).to_dict()


def _project_portfolio(owner, project):
    record = owner.graph.current(_base(project))
    value = (record.payload.get("metadata") or {}).get("otto_orchestrator") or {}
    return _base(value["portfolio_ref"]) if value.get("portfolio_ref") else None


def _association_rows(owner, project):
    refs = owner.store.consumer().find_identity_refs(kind="document-association", payload_matches={
        ("association", "subject", "authority"): project.authority,
        ("association", "subject", "kind"): project.kind,
        ("association", "subject", "id"): project.id,
        ("association", "namespace"): NAMESPACE})
    rows = []
    for ref in refs:
        head = owner.content.read(_base(ref))
        payload = head.get("payload") or {} if head else {}
        if payload.get("active") is False or not payload.get("association"):
            continue
        association = DocumentAssociation.from_dict(payload["association"])
        rows.append((association, head))
    return rows


def _read(owner, portfolio, *, operation="list", path=None, project=None, root_namespace=None,
          revision=None):
    if operation not in {"list", "read"} or operation == "read" and not path:
        raise ValueError("portfolio documents requires list or read with a path")
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", revision)):
        raise ValueError("document revision must be a safe revision identifier")
    namespace = document_namespace(root_namespace=root_namespace)
    if path is not None:
        if not isinstance(path, str):
            raise ValueError("portfolio document path must be a relative UTF-8 path")
        if path.startswith(".roots/") and namespace is None:
            pieces = path.split("/", 2)
            if len(pieces) != 3:
                raise ValueError("portfolio document path must include a root and file")
            namespace = document_namespace(root_namespace=pieces[1])
            path = ".roots/" + namespace + "/" + _path(pieces[2])
        else:
            _path(path)
    projects = [owner.graph.current(project)] if project is not None else [
        record for record in owner.graph.list(kind="project")
        if _project_portfolio(owner, record.ref) == portfolio]
    rows, seen = [], set()
    for record in projects:
        for association, _ in _association_rows(owner, _base(record.ref)):
            key = association.key
            if key in seen or namespace is not None and not key.startswith(".roots/" + namespace + "/"):
                continue
            visible_path = key
            if key.startswith(".roots/"):
                parts = key.split("/", 2)
                if len(parts) != 3:
                    continue
                visible_path = key if project is None and root_namespace is None else parts[2]
            if operation == "read" and visible_path != path and key != path:
                continue
            seen.add(key)
            ref = ResourceRef.from_dict(association.document.ref.to_dict())
            selected_ref = ResourceRef(ref.authority, ref.kind, ref.id, revision) if revision else ref
            head = owner.content.read(selected_ref)
            if not head:
                continue
            body = head.get("content") if revision else (head.get("revision") or {}).get("content")
            if not isinstance(body, str):
                continue
            rows.append({"path": visible_path, **({"root_namespace": key.split("/", 2)[1]} if key.startswith(".roots/") else {}),
                         "role": "portfolio-document", "document_ref": ref.to_dict(),
                         "revision_ref": selected_ref.to_dict() if revision else head["current_revision"],
                         "bytes": len(body.encode("utf-8")), **({"content": body} if operation == "read" else {})})
    common = {"read_only": True, "provider_called": False, "dispatch": False}
    if operation == "list":
        return {**common, "outcome": "listed", "portfolio_ref": portfolio.to_dict(), "documents": rows}
    return {**common, "outcome": "read", **rows[0]} if rows else {**common, "outcome": "unavailable", "path": path}


def _authorized(session, portfolio):
    portfolio = _base(portfolio)
    if portfolio.kind != "wrk.portfolio" or portfolio.authority != session.actor.authority:
        raise PermissionError("portfolio is outside the owner authority")
    if session.host is None:
        return portfolio, session.actor
    if _base(session.host["portfolio_ref"]) != portfolio:
        raise PermissionError("portfolio is outside the caller's supervision")
    assignment = session.root_assignment()
    if (assignment.principal != session.host["principal"] or assignment.role != "orchestrator"
            or _base(assignment.scope) != portfolio
            or assignment.generation != session.host.get("root_generation")
            or getattr(assignment.status, "value", assignment.status) in {"reassigned", "completed", "cancelled"}):
        raise PermissionError("portfolio documents require the current orchestrator or owner")
    return portfolio, session.binding.authenticated_actor(session.host["principal"])


def portfolio_documents(session, portfolio_ref, *, operation="list", path=None, root_namespace=None,
                        revision=None):
    portfolio, _ = _authorized(session, portfolio_ref)
    return _read(session.owner, portfolio, operation=operation, path=path, root_namespace=root_namespace,
                 revision=revision)


def project_shared_documents(owner, project_ref, *, operation="list", path=None):
    """Trusted owner read for its authenticated bound project reader."""
    project = _base(project_ref)
    portfolio = _project_portfolio(owner, project)
    if portfolio is None:
        return {"outcome": "listed" if operation == "list" else "unavailable", "documents": [], "read_only": True}
    return _read(owner, portfolio, operation=operation, path=path, project=project)


def retire_portfolio_document(session, portfolio_ref, path, *, root_namespace=None):
    """Remove a shared-document association while retaining its DAT document."""
    portfolio, actor = _authorized(session, portfolio_ref)
    path = _path(path)
    namespace = document_namespace(root_namespace=root_namespace)
    owner = session.owner
    receipts = []
    with session.store.transaction():
        for record in owner.graph.list(kind="project"):
            if _project_portfolio(owner, record.ref) != portfolio:
                continue
            for association, _ in _association_rows(owner, _base(record.ref)):
                key = association.key
                visible = key.split("/", 2)[2] if key.startswith(".roots/") else key
                if visible != path or namespace is not None and not key.startswith(".roots/" + namespace + "/"):
                    continue
                receipt = _link(owner, actor, association, remove=True)
                if receipt:
                    receipts.append(receipt)
    return {"portfolio_ref": portfolio.to_dict(), "path": path, "outcome": "retired" if receipts else "unavailable",
            "receipts": receipts, "provider_called": False, "dispatch": False}


def remove_project_associations(owner, project_ref, portfolio_ref, *, actor):
    """Owner detach hook; unlink every associated shared document in the transaction."""
    project = _base(project_ref)
    portfolio = _base(portfolio_ref)
    if project.authority != portfolio.authority:
        raise PermissionError("project is outside the portfolio authority")
    receipts = []
    for association, _ in _association_rows(owner, project):
        receipt = _link(owner, actor, association, remove=True)
        if receipt:
            receipts.append(receipt)
    return receipts

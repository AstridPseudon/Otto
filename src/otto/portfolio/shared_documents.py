"""Portfolio text documents using DAT revisions and read-only project associations.

The private DAT manifest holds only sync digests and paths. It is committed in
one owner transaction with document revisions and associations; no store schema
or secondary index is introduced. Client processes read directories, while the
single owner service validates and commits the supplied bytes.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from herzchen.content import ContentDocument, ContentRevision, DocumentAssociation
from herzchen.contracts import ReferenceBinding, ResourceRef, TransactionContext, canonical_json

NAMESPACE = "portfolio.shared"
MAX_FILES = 1000
MAX_FILE_BYTES = 10 << 20
MAX_TOTAL_BYTES = 256 << 20


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


def _files(bundle):
    files = bundle.get("files")
    if not isinstance(files, Mapping) or len(files) > MAX_FILES:
        raise ValueError("portfolio sync requires at most 1000 UTF-8 files")
    total = 0
    for path, value in files.items():
        _path(path)
        if not isinstance(value, str):
            raise ValueError("portfolio documents must contain UTF-8 text")
        size = len(value.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise ValueError("portfolio document exceeds 10 MiB")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ValueError("portfolio sync exceeds 256 MiB")
    return dict(files)


def read_document_directory(directory, *, exclude_prefixes=()):
    """Client-side, read-only directory ingestion with project sync's depth rule."""
    from otto.hostctl.bundle import _bundle_names
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError("not a directory: " + str(root))
    files = {}
    names = [name for name in _bundle_names(root)
             if not any(name.startswith(prefix) for prefix in exclude_prefixes)]
    if len(names) > MAX_FILES:
        raise ValueError("portfolio sync requires at most 1000 UTF-8 files")
    total = 0
    for name in names:
        with os.fdopen(os.open(root / name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("portfolio sync exceeds its file or operation byte limit")
        files[name] = raw.decode("utf-8")
    bundle = {"root": str(root), "files": files}
    _files(bundle)
    return bundle


def document_namespace(*, root=None, root_namespace=None):
    """Stable root selector; omitted selectors retain the original generic scope."""
    if root_namespace is not None:
        if not isinstance(root_namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", root_namespace):
            raise ValueError("root namespace must be a single safe component of at most 64 characters")
        return root_namespace
    if root is None:
        return None
    if not isinstance(root, (str, Path)) or not str(root) or not Path(root).is_absolute():
        raise ValueError("portfolio document root must be an absolute path")
    return "root-" + _digest(str(Path(root).resolve()))[:32]


def _document_ref(portfolio, path, *, root_namespace=None):
    namespace = document_namespace(root_namespace=root_namespace)
    identity = [portfolio.to_dict(), path] if namespace is None else [portfolio.to_dict(), namespace, path]
    return ResourceRef(portfolio.authority, "dat.content.document", "portfolio-" + _digest(canonical_json(identity))[:32])


def _manifest_ref(portfolio, *, root_namespace=None):
    return _document_ref(portfolio, ".sync-manifest", root_namespace=root_namespace)


def _manifest(owner, portfolio, *, root_namespace=None):
    head = owner.content.read(_manifest_ref(portfolio, root_namespace=root_namespace))
    return dict((head.get("revision") or {}).get("content") or {"files": {}})


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


def _context(actor, action, ref, value, head=None):
    version = head.get("version", 0) if head else 0
    digest = _digest(canonical_json([action, ref.to_dict(), value, version]))
    return TransactionContext(actor, "portfolio-docs:" + digest, digest,
        expected_version=version, expected_revision=(head or {}).get("current_revision", {}).get("revision"))


def _write(owner, actor, portfolio, ref, body, *, manifest=False):
    head = owner.content.read(ref)
    if head and (head.get("revision") or {}).get("content") == body:
        return None
    # Shared DAT documents retain their own canonical EDT scope (authoring.py
    # resolve_scope); authoring_scope here bounds read visibility to the portfolio.
    # Reader sessions cannot acquire write capability for shared documents.
    # Writes enter this orchestrator/owner-checked command on the owner lane.
    document = ContentDocument(ref, "portfolio-manifest" if manifest else "portfolio-document",
        "private" if manifest else "shared", "read", actor.actor,
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
    record = owner.graph.get(_base(project))
    value = (record.payload.get("metadata") or {}).get("otto_orchestrator") or {}
    return _base(value["portfolio_ref"]) if value.get("portfolio_ref") else None


def sync_portfolio_documents(session, portfolio_ref, bundle, *, apply=True):
    """Three-way sync plus explicit enrollment of newly attached projects."""
    portfolio, actor = _authorized(session, portfolio_ref)
    files = _files(bundle)
    namespace = document_namespace(root_namespace=bundle.get("root_namespace"))
    owner = session.owner
    manifest = _manifest(owner, portfolio, root_namespace=namespace)
    synced = dict(manifest.get("files") or {})
    retired = set(manifest.get("retired") or ())
    projects = [record for record in owner.graph.list(kind="project")
                if ((record.payload.get("metadata") or {}).get("otto_orchestrator") or {}).get("portfolio_ref")
                and _base(record.payload["metadata"]["otto_orchestrator"]["portfolio_ref"]) == portfolio]
    rows, recorded, receipts, attached = [], [], [], []
    if not apply:
        for path in sorted(set(files) | set(synced) | retired):
            ref = _document_ref(portfolio, path, root_namespace=namespace)
            head = owner.content.read(ref)
            text = (head.get("revision") or {}).get("content")
            now = _digest(files[path]) if path in files else None
            then = _digest(text) if isinstance(text, str) else None
            base = synced.get(path)
            if path in retired:
                state = "retired"
            elif now == then:
                state = "unchanged"
            elif then is None:
                state = "added"
            elif now is None:
                state = "removed_from_run_dir"
            elif then == base:
                state = "changed"
            elif now == base:
                state = "otto_newer"
            else:
                state = "conflict"
            rows.append({"path": path, "state": state, "stored_sha256": then,
                         "run_dir_sha256": now, "last_synced_sha256": base})
            if state in {"added", "changed"}:
                recorded.append(path)
            if state != "retired" and (head or state == "added"):
                for project in projects:
                    association = _association(project.ref, path, ref, root_namespace=namespace)
                    link = owner.content.read(ResourceRef(project.ref.authority, "document-association", association.identity))
                    if not link or link.get("payload", {}).get("active") is False:
                        attached.append({"project_ref": _base(project.ref).to_dict(), "path": path})
        return {"outcome": "plan", "portfolio_ref": portfolio.to_dict(),
                **({"root_namespace": namespace} if namespace is not None else {}), "documents": rows,
                "recorded": recorded, "attached": attached, "receipts": [],
                "not_overwritten": [row["path"] for row in rows if row["state"] in {"conflict", "otto_newer"}],
                "writes": False, "provider_called": False, "dispatch": False}
    with session.store.transaction():
        for path in sorted(set(files) | set(synced) | retired):
            ref = _document_ref(portfolio, path, root_namespace=namespace)
            head = owner.content.read(ref)
            text = (head.get("revision") or {}).get("content")
            now = _digest(files[path]) if path in files else None
            then = _digest(text) if isinstance(text, str) else None
            base = synced.get(path)
            if path in retired:
                state = "retired"
            elif now == then:
                state = "unchanged"
            elif then is None:
                state = "added"
            elif now is None:
                state = "removed_from_run_dir"
            elif then == base:
                state = "changed"
            elif now == base:
                state = "otto_newer"
            else:
                state = "conflict"
            rows.append({"path": path, "state": state, "stored_sha256": then,
                         "run_dir_sha256": now, "last_synced_sha256": base})
            if state in {"added", "changed"}:
                receipt = _write(owner, actor, portfolio, ref, files[path])
                if receipt:
                    receipts.append(receipt)
                recorded.append(path)
                synced[path] = now
            elif state == "unchanged" and now is not None:
                synced[path] = now
            if state != "retired" and (head or state == "added"):
                for project in projects:
                    receipt = _link(owner, actor, _association(project.ref, path, ref, root_namespace=namespace))
                    if receipt:
                        receipts.append(receipt)
                        attached.append({"project_ref": _base(project.ref).to_dict(), "path": path})
        body = {**manifest, "files": synced}
        if retired:
            body["retired"] = sorted(retired)
        receipt = _write(owner, actor, portfolio, _manifest_ref(portfolio, root_namespace=namespace), body, manifest=True)
        if receipt:
            receipts.append(receipt)
        if namespace is not None:
            catalog = _manifest(owner, portfolio)
            roots = dict(catalog.get("roots") or {})
            roots.setdefault(namespace, {"root": bundle.get("root")})
            receipt = _write(owner, actor, portfolio, _manifest_ref(portfolio),
                             {**catalog, "roots": roots}, manifest=True)
            if receipt:
                receipts.append(receipt)
    return {"outcome": "synced" if recorded or attached else "in_sync", "portfolio_ref": portfolio.to_dict(),
            **({"root_namespace": namespace} if namespace is not None else {}),
            "documents": rows, "recorded": recorded, "attached": attached, "receipts": receipts,
            "not_overwritten": [row["path"] for row in rows if row["state"] in {"conflict", "otto_newer"}],
            "provider_called": False, "dispatch": False}


def retire_portfolio_document(session, portfolio_ref, path, *, root_namespace=None):
    """Unlink a managed path and retain DAT revisions plus a durable sync tombstone."""
    portfolio, actor = _authorized(session, portfolio_ref)
    path = _path(path)
    namespace = document_namespace(root_namespace=root_namespace)
    owner = session.owner
    manifest = _manifest(owner, portfolio, root_namespace=namespace)
    files = dict(manifest.get("files") or {})
    retired = set(manifest.get("retired") or ())
    common = {"portfolio_ref": portfolio.to_dict(), "path": path, "root_namespace": namespace,
              "provider_called": False, "dispatch": False}
    if path in retired:
        return {**common, "outcome": "already_retired", "receipts": []}
    if path not in files:
        return {**common, "outcome": "unavailable", "receipts": []}
    ref = _document_ref(portfolio, path, root_namespace=namespace)
    receipts = []
    with session.store.transaction():
        for project in owner.graph.list(kind="project"):
            association = _association(project.ref, path, ref, root_namespace=namespace)
            linked = owner.content.read(ResourceRef(project.ref.authority, "document-association", association.identity))
            target = ((linked.get("payload") or {}).get("association") or {}).get("document", {}).get("ref")
            # An identically named association in another portfolio may bind a
            # different document. Retire only this root's retained DAT identity.
            if target is None or _base(target) != ref:
                continue
            receipt = _link(owner, actor, association, remove=True)
            if receipt:
                receipts.append(receipt)
        files.pop(path)
        retired.add(path)
        receipt = _write(owner, actor, portfolio, _manifest_ref(portfolio, root_namespace=namespace),
                         {**manifest, "files": files, "retired": sorted(retired)}, manifest=True)
        if receipt:
            receipts.append(receipt)
    return {**common, "outcome": "retired", "document_ref": ref.to_dict(), "receipts": receipts}


def _read(owner, portfolio, *, operation="list", path=None, project=None, root_namespace=None,
          include_retired=False, revision=None):
    if operation not in {"list", "read"} or operation == "read" and not path:
        raise ValueError("portfolio documents requires list or read with a path")
    if (include_retired or revision is not None) and operation != "read":
        raise ValueError("retired documents and explicit revisions require a read with a path")
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", revision)):
        raise ValueError("document revision must be a safe revision identifier")
    namespace = document_namespace(root_namespace=root_namespace)
    catalog = _manifest(owner, portfolio)
    namespaces = [namespace] if namespace is not None else [None, *sorted(catalog.get("roots") or {})]
    rows = []
    if path is not None:
        # Qualified keys come from the owner's catalog and project associations.
        if not isinstance(path, str):
            raise ValueError("portfolio document path must be a relative UTF-8 path")
        prefix, separator, rest = path.partition("/")
        selected, scoped_separator, local = rest.partition("/")
        if namespace is None and prefix == ".roots" and separator and scoped_separator and selected in (catalog.get("roots") or {}):
            _path(local)
        else:
            _path(path)
    for scope in namespaces:
        manifest = _manifest(owner, portfolio, root_namespace=scope)
        paths = set(manifest.get("files") or {})
        retired = set(manifest.get("retired") or ())
        if include_retired:
            paths |= retired
        for name in sorted(paths):
            key = name if scope is None or namespace is not None else ".roots/" + scope + "/" + name
            if operation == "read" and key != path:
                continue
            ref = _document_ref(portfolio, name, root_namespace=scope)
            if project is not None:
                association = _association(project, name, ref, root_namespace=scope)
                linked = owner.content.read(ResourceRef(portfolio.authority, "document-association", association.identity))
                if not linked or linked.get("payload", {}).get("active") is False:
                    continue
            selected_ref = ResourceRef(ref.authority, ref.kind, ref.id, revision) if revision else ref
            head = owner.content.read(selected_ref)
            if not head:
                continue
            body = head.get("content") if revision else (head.get("revision") or {}).get("content")
            revision_ref = selected_ref.to_dict() if revision else head["current_revision"]
            rows.append({"path": key, **({"root_namespace": scope} if scope is not None else {}),
                         "role": "portfolio-document", "document_ref": ref.to_dict(),
                         "revision_ref": revision_ref, "bytes": len(body.encode("utf-8")),
                         **({"retired": True} if name in retired else {}),
                         **({"content": body} if operation == "read" else {})})
    common = {"read_only": True, "provider_called": False, "dispatch": False}
    if operation == "list":
        return {**common, "outcome": "listed", "portfolio_ref": portfolio.to_dict(), "documents": rows}
    return {**common, "outcome": "read", **rows[0]} if rows else {**common, "outcome": "unavailable", "path": path}


def portfolio_documents(session, portfolio_ref, *, operation="list", path=None, root_namespace=None,
                        include_retired=False, revision=None):
    portfolio, _ = _authorized(session, portfolio_ref)
    return _read(session.owner, portfolio, operation=operation, path=path, root_namespace=root_namespace,
                 include_retired=include_retired, revision=revision)


def project_shared_documents(owner, project_ref, *, operation="list", path=None):
    """Trusted owner read for its authenticated bound project reader."""
    project = _base(project_ref)
    portfolio = _project_portfolio(owner, project)
    if portfolio is None:
        return {"outcome": "listed" if operation == "list" else "unavailable", "documents": [], "read_only": True}
    return _read(owner, portfolio, operation=operation, path=path, project=project)


def remove_project_associations(owner, project_ref, portfolio_ref, *, actor):
    """Owner detach hook; call in the same transaction as supervision removal."""
    project = _base(project_ref)
    portfolio = _base(portfolio_ref)
    if project.authority != portfolio.authority:
        raise PermissionError("project is outside the portfolio authority")
    # Revoke every namespace association, including links made through DAT
    # outside sync. The manifest is sync provenance, not an exhaustive ACL.
    refs = owner.store.consumer().find_identity_refs(kind="document-association", payload_matches={
        ("association", "subject", "authority"): project.authority,
        ("association", "subject", "kind"): project.kind,
        ("association", "subject", "id"): project.id,
        ("association", "namespace"): NAMESPACE})
    receipts = []
    for ref in refs:
        head = owner.content.read(_base(ref))
        payload = head.get("payload") or {}
        if payload.get("active") is False:
            continue
        receipt = _link(owner, actor, DocumentAssociation.from_dict(payload["association"]), remove=True)
        if receipt:
            receipts.append(receipt)
    return receipts

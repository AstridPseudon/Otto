"""``show`` and ``open`` on the manager entry: one project read, one authoring session.

``show project`` reads one project's row and its task rows through the owner's
``list_work`` read. Nothing in its output depends on the caller's lane (Claude
or Codex): the lane selects a model profile, never a read, so the output is the
same for both. It never writes.

``open`` drives Herzchen's authoring session through the owner's
``DocumentEditorHost``: start (``open``), ``autosave``, ``finish`` (the check-in,
which a stale base refuses with nothing changed) and ``release`` (the host's
``discard``, which closes the session without publishing). The checkout is the
one the editor host materializes; this module adds no checkout path. The
editor host checks its own owner actor and the exact handle, so the caller adds
no authority.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

SHOW_PROJECT_SCHEMA = "otto.show.project.v1"

# CLI step -> the editor host's finite operation name. ``release`` is the owner-side release of a
# session by its id (sessions.release through discard_session): it works on an open session and on
# one a refused finish parked for cleanup, and it publishes nothing.
OPEN_OPERATIONS = {"start": "open", "autosave": "save", "finish": "finish", "release": "discard-lost"}


def show_project(portfolio: Any, *, actor: str, project_ref: Mapping[str, Any], limit: int) -> dict[str, Any]:
    """One project's row and its task rows, from the owner's work read."""
    listed = portfolio.list_work(actor=actor, view="all", project_ref=dict(project_ref), limit=limit)
    if listed.get("outcome") not in {"listed", "partial"}:
        return listed
    rows = [row for row in listed.get("projects", ())
            if (row.get("project_ref") or {}).get("id") == project_ref.get("id")]
    if not rows:
        return {"outcome": "not_found", "schema": SHOW_PROJECT_SCHEMA, "read_only": True,
                "dispatch": False, "launch": False,
                "error": {"code": "project_not_found", "message": "no project with that ref is visible to this read"}}
    items = [row for row in listed.get("items", ())
             if (row.get("project_ref") or {}).get("id") == project_ref.get("id")]
    return {"outcome": "read", "schema": SHOW_PROJECT_SCHEMA, "project": rows[0], "tasks": items,
            "pagination": listed.get("pagination"), "read_only": True, "writes": 0,
            "dispatch": False, "launch": False}


def _stale_check_in(editor_host: Any, request: Mapping[str, Any], handle: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Refuse a check-in whose base the document has moved past, before the session is touched.

    The editor host's finish does not carry the base it read, so a stale check-in would only be
    caught after the session is claimed (it would then be parked for recovery). Comparing the
    handle's base with the document's current revision first keeps the session open and writes nothing.
    The late DAT append still guards the race between this read and the finish.
    """
    read = editor_host.operations.document_reader.read_document(
        request["project_ref"], request["document_ref"], actor=editor_host.actor)
    if read.get("outcome") != "read":
        return None  # the finish itself refuses an unreadable document
    current = (read.get("revision_ref") or {}).get("revision")
    if current == handle.get("base_revision"):
        return None
    return {"outcome": "conflict", "error": {"code": "stale_base",
            "message": "the document moved after this session opened; release the session and open it again"},
            "base_revision": handle.get("base_revision"), "current_revision": current,
            "dat_revision_advanced": False, "session_open": True, "publication": "not_published"}


def open_session(editor_host: Any, args: Any) -> dict[str, Any]:
    """One authoring-session step, through the owner's editor host (``open`` is the CLI verb)."""
    operation = OPEN_OPERATIONS[args.open_command]
    request: dict[str, Any] = {"command": "document-authoring", "operation": operation,
                               "request_key": args.request_key}
    if operation == "discard-lost":
        handle = json.loads(args.handle_json)
        if not isinstance(handle, dict) or not isinstance(handle.get("session_id"), str):
            raise ValueError("release needs the handle that open returned")
        request["session_id"] = handle["session_id"]
        return dict(editor_host.dispatch(request, actor=editor_host.actor))
    request.update(project_ref=json.loads(args.project_ref), document_ref=json.loads(args.document_ref))
    if operation == "open":
        if args.inactivity_seconds is not None:
            request["inactivity_seconds"] = args.inactivity_seconds
    else:
        request["handle"] = json.loads(args.handle_json)
    if operation == "save":
        request["editor_buffer"] = json.loads(args.buffer_json)
    if operation == "finish":
        refused = _stale_check_in(editor_host, request, request["handle"])
        if refused is not None:
            return refused
    return dict(editor_host.dispatch(request, actor=editor_host.actor))

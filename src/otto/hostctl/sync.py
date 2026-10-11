"""Mirror a pending project's run-dir files into Otto by digest.

Authority rule: until activation the run directory is authoritative and Otto
mirrors it; this module records changed files as new document revisions
through the supported checkout/check-in path (never a hand edit), reports
task drift, and refuses once the project is no longer pending (Otto is then
the authority and the files are generated views).
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping

from herzchen.contracts import ResourceRef, canonical_json

from .bundle import read_bundle


def _stored_documents(session: Any, record: Any) -> dict[str, dict[str, Any]]:
    from herzchen.content import domain_contribution as content_contribution
    from herzchen.content.packets import ContextPacketService
    from otto.portfolio.documents import ProjectDocumentReader
    reader = ProjectDocumentReader(sheet_reader=session.owner.sheet, content_reader=session.owner.content,
        visibility_reader=ContextPacketService(session.store.domain_handler((content_contribution(),))))
    result = {}
    actor = session.binding.authenticated_actor(session.host["principal"]) if session.host else session.owner.owner_actor
    for row in reader.list_documents(record.ref.to_dict(), actor=actor)["documents"]:
        path = next((m.get("key") for m in row.get("memberships") or () if m.get("namespace") == "project.files"), None)
        if path is None:
            continue
        text = session.owner.content.read(ResourceRef.from_dict(row["current_revision_ref"]))["content"]
        result[path] = {"revision_ref": row["current_revision_ref"],
                        "sha256": hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None}
    return result


def sync_documents(session: Any, record: Any, bundle_source: Any, *, apply: bool = True) -> dict[str, Any]:
    """bundle_source: a run directory, or a bundle the client already read (parse_files + root)."""
    registration = (record.payload.get("custom") or {}).get("otto_host_registration") or {}
    if record.lifecycle.value != "pending":
        return {"outcome": "refused", "reason": "project is " + record.lifecycle.value + "; after activation Otto is "
                "the authority and run-dir files are generated views", "provider_called": False}
    bundle = bundle_source if isinstance(bundle_source, Mapping) else read_bundle(bundle_source)
    files = bundle["raw_sha256"]
    registered = set(registration.get("raw_sha256") or {})
    # Only the run's own files are mirrored; Otto-authored documents such as
    # the onboarding brief.md are not run-dir files and are never compared.
    stored = {path: value for path, value in _stored_documents(session, record).items()
              if path in registered or path in files}
    drift, changes = [], []
    for path in sorted(set(stored) | set(files)):
        now, then = files.get(path), (stored.get(path) or {}).get("sha256")
        state = ("unchanged" if now == then else "added" if then is None
                 else "removed_from_run_dir" if now is None else "changed")
        drift.append({"path": path, "state": state, "stored_sha256": then, "run_dir_sha256": now})
        if state == "changed":
            changes.append({"operation": "edit", "path": path, "content": bundle["files"][path]})
        elif state == "added":
            changes.append({"operation": "add", "path": path, "content": bundle["files"][path]})
    stored_tasks = {}
    for raw in record.payload.get("tasks") or ():
        ref = ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
        task = session.owner.graph.get(ResourceRef(ref.authority, ref.kind, ref.id))
        stored_tasks[task.payload.get("alias") or task.ref.id] = task.payload.get("outcome")
    parsed = {task["id"]: task["outcome"] for task in bundle["tasks"]}
    task_drift = {"added": sorted(set(parsed) - set(stored_tasks)),
                  "removed": sorted(set(stored_tasks) - set(parsed)),
                  "outcome_changed": sorted(k for k in set(parsed) & set(stored_tasks) if parsed[k] != stored_tasks[k]),
                  "applied": False,
                  "note": "task drift is reported, not applied; re-plan through the sheet before activation"}
    result = {"outcome": "in_sync" if not changes else "drift", "documents": drift, "tasks": task_drift,
              "provider_called": False, "dispatch": False}
    if not changes or not apply:
        return result
    key = "sync:" + (registration.get("run_id") or record.ref.id) + ":" + hashlib.sha256(
        canonical_json(files).encode()).hexdigest()[:20]
    actor = session.host["principal"] if session.host else session.actor.actor
    opened = session.portfolio.checkout_project(record.ref.to_dict(), actor=actor, request_id=key + ":open")
    if opened.get("outcome") not in {"opened", "replayed"}:
        return {**result, "outcome": "held", "request_key": key,
                "reason": "checkout unavailable: " + str((opened.get("error") or {}).get("message") or opened.get("outcome")),
                "next_action": "release the open checkout of this project (project-authoring release) and repeat"}
    project_json = copy.deepcopy(opened["project_json"])
    custom = dict(project_json.get("custom") or {})
    mirror = dict(custom.get("otto_host_registration") or registration)
    mirror["raw_sha256"] = dict(files)
    custom["otto_host_registration"] = mirror
    project_json["custom"] = custom
    finished = session.portfolio.check_in_project(opened["project_ref"], session_id=opened["session_id"],
        project_json=project_json, document_changes=changes, actor=actor, request_id=key + ":check-in")
    if finished.get("outcome") not in {"finished", "replayed"}:
        raise RuntimeError("check-in failed: " + str(finished.get("error") or finished.get("outcome")))
    return {**result, "outcome": "synced", "request_key": key, "project_ref": finished.get("project_ref"),
            "recorded": [change["path"] for change in changes]}

"""Finite authenticated editor-buffer host over shared DAT/EDT operations.

The existing owner command lane executes every method. The service wait loop
only publishes a due idle attempt; it never reads or writes canonical state.
Live buffer tracking is disposable UI state. EDT handles and snapshots remain
its sole authority, and a restart requires an explicit holder resume/capture.
"""
from __future__ import annotations

import hashlib
import base64
from dataclasses import fields, is_dataclass
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping

from herzchen.authoring import AuthoringLifecycle, FileWriterLeaseAuthority
from herzchen.authoring.idle import DEFAULT_IDLE_SECONDS
from herzchen.authoring.sessions import AuthoringSessionService, SessionHandle
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.contracts import ResourceRef, canonical_json
from .owner_readers import json_value

def _json(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return json_value(value)


class DocumentEditorHost:
    def __init__(self, *, owner: Any, directory: str | Path, secret: bytes,
                 clock: Any = time.time, vision_validator: Any = None,
                 vision_operations: Any = None) -> None:
        self.actor, self.clock = owner.owner_actor, clock
        self.vision_operations = vision_operations
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.writer_id = "otto.document-editor"
        self.leases = FileWriterLeaseAuthority(
            self.directory / "writer-locks", authority=owner.store.authority,
            secret=secret, writer_identities=(self.writer_id,), clock=clock)
        self.sessions = AuthoringSessionService(owner.store, materializer=self._materialize)
        self.authoring = DocumentAuthoringHandler(owner.store, authoring=self.sessions,
                                                 vision_validator=vision_validator)
        self.lifecycle = AuthoringLifecycle(self.sessions, writer_leases=self.leases,
                                           writer_identity=self.writer_id, clock=clock)
        from .manager_application import ManagerApplication
        self.operations = ManagerApplication.from_owner(
            owner, document_authoring=self.authoring,
            idle_lifecycle=self.lifecycle).document_operations
        self._buffers: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _materialize(self, checkout: Any, initial_bytes: bytes) -> Mapping[str, Any]:
        # Session IDs originate in EDT, never in the transport. Refuse a path
        # already present rather than overwriting a previous checkout.
        session = checkout.session_id
        if not isinstance(session, str) or Path(session).name != session or session in {".", ".."}:
            raise ValueError("EDT session identifier is not a safe checkout component")
        root = self.directory / "checkouts" / session
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.mkdir(mode=0o700)
        path = root / "document.json"
        with path.open("xb") as stream:
            stream.write(initial_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
        return {"path": str(root), "registered_files": ["document.json"]}

    @staticmethod
    def _handle_value(handle: SessionHandle) -> dict[str, Any]:
        # This capability is returned only through authenticated owner ingress.
        return {key: json_value(getattr(handle, key)) for key in (
            "scope", "target_scope", "target_kind", "session_id", "token",
            "fence", "base_revision", "checkout_path")}

    def _handle(self, value: Any) -> SessionHandle:
        fields = {"scope", "target_scope", "target_kind", "session_id", "token",
                  "fence", "base_revision", "checkout_path"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise PermissionError("editor requires its exact owner-issued EDT handle")
        return SessionHandle(**{**value, "actor": self.actor,
            "scope": ResourceRef.from_dict(value["scope"]),
            "target_scope": ResourceRef.from_dict(value["target_scope"])})

    def _visible(self, project: ResourceRef | None, document: ResourceRef) -> None:
        if project is None:
            # This host is independently owner-authenticated. Standalone
            # documents use current DAT access, never a fabricated project.
            self.authoring.content.metadata(document, actor=self.actor)
            return
        read = self.operations.document_reader.read_document(project, document, actor=self.actor)
        if read.get("outcome") != "read":
            raise PermissionError("editor document is outside the current project read grant")

    def _resume(self, request: Mapping[str, Any]) -> Any:
        project = ResourceRef.from_dict(request["project_ref"]) if "project_ref" in request else None
        document = ResourceRef.from_dict(request["document_ref"])
        self._visible(project, document)
        handle = self._handle(request["handle"])
        material = self.authoring.resume(document, self.actor, handle)
        root = Path(material.handle.checkout_path or "").resolve()
        if root != self.directory / "checkouts" / handle.session_id:
            raise PermissionError("editor handle checkout is not materialized by this host")
        return material

    def _quiescent(self, material: Any) -> str:
        with self._lock:
            buffer = self._buffers.get(material.handle.session_id)
            if not buffer or not buffer["captured"] or buffer["writing"]:
                return "unknown"
            expected = buffer["digest"]
        # The same held retirement lease fences all managed writes while this
        # check runs. Neither a timer nor an mtime establishes buffer capture.
        actual = hashlib.sha256((Path(material.handle.checkout_path) / "document.json").read_bytes()).hexdigest()
        return "quiescent" if actual == expected else "unknown"

    def dispatch(self, request: Mapping[str, Any], *, actor: Any) -> Mapping[str, Any]:
        if actor != self.actor:
            raise PermissionError("editor requires the independently authenticated owner")
        if request.get("command") == "vision":
            if self.vision_operations is None or not callable(getattr(self.vision_operations, "dispatch", None)):
                raise PermissionError("Vision command surface is not installed on this owner host")
            return self.vision_operations.dispatch(request)
        operation = request.get("operation")
        common = {"command", "operation", "request_key"}
        session = {"document_ref", "handle"}
        fields = {
            "help": set(), "read": {"document_ref"},
            "open": {"document_ref"}, "inventory": set(),
            "recover": {"session_id"}, "discard-lost": {"session_id"}, "release-parked": {"session_id"},
            "resume": session, "status": session, "discard": session,
            "save": session | {"editor_buffer"},
            "finish": session, "idle-close": session,
        }
        allowed = common | fields.get(operation, {"unsupported"})
        if operation in {"read", "open", "resume", "status", "discard", "save", "finish", "idle-close"}:
            allowed.add("project_ref")
        if operation in {"open", "save", "resume"}:
            allowed.add("inactivity_seconds")
        if operation == "finish":
            allowed.add("expected_base_revision")
        if operation not in fields or set(request) - allowed or not (common | fields[operation]) <= set(request):
            raise ValueError("editor operation fields differ from the finite installed contract")
        key = request["request_key"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("editor request_key must be nonempty")
        if operation == "help":
            return {"outcome": "help", "command": "document-authoring",
                "transport": "exact owner-authoring grant through protected host input; caller IPC alone cannot grant authority",
                "fields": {name: sorted(common | required) for name, required in fields.items()},
                "optional_fields": {name: (["inactivity_seconds"] if name in {"open", "resume", "save"} else [])
                                    + (["expected_base_revision"] if name == "finish" else []) + ["project_ref"]
                                    for name in ("read", "open", "resume", "status", "discard", "save", "finish", "idle-close")},
                "default_inactivity_seconds": DEFAULT_IDLE_SECONDS,
                "buffer_format": {"content": "the editor's current JSON content value"},
                "handle": "retain the exact handle returned by open; never synthesize a token or actor",
                "flow": ["open", "save actual editor buffer", "inspect retained idle notification or explicit finish"],
                "restart": "inventory is observational; explicit resume plus save of the recovered editor buffer is required to rearm idle",
                "rejected_finish": "inspect retained draft; explicit discard and new open permit correction without publishing the rejected bytes",
                "publication": "DAT revision/receipt only; direction, assignment and resource adoption remain separate owner operations",
                "provider_called": False}
        if operation == "read":
            if "project_ref" not in request:
                document = ResourceRef.from_dict(request["document_ref"])
                self._visible(None, document)
                return dict(_json(self.authoring.read(document, self.actor)))
            return self.operations.document_reader.read_document(
                request["project_ref"], request["document_ref"], actor=self.actor)
        if operation == "inventory":
            # Canonical owner inventory, including lost handles. It is not a
            # mutation capability and exposes neither tokens nor fences.
            return dict(json_value(self.authoring.session_inventory(self.actor)))
        if operation == "recover":
            return dict(_json(self.authoring.recover_session(self.actor, request["session_id"])))
        if operation == "discard-lost":
            result = self.authoring.discard_session(self.actor, request["session_id"], request_id=key)
            return {"outcome": result.status, "nonpublishing": True,
                    "receipt": json_value(result.receipt), "cleanup_status": result.cleanup.value}
        if operation == "release-parked":
            # Frees a session the lifecycle parked for recovery; its retained files stay for cleanup.
            result = self.sessions.owner_release_parked(self.actor, request["session_id"], request_id=key)
            return {"outcome": result.status, "nonpublishing": True,
                    "receipt": json_value(result.receipt), "cleanup_status": result.cleanup.value}
        threshold = request.get("inactivity_seconds", DEFAULT_IDLE_SECONDS)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold < 0:
            raise ValueError("inactivity_seconds must be finite and nonnegative")
        if operation == "open":
            if "project_ref" not in request:
                document = ResourceRef.from_dict(request["document_ref"])
                self._visible(None, document)
                material = self.authoring.open_owned(document, self.actor, request_id=key)
            else:
                material = self.operations.open_edit(request["project_ref"], request["document_ref"], actor=self.actor, request_id=key)
            if isinstance(material, Mapping):
                return material
            if material.open_result.handle is None:
                return {"outcome": material.open_result.status, "reason": material.open_result.error,
                        "receipt": _json(material.refusal_receipt), "nonpublishing": True}
            with self._lock:
                self._buffers[material.handle.session_id] = {"captured": False, "writing": False,
                    "published": False, "inactivity_seconds": threshold}
            return {"outcome": material.open_result.status,
                    "handle": self._handle_value(material.handle),
                    "document_ref": material.target.to_dict(),
                    "inactivity_seconds": threshold,
                    "idle_armed": False, "nonpublishing": True}
        material = self._resume(request)
        if operation == "resume":
            # No uncaptured buffer or recovered timestamp is permission to
            # auto-publish after a process restart.
            return {"outcome": "resumed", "handle": self._handle_value(material.handle),
                    "status": self.operations.edit_status(material, actor=self.actor),
                    "idle_armed": False, "capture_required": True}
        if operation == "status":
            return self.operations.edit_status(material, actor=self.actor)
        if operation == "discard":
            result = self.operations.discard_edit(material, actor=self.actor, request_id=key)
            with self._lock:
                self._buffers.pop(material.handle.session_id, None)
            return result
        if operation == "save":
            with self._lock:
                prior = self._buffers.get(material.handle.session_id, {})
                threshold = request.get("inactivity_seconds", prior.get("inactivity_seconds", DEFAULT_IDLE_SECONDS))
            raw = canonical_json(request["editor_buffer"]).encode("utf-8")
            state = {"captured": False, "writing": True, "digest": hashlib.sha256(raw).hexdigest()}
            with self._lock:
                self._buffers[material.handle.session_id] = state
            try:
                with self.leases.open_writer(material.handle.checkout_path, "document.json",
                        writer_identity=self.writer_id, flags=os.O_WRONLY | os.O_TRUNC) as stream:
                    pending = memoryview(raw)
                    while pending:
                        written = stream.write(pending)
                        if written <= 0:
                            raise OSError("editor capture write did not advance")
                        pending = pending[written:]
                saved = self.operations.autosave_edit(material, request["editor_buffer"],
                    request_id=key, content_edit_at=self.clock())
                with self._lock:
                    state.update(writing=False, captured=saved["outcome"] in {"autosaved", "unchanged"},
                        last_content_edit=saved.get("last_content_edit"),
                        inactivity_seconds=threshold, published=False,
                        request={k: request[k] for k in ("project_ref", "document_ref", "handle") if k in request})
                return {**saved, "buffer_captured": state["captured"], "inactivity_seconds": threshold}
            finally:
                with self._lock:
                    state["writing"] = False
        if operation == "idle-close":
            with self._lock:
                buffer = self._buffers.get(material.handle.session_id)
                seconds = buffer["inactivity_seconds"] if buffer else DEFAULT_IDLE_SECONDS
            if not buffer or not buffer["captured"]:
                return {"outcome": "writer_active", "recovery_pending": True,
                    "capture_required": True, "dat_revision_advanced": False,
                    "error": "restart or uncaptured editor buffer requires explicit resume and save"}
            if self.clock() - buffer["last_content_edit"] < seconds:
                return {"outcome": "not_idle", "dat_revision_advanced": False,
                    "last_content_edit": buffer["last_content_edit"], "inactivity_seconds": seconds}
            result = self.operations.idle_close_edit(material, actor=self.actor, request_id=key,
                registered_files=("document.json",), inactivity_seconds=seconds,
                now=self.clock(), writer_check=lambda: self._quiescent(material))
        else:
            # The base is compared inside the owner lane, before the claim: a late
            # writer is refused with nothing claimed and the session stays open,
            # instead of failing the DAT apply after the claim and parking it. An
            # exact replay of a committed finish is left to the lifecycle receipt.
            expected = request.get("expected_base_revision", material.handle.base_revision)
            if self.sessions.reader.get_receipt(key) is None:
                refusal = self._stale_base(request, expected, material.handle.base_revision)
                if refusal is not None:
                    return refusal
            # Only an explicit base reaches the lifecycle: its request digest then
            # matches every finish retained before this field existed.
            result = self.lifecycle.finish(material.handle, request_id=key, mode="manual",
                checkout_root=material.handle.checkout_path, registered_files=("document.json",),
                handler=self.authoring.lifecycle_handler(material, request_id=key),
                expected_base_revision=request.get("expected_base_revision"), writer_check=lambda: self._quiescent(material))
            applied = result.finish.application
            revision = getattr(applied, "revision", None)
            document = getattr(applied, "document", None)
            committed = result.status in {"finished", "replayed", "already_finished"}
            revision_ref = ({**document.ref.to_dict(), "revision": revision.revision}
                            if document is not None and revision is not None else None)
            cleanup_pending = committed and (result.cleanup is None or result.cleanup.status.value != "complete")
            result = {"outcome": result.status, "finish": _json(result),
                "dat_revision_advanced": committed, "cleanup_pending": cleanup_pending,
                "publication": self.operations_publication(committed, revision_ref, result.receipt),
                "notification": {"status": "cleanup_pending" if cleanup_pending else result.status,
                    "durable": committed or result.receipt is not None,
                    "receipt": _json(result.receipt), "error": result.finish.error}}
        with self._lock:
            buffer = self._buffers.get(material.handle.session_id)
            if buffer is not None:
                buffer["published"] = True
                if result.get("outcome") not in {"checked_in", "finished", "replayed", "already_finished"}:
                    buffer["captured"] = False
        if result.get("outcome") in {"checked_in", "finished", "replayed", "already_finished"}:
            with self._lock:
                self._buffers.pop(material.handle.session_id, None)
        return _json(result)

    def _current_revision(self, request: Mapping[str, Any]) -> Any:
        document = ResourceRef.from_dict(request["document_ref"])
        if "project_ref" not in request:
            return self.authoring.content.read(document)["current_revision"]["revision"]
        ref = {key: value for key, value in request["document_ref"].items() if key != "revision"}
        read = self.operations.document_reader.read_document(request["project_ref"], ref, actor=self.actor)
        revision = (read.get("revision_ref") or {}).get("revision")
        if read.get("outcome") != "read" or revision is None:
            raise PermissionError("editor document revision is not readable under the current project grant")
        return revision

    def _stale_base(self, request: Mapping[str, Any], expected: Any, session_base: Any) -> Any:
        """A refusal naming the base the finish lost to, or None when the base is current."""
        current = self._current_revision(request)
        if current == expected == session_base:
            return None
        if expected != current:
            message = ("expected_base_revision %s is not the document's current revision %s; "
                       "the late writer is refused and the session stays open" % (expected, current))
        else:
            message = ("expected_base_revision %s is not the base this session opened on, %s; "
                       "release the session and open it again" % (expected, session_base))
        return {"outcome": "conflict", "error": {"code": "stale_base", "message": message},
                "expected_base_revision": expected, "session_base_revision": session_base,
                "current_revision": current, "dat_revision_advanced": False, "session_open": True,
                "nonpublishing": True, "publication": "not_published"}

    @staticmethod
    def operations_publication(committed: bool, revision_ref: Any, receipt: Any) -> Mapping[str, Any]:
        return {"status": "committed" if committed else "not_published",
            "dat_revision_ref": revision_ref, "receipt": _json(receipt),
            "direction_adoption": "not_performed", "assignment_adoption": "not_performed",
            "resource_adoption": "not_performed", "invocation_context": "unchanged"}

    def poll_idle(self, ingress: Any) -> list[Mapping[str, Any]]:
        """Called by the existing wait loop: local state and IPC publication only.

        Publication is once per captured buffer. The exact retained response
        is the UI notification; a failed attempt needs explicit owner recovery.
        No inline canonical work, second timer, thread or automatic retry.
        """
        requests = []
        with self._lock:
            for session, buffer in self._buffers.items():
                if (buffer["captured"] and not buffer["writing"] and not buffer["published"]
                        and buffer.get("last_content_edit") is not None
                        and self.clock() - buffer["last_content_edit"] >= buffer["inactivity_seconds"]):
                    requests.append({"command": "document-authoring", "operation": "idle-close",
                        "request_key": "editor-idle:" + session + ":" + buffer["digest"],
                        **buffer["request"]})
                    buffer["published"] = True
        return [ingress.publish({"schema": ingress.schema, "request": request}) for request in requests]


# One editor host per owner home, Store and project grant: its buffer capture state must
# survive from one `open` request to the next, and its grant is the one the session holds.
_OWNER_EDITORS: dict[tuple, tuple[Any, DocumentEditorHost]] = {}
_OWNER_EDITORS_LOCK = threading.Lock()


def _editor_secret(root: Path) -> bytes:
    """The lease secret, created once under the owner home and then reused across restarts."""
    path = root / "secret"
    if not path.exists():
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_bytes()
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(os.urandom(32))
    return path.read_bytes()


def owner_editor_host(session: Any, home: str | Path) -> DocumentEditorHost:
    """The owner's own editor host, built from the owner session the lane composed."""
    key = (str(Path(home).resolve()), tuple(getattr(session, "project_ids", ())))
    with _OWNER_EDITORS_LOCK:
        cached = _OWNER_EDITORS.get(key)
        if cached is not None and cached[0] is session.store:
            return cached[1]
        root = Path(home) / "editor"
        host = DocumentEditorHost(owner=session.owner, directory=root, secret=_editor_secret(root))
        _OWNER_EDITORS[key] = (session.store, host)
        return host

"""Exact owner-authenticated authoring grants over the existing file transport.

A trusted owner input (for example protected host stdin) calls publish. A
manager-accessible request file cannot issue a grant or choose its actor.
This port authorizes finite authoring only, not setup, dispatch or replacement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Mapping

from herzchen.contracts import AuthenticatedActor
from .execution_host import _atomic_json


class OwnerAuthoringIngress:
    schema = "otto.owner-authoring-grant.v1"
    fields = frozenset({"command", "operation", "request_key", "edit", "project_ref",
                        "project_json", "session_id", "files", "document_changes"})

    def __init__(self, *, actor: AuthenticatedActor, directory: str | Path,
                 owner_actor: AuthenticatedActor, max_bytes: int = 1048576) -> None:
        if not isinstance(actor, AuthenticatedActor) or actor != owner_actor:
            raise PermissionError("authoring ingress requires the authenticated service owner")
        self.actor, self.directory, self.max_bytes = actor, Path(directory), max_bytes
        self._grants: set[str] = set()
        self._lock = threading.Lock()

    def _checked(self, request: Any) -> tuple[dict[str, Any], bytes]:
        if (not isinstance(request, Mapping) or request.get("command") != "project-authoring"
                or set(request) - self.fields):
            raise PermissionError("owner authoring grant accepts only finite authoring fields")
        raw = json.dumps(dict(request), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > self.max_bytes:
            raise ValueError("owner authoring payload exceeds the bounded grant size")
        return json.loads(raw), raw

    def publish(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        """Trusted input only. Syntax/grant publication has no canonical effect."""
        if set(envelope) != {"schema", "request"} or envelope["schema"] != self.schema:
            raise PermissionError("owner authoring envelope differs")
        request, raw = self._checked(envelope["request"])
        digest = hashlib.sha256(raw).hexdigest()
        token = hashlib.sha256(b"otto-owner-authoring-grant-v1\0" + raw).hexdigest()
        path = self.directory / ("request-" + token + ".json")
        response = self.directory / ("response-" + token + ".json")
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists() and json.loads(path.read_text()) != request:
                raise RuntimeError("retained owner authoring request differs")
            self._grants.add(digest)
            if not path.exists() and not response.exists():
                _atomic_json(path, request)
        return {"outcome": "owner-granted", "request_id": token,
                "request_path": str(path), "response_path": str(response),
                "replayed_transport": response.exists(), "provider_called": False,
                "canonical_effect_recorded": False}

    def authorize(self, request: Mapping[str, Any]) -> AuthenticatedActor:
        """Existing serialized handler verifies the exact independently issued grant."""
        _, raw = self._checked(request)
        with self._lock:
            if hashlib.sha256(raw).hexdigest() not in self._grants:
                raise PermissionError("project authoring lacks an exact authenticated owner input grant")
        return self.actor

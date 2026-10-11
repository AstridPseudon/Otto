"""Finite identity-bearing installed socket client; identity comes from the peer.

No actor/session selector, credential, environment identity or fallback file
lane exists. A failed connection is returned to the owner, never retried here.
"""
import argparse
import json
from pathlib import Path
import socket
from typing import Optional
import uuid

_DEFAULT_TIMEOUT = 15
_LONG_OPERATION_TIMEOUT = 60
_LONG_OPERATIONS = frozenset({"report", "request-help", "respond-help", "resolve-help", "read-help"})
_LAUNCH_OPERATIONS = frozenset({"launch", "run-worker"})


def _operation(request: dict) -> Optional[str]:
    value = request.get("command", request.get("operation"))
    return value if isinstance(value, str) else None


def _timeout_for(request: dict, explicit: Optional[float]) -> float:
    """Use longer bounded waits for report/help reads and mutations."""
    if explicit is not None:
        return explicit
    return _LONG_OPERATION_TIMEOUT if _operation(request) in _LONG_OPERATIONS else _DEFAULT_TIMEOUT


def _recovery_advice(request: dict, request_id: str) -> str:
    operation = _operation(request)
    first = f"Run command-status --request-id {request_id} first; do not resend."
    if operation in _LAUNCH_OPERATIONS:
        return (first + " If status remains unknown, use lookup-occurrence only for this exact launch/run-worker, "
                "with its original scope, canonical request key and complete original input. "
                "Retention and effects remain unconfirmed until read back.")
    if operation in _LONG_OPERATIONS or operation in {"outcome", "help"}:
        return (first + " If status remains uncaptured, inspect the exact scope and canonical logical request key "
                "for the existing report/help/outcome; do not replay it. Retention and effects remain "
                "unconfirmed until read back.")
    return first + " Retention and effects remain unconfirmed until read back; do not infer absence or replay."


def call_connection(connection: socket.socket, request: dict) -> dict:
    """One request on a host-provided Unix connection; no identity selector.

    Used by call() and local inherited-descriptor custody fixtures. Possession
    of a descriptor is not authorization; the owner verifies its kernel peer.
    """
    if not isinstance(connection, socket.socket) or connection.family != socket.AF_UNIX or not isinstance(request, dict):
        raise ValueError("Unix connection and bounded command object required")
    request_id = uuid.uuid4().hex
    raw = json.dumps({**request, "transport_request_id": request_id}, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(raw) > 256 * 1024:
        raise ValueError("bounded command payload required")
    sent = False
    try:
        # Once a send is attempted its effect may have reached the owner.
        sent = True
        connection.sendall(raw)
        chunks, size = [], 0
        while True:
            part = connection.recv(65536)
            if not part: break
            size += len(part)
            if size > 4 * 1024 * 1024:
                raise ValueError("bounded installed response exceeded")
            chunks.append(part)
        return json.loads(b"".join(chunks))
    except (OSError, ValueError) as exc:
        return {"outcome": "unknown" if sent else "unavailable", "retry": False,
                "outer_command": {"transport": "unix-socket", "request_id": request_id,
                                  "retained": None, "retention": "unconfirmed"},
                "error": {"kind": "transport", "code": type(exc).__name__, "message": str(exc)},
                "next_action": _recovery_advice(request, request_id)}


def call(path: str, request: dict, *, timeout: Optional[float] = None) -> dict:
    if not Path(path).is_absolute() or not isinstance(request, dict):
        raise ValueError("absolute installed socket and command object required")
    compact_operation = None
    if request.get("command") == "compact-read":
        from .compact_reads import compact_read_request
        request = compact_read_request(request)
        compact_operation = request["command"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_timeout_for(request, timeout))
        try:
            connection.connect(path)
        except OSError as exc:
            return {"outcome": "unavailable", "retry": False,
                    "error": {"kind": "transport", "code": type(exc).__name__, "message": str(exc)},
                    "next_action": "restore the supported owner connection; no command was sent"}
        result = call_connection(connection, request)
        if compact_operation is not None:
            from .compact_reads import compact_read_response
            return compact_read_response(result, operation=compact_operation)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--command", choices=("whoami", "effective-context"))
    group.add_argument("--request", help="ordinary command JSON; caller claims never grant identity")
    args = parser.parse_args()
    result = call(args.socket, {"command": args.command} if args.command else json.loads(args.request))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("outcome") not in {"error", "held", "unavailable"} else 1


if __name__ == "__main__": raise SystemExit(main())

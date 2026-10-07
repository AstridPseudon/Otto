"""Finite identity-bearing installed socket client; identity comes from the peer.

No actor/session selector, credential, environment identity or fallback file
lane exists. A failed connection is returned to the owner, never retried here.
"""
import argparse
import json
from pathlib import Path
import socket


def call(path: str, request: dict, *, timeout: float = 15) -> dict:
    if not Path(path).is_absolute() or not isinstance(request, dict):
        raise ValueError("absolute installed socket and command object required")
    raw = json.dumps(request, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(raw) > 256 * 1024:
        raise ValueError("bounded command payload required")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(raw)
        chunks = []
        size = 0
        while True:
            part = connection.recv(65536)
            if not part: break
            size += len(part)
            if size > 4 * 1024 * 1024:
                raise ValueError("bounded installed response exceeded")
            chunks.append(part)
    return json.loads(b"".join(chunks))


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

"""Public cold caller for the finite onboarding owner facade.

The process reads only an issued command-socket descriptor. It cannot construct
an owner, select an actor, inspect a Store, or build an owner request envelope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 262_144


def dispatch(client: Any, request: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(request, Mapping) or not isinstance(request.get("operation"), str):
        raise ValueError("JSON request needs a finite operation")
    operation = request["operation"]
    if operation in {"whoami", "help"}:
        if set(request) != {"operation"}:
            raise ValueError("whoami/help take no caller-selected fields")
        return client.call(operation)
    if operation == "cli":
        if set(request) != {"operation", "argv"} or not isinstance(request["argv"], list):
            raise ValueError("cli requires only an argv list")
        return client.call("cli", request["argv"])
    if operation == "save":
        fields = {"operation", "project_ref", "session_id", "project_json", "document_changes", "request_key"}
        if set(request) != fields:
            raise ValueError("save requires its exact bounded fields")
        return client.call("save", request["project_ref"], request["session_id"], request["project_json"],
                           request["document_changes"], request["request_key"])
    if operation == "release":
        if set(request) != {"operation", "project_ref", "session_id", "request_key"}:
            raise ValueError("release requires its exact bounded fields")
        return client.call("release", request["project_ref"], request["session_id"], request["request_key"])
    if operation in {"queue", "activation"}:
        expected = {"operation", "suboperation", "arguments"}
        if set(request) != expected or not isinstance(request["suboperation"], str) or not isinstance(request["arguments"], Mapping):
            raise ValueError("queue/activation need a finite suboperation and arguments object")
        return client.call(operation, request["suboperation"], request["arguments"])
    if operation == "journey":
        expected = {"operation", "suboperation", "arguments"}
        allowed = {"read-result", "read-artifact", "consume-result", "review-input",
                   "review-task", "finish-task", "finish-project"}
        if (set(request) != expected or request.get("suboperation") not in allowed
                or not isinstance(request.get("arguments"), Mapping)):
            raise ValueError("journey needs one finite operation and a bounded arguments object")
        return client.call("journey", request["suboperation"], request["arguments"])
    raise PermissionError("operation is outside the issued onboarding facade")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Call the host-issued finite onboarding facade")
    parser.add_argument("--connection", required=True, help="private JSON command-socket capability file")
    parser.add_argument("--request-json", required=True, help="one bounded JSON operation")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.connection).read_bytes()
        request_bytes = args.request_json.encode("utf-8")
        if len(raw) > MAX_RESPONSE_BYTES or len(request_bytes) > MAX_REQUEST_BYTES:
            raise ValueError("connection or request exceeds the finite input bound")
        connection = json.loads(raw)
        request = json.loads(request_bytes)
        if not isinstance(connection, dict) or not isinstance(request, dict):
            raise ValueError("connection and request must be JSON objects")
        from herzchen.command_ports import connect_consumer_facade
        client = connect_consumer_facade(connection)
        result = dispatch(client, request)
        output = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(output.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds the finite output bound")
        print(output)
        return 0
    except Exception as exc:
        print(json.dumps({"schema": "otto.bound-onboarding-cli-error.v1", "outcome": "error",
                          "error": type(exc).__name__, "message": str(exc)[:512],
                          "provider_called": False}, sort_keys=True, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

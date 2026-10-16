"""A minimal MCP server over stdio. An agent CLI spawns it as a child; it forwards tools/list and tools/call to a FacadeServer socket, using the token from its environment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TextIO

from .server import request

__all__ = ["serve", "main"]

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "fleet-tools", "version": "1"}

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


def _ok(msg_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _valid_id(msg_id: object) -> bool:
    return msg_id is None or isinstance(msg_id, (str, int, float))


def _descriptor(entry: dict) -> dict:
    """An MCP tool descriptor from one facade listing entry. Argument values are free-form JSON."""

    args = entry.get("args") or []
    return {
        "name": entry["name"],
        "description": entry.get("description", ""),
        "inputSchema": {
            "type": "object",
            "properties": {name: {} for name in args},
            "additionalProperties": False,
        },
    }


def _list_tools(socket_path: str, token: str) -> dict:
    reply = request(socket_path, {"op": "list", "token": token})
    if reply.get("ok") is not True:
        return {"tools": []}
    return {"tools": [_descriptor(entry) for entry in reply.get("tools", [])]}


def _call_tool(socket_path: str, token: str, params: dict) -> dict | None:
    name = params.get("name")
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(name, str) or not name or not isinstance(arguments, dict):
        return None
    reply = request(socket_path, {"op": "call", "token": token, "tool": name, "args": arguments})
    return {
        "content": [{"type": "text", "text": json.dumps(reply, sort_keys=True)}],
        "isError": not reply.get("ok"),
    }


def _dispatch(socket_path: str, token: str, text: str) -> dict | None:
    """The reply object for one JSON-RPC line, or None when the line is a notification."""

    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return _rpc_error(None, _PARSE_ERROR, "parse error")
    if not isinstance(message, dict):
        return _rpc_error(None, _INVALID_REQUEST, "invalid request")
    if "id" not in message:
        return None
    msg_id = message["id"]
    if not _valid_id(msg_id):
        return _rpc_error(None, _INVALID_REQUEST, "invalid request")
    method = message.get("method")
    if not isinstance(method, str):
        return _rpc_error(msg_id, _INVALID_REQUEST, "invalid request")

    if method not in ("initialize", "ping", "tools/list", "tools/call"):
        return _rpc_error(msg_id, _METHOD_NOT_FOUND, "method not found")
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _rpc_error(msg_id, _INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        version = params.get("protocolVersion")
        if not isinstance(version, str):
            version = PROTOCOL_VERSION
        return _ok(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": dict(SERVER_INFO),
            },
        )
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, _list_tools(socket_path, token))
    result = _call_tool(socket_path, token, params)
    if result is None:
        return _rpc_error(msg_id, _INVALID_PARAMS, "invalid tool call parameters")
    return _ok(msg_id, result)


def serve(socket_path: str, token: str, instream: TextIO, outstream: TextIO) -> None:
    """Read newline-delimited JSON-RPC until EOF, answering each request line. Never echoes the token."""

    for line in instream:
        text = line.strip()
        if not text:
            continue
        try:
            reply = _dispatch(socket_path, token, text)
        except Exception:
            reply = _rpc_error(None, _INTERNAL_ERROR, "internal error")
        if reply is None:
            continue
        try:
            outstream.write(json.dumps(reply, sort_keys=True) + "\n")
            outstream.flush()
        except BrokenPipeError:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stdio MCP server that forwards tool calls to a facade socket.")
    parser.add_argument("--socket", required=True, metavar="PATH", help="facade socket path")
    parser.add_argument("--token-env", required=True, metavar="NAME", help="environment variable holding the token")
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "")
    os.environ.pop(args.token_env, None)
    if not token:
        sys.stderr.write("stdio_server: token variable is missing or empty\n")
        return 2
    serve(args.socket, token, sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

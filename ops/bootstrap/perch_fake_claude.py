#!/opt/homebrew/bin/python3.11 -B
"""Disposable Claude stream for PERCH stage-2 --fake worker turns.

The owner pins this launcher through its normal Claude adapter. It writes a
small artifact inside the worker's fenced lab, never in the owner's tree.
"""

import json
import os
import signal
import socket
import sys
import uuid
from pathlib import Path


def await_release(marker):
    """Hold one owner-launched turn until the harness has taken its product reads."""
    released = False

    def release(_signal, _frame):
        nonlocal released
        released = True

    signal.signal(signal.SIGUSR1, release)
    with open(marker, "w", encoding="utf-8") as output:
        output.write(str(os.getpid()) + "\n")
    while not released:
        signal.pause()


def emit(value):
    print(json.dumps(value), flush=True)


def done_tool(args):
    """Submit through the owner-issued, token-fenced worker tool socket."""
    config = json.loads(args[args.index("--mcp-config") + 1])
    entry = config["mcpServers"]["otto"]
    server_args = entry["args"]
    socket_path = server_args[server_args.index("--socket") + 1]
    token_name = server_args[server_args.index("--token-env") + 1]
    token = os.environ[token_name]
    request = {"op": "call", "token": token, "tool": "done",
               "args": {"summary": "PERCH stage-2 canary worker finished"}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(socket_path)
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        with client.makefile("r", encoding="utf-8") as stream:
            reply = json.loads(stream.readline())
    if reply.get("ok") is not True:
        raise RuntimeError("owner done tool refused: " + repr(reply))
    return reply


def canary_alias(prompt):
    """Select the assigned task from the owner-bound resource brief."""
    opening = '<otto-resource-brief sha256="'
    if prompt.count(opening) != 1:
        raise ValueError("fake worker needs one owner resource brief")
    body = prompt.split(opening, 1)[1].split('>\n', 1)[1].split('\n</otto-resource-brief>', 1)[0]
    brief = json.loads(body)
    contract = brief.get("instruction_contract") or {}
    core = brief.get("operating_core") or {}
    priorities = core.get("priorities") or []
    for alias in ("A", "B", "C"):
        if (core.get("role") == "worker"
                and contract.get("objective") == "Implement the delegated " + alias + " outcome"
                and (contract.get("task_ref") or {}).get("kind") == "work.task"
                and len(priorities) == 1 and priorities[0].get("id") == alias.lower()):
            return alias
    raise ValueError("fake worker brief has no exact stage-2 task identity")


def canary_workspace_role():
    """Recognize the owner-supplied canary worktree or its fenced lab cwd."""
    cwd = Path.cwd()
    if (cwd.name == "canon" and cwd.parent.name.startswith("2-")
            and cwd.parent.parent.name == "perch-canary"):
        return "manager"
    for parent in cwd.parents:
        if (parent.name == "canon.otto-labs" and parent.parent.name.startswith("2-")
                and parent.parent.parent.name == "perch-canary"):
            return "worker"
    return None


def main():
    if "--version" in sys.argv:
        print("2.1.293 (Claude Code)")
        return 0
    args = sys.argv[1:]
    model = args[args.index("--model") + 1]
    # The real host passes --tools "" for its inert initializer. Its native
    # init event must report no tools so the owner can authorize the work turn.
    tool_names = args[args.index("--tools") + 1]
    tools = tool_names.split(",") if tool_names else []
    request = json.loads(sys.stdin.readline())
    prompt = request["message"]["content"][0]["text"]
    initializer = prompt.startswith("Initialize this session only.")
    session = (args[args.index("--resume") + 1] if "--resume" in args
               else request.get("session_id") or "perch-" + uuid.uuid4().hex[:12])
    config = json.loads(args[args.index("--mcp-config") + 1]) if "--mcp-config" in args else {"mcpServers": {}}
    servers = list(config.get("mcpServers") or {})
    mcp_tools = [arg for arg in args if arg.startswith("mcp__")]
    mode = args[args.index("--permission-mode") + 1] if "--permission-mode" in args else "bypassPermissions"
    emit({"type": "system", "subtype": "init", "session_id": session,
          "cwd": os.getcwd(), "model": model, "permissionMode": mode,
          "tools": tools + mcp_tools, "mcp_servers": servers, "plugins": [], "skills": [], "slash_commands": []})
    emit({"type": "user", "uuid": "input-" + uuid.uuid4().hex[:8], "session_id": session,
          "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})
    if initializer:
        emit({"type": "result", "subtype": "success", "is_error": False,
              "session_id": session, "uuid": "done-" + uuid.uuid4().hex[:8],
              "result": "READY", "usage": {"input_tokens": 1, "output_tokens": 1}})
        return 0
    workspace_role = canary_workspace_role()
    try:
        alias = canary_alias(prompt)
    except ValueError:
        if workspace_role != "manager":
            raise
        alias = None
    if alias is None:
        if workspace_role == "manager":
            await_release(".perch-manager.pid")
        emit({"type": "result", "subtype": "success", "is_error": False,
              "session_id": session, "uuid": "done-" + uuid.uuid4().hex[:8],
              "result": "PERCH manager turn complete", "usage": {"input_tokens": 1, "output_tokens": 1}})
        return 0
    if tools and "Bash" not in tools:
        if alias == "C":
            # Stage 2 kills this exact owner-launched worker to verify that
            # only its slot is released. The PID marker is inside its lab.
            with open(".perch-worker-C.pid", "w", encoding="utf-8") as marker:
                marker.write(str(os.getpid()) + "\n")
            signal.pause()
            return 1
        if alias in {"A", "B"} and workspace_role == "worker":
            await_release(".perch-worker-" + alias + ".pid")
        path = os.path.join(os.getcwd(), "perch-worker-" + session + ".txt")
        content = "PERCH stage-2 worker artifact from " + model + "\n"
        emit({"type": "assistant", "uuid": "write-" + session, "session_id": session,
              "message": {"role": "assistant", "model": model,
                          "content": [{"type": "tool_use", "id": "write-1", "name": "Write",
                                       "input": {"file_path": path, "content": content}}]}})
        with open(path, "w", encoding="utf-8") as output:
            output.write(content)
        emit({"type": "user", "uuid": "result-" + session, "session_id": session,
              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "write-1",
                                                       "is_error": False, "content": "written"}]}})
        if "mcp__otto__done" in mcp_tools:
            emit({"type": "assistant", "uuid": "submit-" + session, "session_id": session,
                  "message": {"role": "assistant", "model": model,
                              "content": [{"type": "tool_use", "id": "done-1", "name": "mcp__otto__done",
                                           "input": {"summary": "PERCH stage-2 canary worker finished"}}]}})
            try:
                result = done_tool(args)
            except Exception as exc:
                print(str(exc), file=sys.stderr)
                emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "session_id": session, "uuid": "failed-" + uuid.uuid4().hex[:8],
                      "result": str(exc)[:2000]})
                return 1
            emit({"type": "user", "uuid": "done-tool-" + session, "session_id": session,
                  "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "done-1",
                                                           "is_error": False, "content": json.dumps(result)}]}})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "session_id": session, "uuid": "done-" + uuid.uuid4().hex[:8],
          "result": "PERCH canary turn complete", "usage": {"input_tokens": 3, "output_tokens": 2}})
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/opt/homebrew/bin/python3.11 -B
"""Disposable Claude stream for PERCH stage-2 --fake worker turns.

The owner pins this launcher through its normal Claude adapter. It writes a
small artifact inside the worker's fenced lab, never in the owner's tree.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
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


def worker_tool(args, tool, tool_args=None):
    """Call a real owner-issued, token-fenced worker tool socket."""
    config = json.loads(args[args.index("--mcp-config") + 1])
    entry = config["mcpServers"]["otto"]
    server_args = entry["args"]
    socket_path = server_args[server_args.index("--socket") + 1]
    token_name = server_args[server_args.index("--token-env") + 1]
    token = os.environ[token_name]
    request = {"op": "call", "token": token, "tool": tool, "args": tool_args or {}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(socket_path)
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        with client.makefile("r", encoding="utf-8") as stream:
            reply = json.loads(stream.readline())
    return reply


def worker_tool_pair(args, requests):
    """Queue two token-authenticated tool requests before reading either reply."""
    config = json.loads(args[args.index("--mcp-config") + 1])
    entry = config["mcpServers"]["otto"]
    server_args = entry["args"]
    socket_path = server_args[server_args.index("--socket") + 1]
    token_name = server_args[server_args.index("--token-env") + 1]
    token = os.environ[token_name]
    clients = [socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) for _ in requests]
    streams = []
    try:
        for client, (tool, tool_args) in zip(clients, requests):
            client.connect(socket_path)
            client.sendall((json.dumps({"op": "call", "token": token, "tool": tool,
                                        "args": tool_args}) + "\n").encode("utf-8"))
        for client in clients:
            streams.append(client.makefile("r", encoding="utf-8"))
        return [json.loads(stream.readline()) for stream in streams]
    finally:
        for stream in streams:
            stream.close()
        for client in clients:
            client.close()


def done_tool(args):
    """Submit through the owner-issued, token-fenced worker tool socket."""
    reply = worker_tool(args, "done", {"summary": "PERCH stage-2 canary worker finished"})
    if reply.get("ok") is not True:
        raise RuntimeError("owner done tool refused: " + repr(reply))
    return reply


def disturbance(alias):
    """Read a harness trigger from the disposable admitted project's directory."""
    for parent in (Path.cwd(), *Path.cwd().parents):
        if parent.name.startswith("2-") and parent.parent.name == "perch-canary":
            marker = parent / (".perch-disturb-" + alias + ".json")
            if marker.is_file():
                try:
                    value = json.loads(marker.read_text(encoding="utf-8"))
                except Exception:
                    value = {"mode": marker.read_text(errors="replace").strip()}
                value["marker_dir"] = str(parent)
                return value
    return {}


def apply_disturbance(args, alias, mode):
    """Exercise disturbances through the actual worker tool socket."""
    marker_dir = Path(disturbance(alias).get("marker_dir", Path.cwd()))
    trace = marker_dir / (".perch-disturb-" + alias + "-trace.json")
    if mode in {"conflict", "double-done"}:
        (marker_dir / (".perch-disturb-" + alias + ".pid")).write_text(str(os.getpid()) + "\n",
                                                                          encoding="utf-8")
    calls = []
    if mode == "check-failure":
        # Make the admitted repository check fail inside this real fenced lab.
        target = Path.cwd() / "toy" / "mathx.py"
        if target.exists():
            target.write_text(target.read_text(encoding="utf-8") + "\nthis is invalid python !!!\n", encoding="utf-8")
        calls.append(worker_tool(args, "done", {"summary": "exercise retained landing refusal"}))
        if target.exists():
            target.write_text(target.read_text(encoding="utf-8").replace("\nthis is invalid python !!!\n", "\n"), encoding="utf-8")
        calls.append(worker_tool(args, "done", {"summary": "retry after refusal"}))
    elif mode == "double-done":
        calls.extend(worker_tool_pair(args, [
            ("done", {"summary": "first queued landing request"}),
            ("done", {"summary": "second queued landing request"}),
        ]))
    elif mode in {"conflict", "hold"}:
        if mode == "conflict":
            target = Path.cwd() / "toy" / "perch_disturb_slot.py"
            if not target.exists():
                raise RuntimeError("conflict seed file is absent from the admitted repository")
            target.write_text("PERCH_DISTURB_SLOT = 'worker'\n", encoding="utf-8")
            await_release(".perch-worker-" + alias + ".pid")
        else:
            await_release(".perch-worker-" + alias + ".pid")
        calls.append(worker_tool(args, "done", {"summary": "PERCH disturbance task finished"}))
    else:
        return False
    trace.write_text(json.dumps({"mode": mode, "task": alias, "responses": calls}, sort_keys=True, indent=2) + "\n",
                     encoding="utf-8")
    return True


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
    for alias in ("A", "B", "C", "D", "E", "F", "G", "H", "I"):
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


def manager_entrypoint(prompt):
    """Use the exact installed command introduced by the owner to this turn."""
    opening = '<otto-resource-brief sha256="'
    if prompt.count(opening) != 1:
        raise ValueError("fake manager needs one owner resource brief")
    body = prompt.split(opening, 1)[1].split('>\n', 1)[1].split('\n</otto-resource-brief>', 1)[0]
    brief = json.loads(body)
    core = brief.get("operating_core") or {}
    entrypoint = (core.get("introduction") or {}).get("tool_entrypoint")
    if core.get("role") != "manager" or not isinstance(entrypoint, str) or not entrypoint.endswith("/ottoctl"):
        raise ValueError("fake manager has no exact installed client")
    if not Path(entrypoint).is_file():
        raise FileNotFoundError(entrypoint)
    return entrypoint


def manager_project_id(prompt):
    """Read the project pinned into this manager's adopted operating context."""
    opening = '<otto-resource-brief sha256="'
    if prompt.count(opening) != 1:
        return "perch-stage2"
    body = prompt.split(opening, 1)[1].split('>\n', 1)[1].split('\n</otto-resource-brief>', 1)[0]
    brief = json.loads(body)
    context = ((brief.get("operating_core") or {}).get("introduction") or {}).get("manager_operating_context") or {}
    project_ref = context.get("project_ref")
    project_id = project_ref.get("id") if isinstance(project_ref, dict) else None
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("fake manager brief has no pinned project in its operating context")
    return project_id


def manager_marker(prompt):
    project = manager_project_id(prompt)
    return ".perch-manager.pid" if project == "perch-stage2" else ".perch-manager-" + project + ".pid"


def installed_client(entrypoint, *words):
    result = subprocess.run([entrypoint, "manager", *words], capture_output=True, text=True,
                            check=False)
    try:
        response = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("installed manager client returned no JSON: " + result.stderr[-1000:]) from exc
    if result.returncode or response.get("outcome") in {"error", "denied", "unavailable", "unknown"}:
        raise RuntimeError("installed manager client refused " + words[0] + ": " + repr(response))
    return response


def scripted_manager_turn(alias, *, client):
    """One owner-started turn records a judgment or reconciles C's exact Due."""
    if alias in {"A", "B", "F", "G"}:
        observed = client("review-input", "--task", alias)
        if observed.get("outcome") == "pending":
            return "pending"
        if observed.get("review_eligible") is False and observed.get("completion", {}).get("state") == "recorded":
            return "completed"
        if (observed.get("outcome") != "read"
                or observed.get("task_outcome") not in (None, "Canary dispatch " + alias)
                or not isinstance(observed.get("worker_result_sha256"), str)
                or len(observed["worker_result_sha256"]) != 64
                or not isinstance(observed.get("criterion_aliases"), dict)
                or not observed["criterion_aliases"]
                or not isinstance(observed.get("candidate_ref"), dict)
                or observed["candidate_ref"] not in observed.get("evidence_refs", ())):
            raise RuntimeError("canary " + alias + " has no inspectable retained worker result: " + repr(observed))
        evidence = observed["evidence_refs"]
        judgments = {criterion: {"verdict": "PASS", "rationale": "perch" + alias + "Checked",
                     "evidence_refs": evidence} for criterion in observed["criterion_aliases"]}
        inspection = {"observed": "Retained owner worker result matches the canary outcome and exact evidence refs",
                      "worker_result_sha256": observed["worker_result_sha256"],
                      "observed_turn_id": observed.get("observed_turn_id"),
                      "task_outcome": observed["task_outcome"]}
        command = ["review-task", "--task", alias, "--request-key", "perch-stage2-review-" + alias,
                   "--candidate-ref", json.dumps(observed["candidate_ref"], separators=(",", ":"))]
        for ref in observed["source_refs"]:
            command += ["--source-ref", json.dumps(ref, separators=(",", ":"))]
        command += ["--judgments", json.dumps(judgments, separators=(",", ":")),
                    "--inspection", json.dumps(inspection, separators=(",", ":"))]
        reviewed = client(*command)
        if (reviewed.get("outcome") != "accepted" or not reviewed.get("gate_refs")
                or (reviewed.get("completion") or {}).get("outcome") not in {"pending", "completed", "replayed"}):
            raise RuntimeError("canary " + alias + " review or finish was refused: " + repr(reviewed))
        return "reviewed"
    if alias != "C":
        raise ValueError("unknown canary alias")
    status = client("status")
    schedule = ((status.get("workers") or {}).get("C") or {}).get("schedule_id")
    if not isinstance(schedule, str) or not schedule:
        return "pending"
    observed = client("execution-control", "--operation", "read", "--schedule-id", schedule)
    recovery = observed.get("recovery") or {}
    pins = recovery.get("manager_gone_group_recovery") or {}
    if recovery.get("state") != "held_failed":
        if (observed.get("occurrence") or {}).get("stop_state") == "stopped":
            return "recovered"
        return "pending"
    if not all(isinstance(pins.get(key), str) and len(pins[key]) == 64
               for key in ("expected_due_sha256", "expected_result_sha256")):
        raise RuntimeError("killed C has no exact retained recovery pins: " + repr(observed))
    settled = client("execution-control", "--operation", "recover", "--schedule-id", schedule,
                     "--request-key", "perch-stage2-recover-C", "--expected-due-sha256",
                     pins["expected_due_sha256"], "--expected-result-sha256", pins["expected_result_sha256"],
                     "--reason", "Stage 2 worker C was SIGKILLed after owner dispatch")
    if settled.get("outcome") == "refused" and settled.get("cause") == "process_group_alive":
        return "pending"
    if (settled.get("outcome") not in {"settled", "replayed"} or settled.get("manager_recovery") is not True
            or settled.get("historical_result_preserved") is not True or settled.get("provider_called") is not False):
        raise RuntimeError("killed C recovery was not accepted: " + repr(settled))
    return "recovered"


def manager_journey(prompt):
    entrypoint = manager_entrypoint(prompt)
    client = lambda *words: installed_client(entrypoint, *words)
    project = manager_project_id(prompt)
    aliases = ("F", "G") if project == "perch-disturb" else ("A", "B")
    for alias in aliases:
        while True:
            state = scripted_manager_turn(alias, client=client)
            if state == "completed":
                break
            if state == "reviewed":
                # The current native manager turn must return before its
                # retained finish intent can settle and wake the next turn.
                return state
            time.sleep(0.25)
    if project == "perch-disturb":
        return "completed"
    # The accepted B completion wakes this same manager. Keep that turn
    # available while the owner dispatches and the harness kills worker C.
    while True:
        state = scripted_manager_turn("C", client=client)
        if state == "recovered":
            return state
        time.sleep(0.25)


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
            marker = manager_marker(prompt)
            if not Path(marker).exists():
                await_release(marker)
            try:
                result = manager_journey(prompt)
            except Exception as exc:
                print(str(exc), file=sys.stderr)
                emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "session_id": session, "uuid": "failed-" + uuid.uuid4().hex[:8],
                      "result": str(exc)[:2000]})
                return 1
        else:
            result = "PERCH manager turn complete"
        emit({"type": "result", "subtype": "success", "is_error": False,
              "session_id": session, "uuid": "done-" + uuid.uuid4().hex[:8],
              "result": "PERCH manager turn " + result, "usage": {"input_tokens": 1, "output_tokens": 1}})
        return 0
    mode = (disturbance(alias).get("mode") or "").strip()
    if mode == "failed-launch":
        print("PERCH seeded fake launcher failure for admitted task " + alias, file=sys.stderr)
        marker_dir = disturbance(alias).get("marker_dir")
        if marker_dir:
            (Path(marker_dir) / (".perch-disturb-" + alias + ".json")).unlink(missing_ok=True)
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "session_id": session, "uuid": "failed-" + uuid.uuid4().hex[:8],
              "result": "PERCH seeded launcher failure"})
        return 1
    if tools and "Bash" not in tools:
        if alias == "C":
            # Stage 2 kills this exact owner-launched worker to verify that
            # only its slot is released. The PID marker is inside its lab.
            with open(".perch-worker-C.pid", "w", encoding="utf-8") as marker:
                marker.write(str(os.getpid()) + "\n")
            signal.pause()
            return 1
        if (alias in {"A", "B"} and workspace_role == "worker"
                and mode not in {"check-failure", "double-done", "conflict", "hold"}):
            await_release(".perch-worker-" + alias + ".pid")
        if (alias in {"A", "B"} and workspace_role == "worker"
                and mode in {"check-failure", "double-done", "conflict", "hold"}):
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
            if mode in {"check-failure", "double-done", "conflict", "hold"}:
                try:
                    apply_disturbance(args, alias, mode)
                except Exception as exc:
                    print(str(exc), file=sys.stderr)
                    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "session_id": session, "uuid": "failed-" + uuid.uuid4().hex[:8],
                          "result": str(exc)[:2000]})
                    return 1
                emit({"type": "result", "subtype": "success", "is_error": False,
                      "session_id": session, "uuid": "done-" + uuid.uuid4().hex[:8],
                      "result": "PERCH disturbance calls completed", "usage": {"input_tokens": 3, "output_tokens": 2}})
                return 0
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

"""Tests for the product-neutral tool facade core in herzchen.fleet.tools."""

import pytest

from herzchen.fleet.tools import (
    CHECK,
    DONE,
    KINDS,
    TASK,
    Acceptance,
    AcceptanceError,
    FeedbackLedger,
    OwnerPort,
    ToolFacade,
    ToolRuleError,
    ToolSpec,
    TokenBook,
)

# --- core: tokens, facade, check-versus-done

ROLE = "worker"
TASK_TOOL = "task_run"
CHECK_TOOL = "run_check"
DONE_TOOL = "submit"
TASK_OP = "do_task"
CHECK_OP = "run_check_op"
DONE_OP = "submit_op"

CANNED = {
    TASK_OP: {"status": "started", "accepted": True, "acceptance": "yes"},
    CHECK_OP: {"run_id": "run-1", "commit": "c1", "ok": True, "accepted": True},
    DONE_OP: {"submitted": True, "counts_as_acceptance": True},
}


class FakeOwner(OwnerPort):
    """Records every call and returns canned replies. An exception value is raised instead."""

    def __init__(self, replies=None):
        self.replies = dict(CANNED if replies is None else replies)
        self.calls = []

    def call(self, operation, assignment, args, *, feedback):
        self.calls.append(
            {"operation": operation, "assignment": assignment, "args": dict(args), "feedback": feedback}
        )
        reply = self.replies[operation]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _tools():
    return [
        ToolSpec(name=TASK_TOOL, kind=TASK, operation=TASK_OP, args=("title",), description="Do the work"),
        ToolSpec(name=CHECK_TOOL, kind=CHECK, operation=CHECK_OP, args=("suite",), description="Check the work"),
        ToolSpec(name=DONE_TOOL, kind=DONE, operation=DONE_OP, description="Submit for review"),
    ]


def _facade(owner=None, book=None, ledger=None, roles=None):
    owner = owner if owner is not None else FakeOwner()
    book = book if book is not None else TokenBook()
    ledger = ledger if ledger is not None else FeedbackLedger()
    roles = roles if roles is not None else {ROLE: (TASK_TOOL, CHECK_TOOL, DONE_TOOL)}
    facade = ToolFacade(_tools(), roles, owner, book, ledger)
    return facade, book, ledger, owner


def test_token_scoped_to_assignment():
    facade, book, _ledger, owner = _facade()
    t1 = book.issue("a1", ROLE)
    t2 = book.issue("a2", ROLE)

    smuggled = facade.call(t1, TASK_TOOL, {"assignment": "a2", "title": "x"})
    assert smuggled["ok"] is False and smuggled["error"] == "bad_args"
    not_json = facade.call(t1, TASK_TOOL, {"title": object()})
    assert not_json["ok"] is False and not_json["error"] == "bad_args"
    assert owner.calls == []

    reply = facade.call(t1, TASK_TOOL, {"title": "x"})
    assert reply["ok"] is True and reply["kind"] == "task"
    assert owner.calls[-1]["assignment"] == "a1"

    facade.call(t2, TASK_TOOL, {"title": "y"})
    assert owner.calls[-1]["assignment"] == "a2"

    book.issue("a1", ROLE)
    old = facade.call(t1, TASK_TOOL, {"title": "z"})
    assert old == {"ok": False, "error": "unauthorized", "detail": "unknown token"}

    book.revoke("a2")
    assert facade.call(t2, TASK_TOOL, {"title": "z"})["error"] == "unauthorized"

    for forged in ("forged-token", "", None, 42):
        assert facade.call(forged, TASK_TOOL, {"title": "z"})["error"] == "unauthorized"

    assert book.live() == frozenset({"a1"})
    assert t1 not in repr(book)
    assert t2 not in repr(book)
    assert t1 not in repr(vars(book))


def test_worker_check_never_counts_as_acceptance():
    facade, book, ledger, owner = _facade()
    token = book.issue("a1", ROLE)
    acceptance = Acceptance(ledger)

    reply = facade.call(token, CHECK_TOOL, {"suite": "unit"})
    assert reply["ok"] is True and reply["kind"] == "check"
    assert reply["feedback"] is True and reply["accepted"] is False
    assert "accepted" not in reply["result"]
    assert "acceptance" not in reply["result"]
    assert owner.calls[-1]["feedback"] is True

    [entry] = ledger.entries("a1")
    assert entry["kind"] == "feedback"
    assert entry["counts_as_acceptance"] is False

    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c1", {"run_id": "run-1", "commit": "c1", "ok": True})
    assert acceptance.accepted("a1", "c1") is False

    acceptance.record("a1", "c1", {"run_id": "run-9", "commit": "c1", "ok": True})
    assert acceptance.accepted("a1", "c1") is True
    assert acceptance.accepted("a1", "c2") is False

    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c2", {"run_id": "run-10", "commit": "c1", "ok": True})
    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c2", {"run_id": "run-11", "commit": "c2", "ok": False})
    assert acceptance.accepted("a1", "c2") is False

    done = facade.call(token, DONE_TOOL, {})
    assert done["ok"] is True and done["kind"] == "done"
    assert done["submitted"] is True and done["accepted"] is False
    assert "accepted" not in done["result"]
    assert "counts_as_acceptance" not in done["result"]

    other = book.issue("a3", ROLE)
    facade.call(other, DONE_TOOL, {})
    assert acceptance.accepted("a3", "c1") is False


def test_role_limits_tools():
    facade, book, _ledger, owner = _facade(roles={"limited": (TASK_TOOL,)})
    token = book.issue("a1", "limited")

    assert facade.listing(token) == [
        {"name": TASK_TOOL, "kind": TASK, "description": "Do the work", "args": ["title"]}
    ]
    assert facade.call(token, CHECK_TOOL, {"suite": "unit"})["error"] == "forbidden"
    assert facade.call(token, DONE_TOOL, {})["error"] == "forbidden"
    assert facade.call(token, "no_such_tool", {})["error"] == "forbidden"
    assert owner.calls == []
    assert facade.call(token, TASK_TOOL, {"title": "ok"})["ok"] is True

    full, full_book, _, _ = _facade()
    full_token = full_book.issue("a2", ROLE)
    assert [spec["name"] for spec in full.listing(full_token)] == [TASK_TOOL, CHECK_TOOL, DONE_TOOL]

    with pytest.raises(ToolRuleError):
        _facade(roles={ROLE: ("missing_tool",)})


def test_toolspec_rejects_reserved_args():
    for reserved in ("assignment", "token", "role", "feedback", "accepted", "acceptance"):
        with pytest.raises(ToolRuleError):
            ToolSpec(name="t", kind=TASK, operation="op", args=(reserved,))
    with pytest.raises(ToolRuleError):
        ToolSpec(name="t", kind="boss", operation="op")
    with pytest.raises(ToolRuleError):
        ToolSpec(name="Bad Name", kind=TASK, operation="op")
    assert KINDS == (TASK, CHECK, DONE)


def test_owner_failure_is_generic():
    owner = FakeOwner({TASK_OP: RuntimeError("secret-token-xyz")})
    facade, book, _ledger, _ = _facade(owner=owner)
    token = book.issue("a1", ROLE)

    reply = facade.call(token, TASK_TOOL, {"title": "x"})
    assert reply == {"ok": False, "error": "owner_unavailable", "detail": "RuntimeError"}
    assert "secret-token-xyz" not in repr(reply)
    assert token not in repr(reply)


# --- transport: socket server and stdio MCP server

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from herzchen.fleet.tools import FacadeServer, request

TOKEN_ENV = "TOOLS_TEST_TOKEN"
OTHER_ENV = "TOOLS_TEST_OTHER_TOKEN"
SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")


@pytest.fixture
def sock_dir():
    """A short directory under /tmp: pytest's tmp_path is too long for a unix socket path."""

    path = tempfile.mkdtemp(dir="/tmp")
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


def _send_raw(path: str, data: bytes) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(path)
        sock.sendall(data)
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buffer += chunk
    return json.loads(buffer.split(b"\n", 1)[0])


def _child_env(token_env: str, token: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env[token_env] = token
    return env


def _spawn(path: str, token: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "herzchen.fleet.tools.stdio_server", "--socket", path, "--token-env", TOKEN_ENV],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_child_env(TOKEN_ENV, token),
        text=True,
    )


class _Stdio:
    """Drives one stdio child and keeps every stdout line it wrote, for the token-leak check."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.seen: list[str] = []

    def call(self, message: dict) -> dict:
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, "child closed stdout without replying"
        self.seen.append(line)
        return json.loads(line)

    def notify(self, message: dict) -> None:
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def finish(self) -> tuple[str, str]:
        """Close the child's stdin (EOF) and collect what remains of its output."""

        out, err = self.proc.communicate(timeout=10)
        self.seen.append(out)
        return out, err


def _kill_if_running(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


def _tool_payload(reply: dict) -> dict:
    return json.loads(reply["result"]["content"][0]["text"])


def test_socket_serves_list_and_call_by_token(sock_dir):
    facade, book, _ledger, owner = _facade()
    token = book.issue("a1", ROLE)
    path = str(sock_dir / "facade.sock")

    with FacadeServer(facade, path):
        listed = request(path, {"op": "list", "token": token})
        assert listed["ok"] is True
        assert [tool["name"] for tool in listed["tools"]] == [TASK_TOOL, CHECK_TOOL, DONE_TOOL]

        reply = request(path, {"op": "call", "token": token, "tool": TASK_TOOL, "args": {"title": "x"}})
        assert reply["ok"] is True and reply["kind"] == "task"
        assert owner.calls[-1]["assignment"] == "a1"

        forged = request(path, {"op": "list", "token": "forged-token"})
        assert forged["ok"] is False and forged["error"] == "unauthorized"
        assert token not in repr(forged)

        assert _send_raw(path, b"this is not json\n")["error"] == "bad_request"
        assert _send_raw(path, b"[1, 2, 3]\n")["error"] == "bad_request"
        assert _send_raw(path, b'{"op": "dance", "token": "x"}\n')["error"] == "bad_request"

        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not os.path.exists(path)


def test_stdio_mcp_roundtrip(sock_dir):
    facade, book, _ledger, owner = _facade()
    token = book.issue("a1", ROLE)
    path = str(sock_dir / "facade.sock")

    with FacadeServer(facade, path):
        proc = _spawn(path, token)
        child = _Stdio(proc)
        try:
            init = child.call(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}},
                }
            )
            assert init["id"] == 1
            assert init["result"]["protocolVersion"] == "2024-11-05"
            assert init["result"]["capabilities"] == {"tools": {}}
            child.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

            listed = child.call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = listed["result"]["tools"]
            assert [tool["name"] for tool in tools] == [TASK_TOOL, CHECK_TOOL, DONE_TOOL]
            assert tools[0]["inputSchema"] == {
                "type": "object",
                "properties": {"title": {}},
                "additionalProperties": False,
            }

            task = child.call(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": TASK_TOOL, "arguments": {"title": "x"}},
                }
            )
            assert task["result"]["isError"] is False

            check = child.call(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": CHECK_TOOL, "arguments": {"suite": "unit"}},
                }
            )
            assert check["result"]["isError"] is False
            payload = _tool_payload(check)
            assert payload["feedback"] is True and payload["accepted"] is False

            done = child.call(
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": DONE_TOOL, "arguments": {}}}
            )
            assert done["result"]["isError"] is False
            payload = _tool_payload(done)
            assert payload["submitted"] is True and payload["accepted"] is False

            smuggled = child.call(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": TASK_TOOL, "arguments": {"assignment": "a2"}},
                }
            )
            assert smuggled["result"]["isError"] is True

            unknown = child.call({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
            assert unknown["error"]["code"] == -32601

            out, err = child.finish()
            assert proc.returncode == 0
        finally:
            _kill_if_running(proc)

    assert {call["assignment"] for call in owner.calls} == {"a1"}
    assert token not in "".join(child.seen) + err


def test_stdio_server_without_token_refuses(sock_dir):
    _facade_, book, _ledger, _owner = _facade()
    token = book.issue("a1", ROLE)
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop(TOKEN_ENV, None)
    env[OTHER_ENV] = token  # a token under another name must not be read

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "herzchen.fleet.tools.stdio_server",
            "--socket",
            str(sock_dir / "facade.sock"),
            "--token-env",
            TOKEN_ENV,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "token" in result.stderr
    assert token not in result.stderr


def test_two_stdio_servers_two_assignments(sock_dir):
    facade, book, _ledger, owner = _facade()
    token_a1 = book.issue("a1", ROLE)
    token_a2 = book.issue("a2", ROLE)
    path = str(sock_dir / "facade.sock")

    with FacadeServer(facade, path):
        first = subprocess.Popen(
            [sys.executable, "-m", "herzchen.fleet.tools.stdio_server", "--socket", path, "--token-env", TOKEN_ENV],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(TOKEN_ENV, token_a1),
            text=True,
        )
        second = subprocess.Popen(
            [sys.executable, "-m", "herzchen.fleet.tools.stdio_server", "--socket", path, "--token-env", TOKEN_ENV],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(TOKEN_ENV, token_a2),
            text=True,
        )
        try:
            for child in (_Stdio(first), _Stdio(second)):
                reply = child.call(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": TASK_TOOL, "arguments": {"title": "x"}},
                    }
                )
                assert reply["result"]["isError"] is False
                child.finish()
            assert first.returncode == 0 and second.returncode == 0
        finally:
            _kill_if_running(first)
            _kill_if_running(second)

    assert [call["assignment"] for call in owner.calls] == ["a1", "a2"]


# --- hosts: the worker tool pins and the exec allowance

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from herzchen.fleet.hosts import McpGrant, McpServer, TurnSpec, get_host
from herzchen.fleet.hosts.claude import (BUILTIN_TOOLS, PROTECTED_NAMES, WORKER_BUILTIN_TOOLS,
                                         ClaudeBindingError, sandbox_policy, sandbox_wrap)
from herzchen.fleet.hosts.contract import HostContractError
from herzchen.fleet.tools.pins import exec_allow_for, require_sole_server, sole_server_grant

needs_sandbox = pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"),
                                   reason="needs macOS sandbox-exec")


def _grant(command="/usr/bin/true"):
    return sole_server_grant(server="srv", tools=("task", "check", "done"), command=command,
                             token="t0k", token_env="TOK_X", token_env_prefix="TOK_")


def test_policy_without_exec_allow_is_unchanged():
    tail = ''.join('(deny file-write* (subpath ' + json.dumps(str(Path('/w') / name)) + '))'
                   for name in PROTECTED_NAMES)
    expected = ('(version 1)(allow default)(deny file-write*)(deny process-fork)(deny process-exec)'
                '(allow file-write* (subpath "/w"))(allow file-write* (subpath "/s"))'
                '(allow file-write* (literal "/dev/null"))' + tail)
    assert sandbox_policy('/w', '/s') == expected
    assert sandbox_policy('/w', '/s', exec_allow=()) == expected


def test_policy_with_exec_allow_forks_but_execs_only_the_server():
    policy = sandbox_policy('/w', '/s', exec_allow=('/x/server',))
    assert '(allow process-fork)' in policy
    assert '(allow process-exec (literal "/x/server"))' in policy
    assert '(deny process-fork)' not in policy
    assert '(deny process-exec)' in policy


@pytest.mark.parametrize('bad', ['x/server', '/x/\x00s', ''])
def test_exec_allow_entries_must_be_absolute(bad):
    with pytest.raises(ClaudeBindingError):
        sandbox_policy('/w', '/s', exec_allow=(bad,))


def test_exec_allow_has_no_effect_when_subprocesses_are_allowed():
    assert (sandbox_policy('/w', '/s', allow_subprocesses=True, exec_allow=('/x/server',))
            == sandbox_policy('/w', '/s', allow_subprocesses=True))


def test_claude_worker_argv_pins_tools_and_one_server(tmp_path):
    ws, state = str(tmp_path / "w"), str(tmp_path / "st")
    os.mkdir(ws)
    os.mkdir(state)
    spec = TurnSpec(executable="/L/claude", workspace=ws, prompt="p", model="claude-sonnet-5-5",
                    reasoning="high", profile="workspace-write", mcp=_grant(),
                    options={"tools": WORKER_BUILTIN_TOOLS, "allowed_tools": BUILTIN_TOOLS, "state_root": state})
    plan = get_host("claude-code").launch(spec)
    argv = list(plan.argv)
    assert argv[argv.index("--tools") + 1] == "Edit,Glob,Grep,Read,Write"
    assert "--strict-mcp-config" in argv
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    assert set(config["mcpServers"]) == {"srv"}
    allowed = argv[argv.index("--allowedTools") + 1:]
    for name in ("mcp__srv__task", "mcp__srv__check", "mcp__srv__done", "Edit(/%s/**)" % ws):
        assert name in allowed
    assert not any("t0k" in part for part in argv)
    assert plan.env == {"TOK_X": "t0k"}


def test_codex_worker_argv_pins_one_server(tmp_path):
    ws = str(tmp_path / "w")
    os.mkdir(ws)
    spec = TurnSpec(executable="/L/codex", workspace=ws, prompt="p", model="gpt-5.6-luna", reasoning="high",
                    profile="workspace-write", mcp=_grant())
    plan = get_host("codex").launch(spec)
    argv = list(plan.argv)
    assert "--ignore-user-config" in argv
    mcp_parts = [part for part in argv if part.startswith("mcp_servers.")]
    assert mcp_parts and all(part.startswith("mcp_servers.srv.") for part in mcp_parts)
    enabled = [part for part in mcp_parts if part.startswith("mcp_servers.srv.enabled_tools=")]
    assert len(enabled) == 1
    assert json.loads(enabled[0].split("=", 1)[1]) == ["task", "check", "done"]
    assert not any("t0k" in part for part in argv)


def test_sole_server_grant_needs_a_tool_allowlist():
    with pytest.raises(HostContractError):
        sole_server_grant(server="srv", tools=(), command="/usr/bin/true", token="t0k",
                          token_env="TOK_X", token_env_prefix="TOK_")


def test_require_sole_server_and_exec_allow_for():
    grant = _grant()
    require_sole_server(grant, "srv")
    with pytest.raises(HostContractError):
        require_sole_server(McpGrant(), "srv")
    two = McpGrant(servers=(McpServer(name="srv", command="/usr/bin/true", tools=("task",)),
                            McpServer(name="other", command="/usr/bin/true", tools=("task",))))
    with pytest.raises(HostContractError):
        require_sole_server(two, "srv")
    with pytest.raises(HostContractError):
        require_sole_server(grant, "other")
    assert exec_allow_for(grant) == (os.path.realpath("/usr/bin/true"),)
    assert exec_allow_for(two) == (os.path.realpath("/usr/bin/true"),) * 2


def _run_in_fence(policy, ws, script):
    argv = sandbox_wrap(policy, ws, ["/bin/bash", "-c", script])
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


@needs_sandbox
def test_sandbox_lets_only_the_mcp_command_run(tmp_path):
    ws, state = str(tmp_path / "w"), str(tmp_path / "st")
    os.mkdir(ws)
    os.mkdir(state)
    script = "/bin/echo child-ran && echo OK || echo BLOCKED"
    allowed = _run_in_fence(sandbox_policy(ws, state, exec_allow=("/bin/echo",)), ws, script)
    assert "child-ran" in allowed.stdout and "OK" in allowed.stdout.split()
    blocked = _run_in_fence(sandbox_policy(ws, state, exec_allow=("/usr/bin/true",)), ws, script)
    assert "child-ran" not in blocked.stdout and "BLOCKED" in blocked.stdout.split()
    none = _run_in_fence(sandbox_policy(ws, state), ws, script)
    assert "child-ran" not in none.stdout and "OK" not in none.stdout.split()


# --- otto side: role table and the fake harness

from herzchen.fleet.hosts import TurnSpec, get_host
from herzchen.fleet.tools import AllowlistedPort
from herzchen.fleet.tools.pins import exec_allow_for, require_sole_server, sole_server_grant
from otto.agents.claude_adapter import ROLE_PROFILES
from otto.agents.claude_cli import (MANAGER_TOOLS, OWNER_OPERATIONS, TOOL_ENV_PREFIX, TOOL_SERVER, TOOL_SPECS,
                                    WORKER_TOOLS)

OTTO_CALLS = ("task", "check", "done")
OTTO_OWNER_REPLIES = {
    "effective-context": {"title": "Ship the thing", "context": "notes"},
    "worker-check": {"run_id": "run-1", "commit": "c1", "ok": True},
    "worker-done": {"submitted": True},
}
OTTO_ROLES = {role: profile["calls"] for role, profile in ROLE_PROFILES.items()}


def _expand(value, env):
    """A config value written as ${NAME} is read from the environment the plan hands the child."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return env[value[2:-1]]
    return value


def _mcp_server_from_plan(plan, kind):
    """The one MCP server command, its args and its child environment, read the way each CLI reads its flags."""
    argv = list(plan.argv)
    if kind == "claude-code":
        config = json.loads(argv[argv.index("--mcp-config") + 1])
        server = config["mcpServers"][TOOL_SERVER]
        child_env = {name: _expand(value, plan.env) for name, value in server.get("env", {}).items()}
        return server["command"], list(server["args"]), child_env
    prefix = "mcp_servers.%s." % TOOL_SERVER
    fields = {}
    for index, part in enumerate(argv[:-1]):
        if part == "-c" and argv[index + 1].startswith(prefix):
            key, _, raw = argv[index + 1].partition("=")
            fields[key[len(prefix):]] = json.loads(raw)
    child_env = {name: plan.env[name] for name in fields["env_vars"]}
    return fields["command"], list(fields["args"]), child_env


def _harness_env(extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update(extra)
    return env


@pytest.mark.parametrize("kind", ["claude-code", "codex"])
def test_fake_harness_uses_tools(kind, tmp_path, sock_dir):
    ws, state = tmp_path / "w", tmp_path / "st"
    ws.mkdir()
    state.mkdir()
    env_name = TOOL_ENV_PREFIX + "A1"
    path = str(sock_dir / "facade.sock")

    owner_port = FakeOwner(dict(OTTO_OWNER_REPLIES))
    owner = AllowlistedPort(owner_port, OWNER_OPERATIONS + ("worker-check", "worker-done"))
    book, ledger = TokenBook(), FeedbackLedger()
    facade = ToolFacade(TOOL_SPECS, OTTO_ROLES, owner, book, ledger)
    token = book.issue("a1", "worker")
    grant = sole_server_grant(
        server=TOOL_SERVER, tools=tuple(spec.name for spec in TOOL_SPECS), command=sys.executable,
        args=("-m", "herzchen.fleet.tools.stdio_server", "--socket", path, "--token-env", env_name),
        token=token, token_env=env_name, token_env_prefix=TOOL_ENV_PREFIX)
    require_sole_server(grant, TOOL_SERVER)

    if kind == "claude-code":
        options = {"tools": WORKER_TOOLS, "allowed_tools": MANAGER_TOOLS,
                   "max_turns": ROLE_PROFILES["worker"]["max_turns"], "state_root": str(state),
                   "exec_allow": exec_allow_for(grant)}
        spec = TurnSpec(executable="/L/claude", workspace=str(ws), prompt="p", model="claude-sonnet-5-5",
                        reasoning="high", profile="workspace-write", mcp=grant, options=options)
    else:
        spec = TurnSpec(executable="/L/codex", workspace=str(ws), prompt="p", model="gpt-5.6-luna",
                        reasoning="high", profile="workspace-write", mcp=grant)
    host = get_host(kind)
    plan = host.launch(spec, fence=host.make_fence(spec))

    # (a) the argv pins the surface; (b) the token is in no argv element
    argv = list(plan.argv)
    if kind == "claude-code":
        assert argv[argv.index("--tools") + 1] == "Edit,Glob,Grep,Read,Write"
        assert "--strict-mcp-config" in argv
        config = json.loads(argv[argv.index("--mcp-config") + 1])
        assert list(config["mcpServers"]) == [TOOL_SERVER]
        allowed = argv[argv.index("--allowedTools") + 1:]
        for name in OTTO_CALLS:
            assert "mcp__%s__%s" % (TOOL_SERVER, name) in allowed
        # every file tool is pinned to the workspace; the OS fence confines writes only
        for name in WORKER_TOOLS:
            assert "%s(/%s/**)" % (name, ws) in allowed
        # a command-free worker with its one granted server runs confined: dontAsk, no safe mode
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "--safe-mode" not in argv and "--dangerously-skip-permissions" not in argv
    else:
        assert "--ignore-user-config" in argv
        mcp_parts = [part for part in argv if part.startswith("mcp_servers.")]
        assert mcp_parts and all(part.startswith("mcp_servers.%s." % TOOL_SERVER) for part in mcp_parts)
        enabled = [json.loads(part.split("=", 1)[1]) for part in mcp_parts
                   if part.startswith("mcp_servers.%s.enabled_tools=" % TOOL_SERVER)]
        assert enabled == [list(OTTO_CALLS)]
    assert not any(token in part for part in argv)

    # the fake harness spawns the server command the plan names, with the plan's token in its environment
    command, args, child_env = _mcp_server_from_plan(plan, kind)
    with FacadeServer(facade, path):
        proc = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=_harness_env(child_env), text=True)
        child = _Stdio(proc)
        try:
            init = child.call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}}})
            assert init["result"]["protocolVersion"] == "2024-11-05"
            child.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

            # (c) the tools the harness sees are exactly task, check, done
            listed = child.call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert [tool["name"] for tool in listed["result"]["tools"]] == list(OTTO_CALLS)

            replies = {}
            for msg_id, name in enumerate(OTTO_CALLS, start=3):
                reply = child.call({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                                    "params": {"name": name, "arguments": {}}})
                assert reply["result"]["isError"] is False
                replies[name] = _tool_payload(reply)
            out, err = child.finish()
            assert proc.returncode == 0
        finally:
            _kill_if_running(proc)

    # (d) check is feedback, (e) done is submitted and never accepted
    assert replies["task"]["ok"] is True
    assert replies["check"]["feedback"] is True and replies["check"]["accepted"] is False
    assert replies["done"]["submitted"] is True and replies["done"]["accepted"] is False
    assert token not in "".join(child.seen) + err

    # (f) the owner saw every call, for assignment a1 only
    assert [call["operation"] for call in owner_port.calls] == ["effective-context", "worker-check", "worker-done"]
    assert {call["assignment"] for call in owner_port.calls} == {"a1"}

    # (g) no acceptance follows from the worker's calls; the owner's own run record is refused
    acceptance = Acceptance(ledger)
    assert acceptance.accepted("a1", "c1") is False
    assert acceptance.accepted("a1", "c2") is False
    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c1", {"run_id": "run-1", "commit": "c1", "ok": True})
    assert acceptance.accepted("a1", "c1") is False


def test_role_table_limits_calls():
    assert ROLE_PROFILES["worker"]["calls"] == ("task", "check", "done")
    assert ROLE_PROFILES["manager"]["calls"] == ()
    assert WORKER_TOOLS == ("Edit", "Glob", "Grep", "Read", "Write")
    assert "Bash" not in WORKER_TOOLS

    names = {spec.name for spec in TOOL_SPECS}
    for role, profile in ROLE_PROFILES.items():
        assert set(profile["calls"]) <= names, role

    owner = FakeOwner(dict(OTTO_OWNER_REPLIES))
    book, ledger = TokenBook(), FeedbackLedger()
    facade = ToolFacade(TOOL_SPECS, OTTO_ROLES, owner, book, ledger)
    for role in ("manager", "stranger"):
        token = book.issue(role + "-assignment", role)
        assert facade.listing(token) == []
        for name in OTTO_CALLS:
            assert facade.call(token, name, {})["error"] == "forbidden"
    assert owner.calls == []


def test_unlisted_owner_operations_are_refused():
    owner_port = FakeOwner(dict(OTTO_OWNER_REPLIES))
    owner = AllowlistedPort(owner_port, OWNER_OPERATIONS)
    book, ledger = TokenBook(), FeedbackLedger()
    facade = ToolFacade(TOOL_SPECS, OTTO_ROLES, owner, book, ledger)
    token = book.issue("a1", "worker")

    task = facade.call(token, "task", {})
    assert task["ok"] is True and task["kind"] == "task"

    check = facade.call(token, "check", {})
    assert check["ok"] is False and check["error"] == "owner_unavailable"
    done = facade.call(token, "done", {"summary": "x"})
    assert done["ok"] is False and done["error"] == "owner_unavailable"

    assert [call["operation"] for call in owner_port.calls] == ["effective-context"]
    assert ledger.entries("a1") == []


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"),
                    reason="needs macOS sandbox-exec")
def test_mac_write_scope_pins_the_server_exec(tmp_path):
    from otto.agents.claude_cli import MacWriteScope

    ws, state = tmp_path / "w", tmp_path / "st"
    ws.mkdir()
    state.mkdir()
    granted = MacWriteScope(str(ws), str(state), authentication="isolated", exec_allow=(sys.executable,))
    # The interpreter itself, plus (for a framework Python stub such as Homebrew's) its own
    # Python.app re-exec target, spelled out here rather than computed by the code under test.
    real = os.path.realpath(sys.executable)
    expected = [real]
    head, name = os.path.split(real)
    version = os.path.dirname(head)
    if (os.path.basename(head) == "bin" and name.startswith("python")
            and os.path.basename(os.path.dirname(version)) == "Versions"):
        app = os.path.realpath(os.path.join(version, "Resources", "Python.app", "Contents", "MacOS", "Python"))
        if os.path.isfile(app):
            expected.append(app)
    assert granted.pin["exec_allow"] == expected
    assert "(allow process-fork)" in granted.policy

    plain = MacWriteScope(str(ws), str(state), authentication="isolated")
    assert "(deny process-fork)" in plain.policy
    assert "exec_allow" not in plain.pin


# --- confined worker: the launch shape the live probe established

def _dirs(tmp_path):
    ws, state = str(tmp_path / "w"), str(tmp_path / "st")
    os.mkdir(ws)
    os.mkdir(state)
    return ws, state


def _otto_grant():
    """The worker's one granted server, named the way the adapter requires it."""
    return sole_server_grant(server=TOOL_SERVER, tools=tuple(spec.name for spec in TOOL_SPECS),
                             command=sys.executable, token="t0k", token_env=TOOL_ENV_PREFIX + "A1",
                             token_env_prefix=TOOL_ENV_PREFIX)


def _confined_spec(ws, state, *, mcp=None, tools=WORKER_TOOLS, initializer=False, **options):
    """A claude-code turn built the way the harness builds one; no mcp means an MCP-less turn."""
    options = {"state_root": state, **options}
    if not initializer:
        options.setdefault("tools", tools)
        options.setdefault("allowed_tools", MANAGER_TOOLS)
    return TurnSpec(executable="/L/claude", workspace=ws, prompt="p", model="claude-sonnet-5-5",
                    reasoning="high", profile="workspace-write", initializer=initializer,
                    mcp=McpGrant() if mcp is None else mcp, options=options)


def test_confined_worker_launch_flags(tmp_path):
    ws, state = _dirs(tmp_path)
    host = get_host("claude-code")

    # a command-free worker with its one granted server runs under dontAsk, without safe mode
    argv = list(host.launch(_confined_spec(ws, state, mcp=_otto_grant())).argv)
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--safe-mode" not in argv and "--dangerously-skip-permissions" not in argv
    allowed = argv[argv.index("--allowedTools") + 1:]
    for name in WORKER_TOOLS:
        assert "%s(/%s/**)" % (name, ws) in allowed

    # the same worker with no MCP server keeps the old shape: safe mode, bypass, single-slash scopes
    argv = list(host.launch(_confined_spec(ws, state)).argv)
    assert "--safe-mode" in argv and "--dangerously-skip-permissions" in argv
    assert "--permission-mode" not in argv
    allowed = argv[argv.index("--allowedTools") + 1:]
    for name in WORKER_TOOLS:
        assert "%s(%s/**)" % (name, ws) in allowed
    assert "Glob" not in allowed and "Grep" not in allowed

    # a manager runs Bash: it keeps safe mode, bypass and the bare Glob/Grep entries
    manager = _confined_spec(ws, state, tools=MANAGER_TOOLS, allow_subprocesses=True)
    argv = list(host.launch(manager).argv)
    assert "--safe-mode" in argv and "--dangerously-skip-permissions" in argv
    assert "--permission-mode" not in argv
    allowed = argv[argv.index("--allowedTools") + 1:]
    assert "Glob" in allowed and "Grep" in allowed

    # an initializer is inert and keeps safe mode and bypass even when a grant is present
    argv = list(host.launch(_confined_spec(ws, state, mcp=_otto_grant(), initializer=True)).argv)
    assert "--safe-mode" in argv and "--dangerously-skip-permissions" in argv
    assert "--permission-mode" not in argv


def test_parser_expects_the_launched_permission_mode(tmp_path):
    ws, state = _dirs(tmp_path)
    host = get_host("claude-code")
    confined = _confined_spec(ws, state, mcp=_otto_grant())
    bare = _confined_spec(ws, state)

    def init_frame(permission_mode, tools, servers):
        return json.dumps({"type": "system", "subtype": "init", "session_id": "s-1", "cwd": ws,
                           "model": "claude-sonnet-5-5", "permissionMode": permission_mode, "tools": tools,
                           "mcp_servers": servers, "plugins": [], "skills": [], "slash_commands": [],
                           }).encode()

    confined_tools = sorted([*WORKER_TOOLS, "mcp__otto__check", "mcp__otto__done", "mcp__otto__task"])
    connected = [{"name": "otto", "status": "connected"}]
    accepted = host.parser(confined)
    accepted.feed(init_frame("dontAsk", confined_tools, connected))
    assert accepted.stream.session == "s-1" and accepted.stream.init is not None
    with pytest.raises(ClaudeBindingError):
        host.parser(confined).feed(init_frame("bypassPermissions", confined_tools, connected))

    accepted = host.parser(bare)
    accepted.feed(init_frame("bypassPermissions", sorted(WORKER_TOOLS), []))
    assert accepted.stream.session == "s-1" and accepted.stream.init is not None
    with pytest.raises(ClaudeBindingError):
        host.parser(bare).feed(init_frame("dontAsk", sorted(WORKER_TOOLS), []))


def test_transport_drops_safe_mode_env_only_with_a_grant(tmp_path):
    from otto.agents.claude_cli import VERSION, ClaudeCliTransport, LauncherPin, MacWriteScope
    ws, state = _dirs(tmp_path)
    pin = LauncherPin("/x", "/x", "0", VERSION)
    scope = MacWriteScope(ws, state, authentication="isolated")
    granted = ClaudeCliTransport(pin, scope, model="claude-sonnet-5-5", reasoning="high", mcp=_otto_grant())
    assert "CLAUDE_CODE_SAFE_MODE" not in granted.environment()
    plain = ClaudeCliTransport(pin, scope, model="claude-sonnet-5-5", reasoning="high")
    assert plain.environment()["CLAUDE_CODE_SAFE_MODE"] == "1"


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"),
                    reason="needs macOS sandbox-exec")
def test_adapter_pins_follow_the_permission_mode(tmp_path):
    from otto.agents.claude_adapter import ClaudeWorkerAdapter
    from otto.agents.claude_cli import VERSION, LauncherPin
    ws, state = _dirs(tmp_path)
    pin = LauncherPin("/x", "/x", "0", VERSION)
    common = dict(owner="o", source=ws, worktree=ws, launcher_pin=pin, state_root=state,
                  requested_model="claude-sonnet-5-5", authentication="isolated")
    granted = ClaudeWorkerAdapter(**common, worker_mcp=_otto_grant())
    assert granted.pins()["permission_mode"] == "dontAsk"
    bare = ClaudeWorkerAdapter(**common)
    assert bare.pins()["permission_mode"] == "bypassPermissions"

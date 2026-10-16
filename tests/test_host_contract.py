"""HOSTKIT: one host contract; adding an agent harness is one implementation.

Three groups:
  * the named checks: fake_harness_runs_full_loop, unknown_host_refused, one_codex_binding;
  * XHARD flag parity: the launch flags (sandbox, session, workspace) each host emitted BEFORE it
    moved behind the contract (recorded from canon/main 51fcfb9 by driving the pre-move code with a fake process factory) are
    asserted at BOTH layers -- the contract and the real runtime that consumes it;
  * the contract's MCP/token, model-slot and parser surfaces.

``herzchen.fleet.hosts`` is imported lazily so the runtime-parity tests still run (and pass) against
canon, where the package does not exist, proving the goldens match the pre-move code.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def hosts():
    return importlib.import_module("herzchen.fleet.hosts")


# ---------------------------------------------------------------------------
# Recorded launch flags (canon/main, before the move). {WS} and {ST} stand for the temp workspace and state-root paths.
# ---------------------------------------------------------------------------
CODEX_COMMON = ["/L/codex", "exec", "-C", "{WS}", "-m", "M", "-c", "model_reasoning_effort=high",
                "-c", 'approval_policy="never"', "--ignore-user-config", "--ignore-rules", "--json"]
CODEX_SOCKET_OVERRIDES = [
    "-c", 'default_permissions="otto-native-caller"',
    "-c", "features.network_proxy=true",
    "-c", 'permissions.otto-native-caller.extends=":workspace"',
    "-c", "permissions.otto-native-caller.network.enabled=true",
    "-c", 'permissions.otto-native-caller.network.mode="limited"',
    "-c", "permissions.otto-native-caller.network.domains={}",
    "-c", 'permissions.otto-native-caller.network.unix_sockets={"{WS}/s.sock"="allow"}',
    "-c", 'permissions.otto-native-caller.workspace_roots={"{WS}"=true,"{WS}/extra"=true}',
]
CODEX_GOLDEN = {
    "invoke.read-only": CODEX_COMMON + ["-s", "read-only", "-"],
    "invoke.workspace-write": CODEX_COMMON + ["-s", "workspace-write", "--add-dir", "{WS}/extra", "-"],
    "resume.read-only": CODEX_COMMON + ["-s", "read-only", "resume", "sess-1", "-"],
    "resume.workspace-write": CODEX_COMMON + ["-s", "workspace-write", "--add-dir", "{WS}/extra",
                                              "resume", "sess-1", "-"],
    "resume.workspace-write.receipt": CODEX_COMMON + ["-s", "workspace-write", "resume", "sess-1",
                                                      "-o", "{WS}/r.json", "-"],
    "resume.workspace-write.socket": CODEX_COMMON + CODEX_SOCKET_OVERRIDES + ["resume", "sess-1", "-"],
}

CLAUDE_HEAD = ["/L/claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--replay-user-messages", "--safe-mode", "--setting-sources", "", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--dangerously-skip-permissions"]
CLAUDE_GOLDEN = {
    "worker.initializer": CLAUDE_HEAD + ["--tools", "", "--model", "claude-sonnet-5-5", "--effort", "high",
                                         "--max-turns", "1"],
    "worker.fresh": CLAUDE_HEAD + ["--tools", "Edit,Glob,Grep,Read,Write", "--model", "claude-sonnet-5-5",
                                   "--effort", "high", "--max-turns", "8", "--allowedTools", "Edit({WS}/**)",
                                   "Glob({WS}/**)", "Grep({WS}/**)", "Read({WS}/**)", "Write({WS}/**)"],
    "worker.resume": CLAUDE_HEAD + ["--tools", "Edit,Glob,Grep,Read,Write", "--model", "claude-sonnet-5-5",
                                    "--effort", "high", "--max-turns", "8", "--allowedTools", "Edit({WS}/**)",
                                    "Glob({WS}/**)", "Grep({WS}/**)", "Read({WS}/**)", "Write({WS}/**)",
                                    "--resume", "native-1"],
    "manager.resume": CLAUDE_HEAD + ["--tools", "Bash,Edit,Glob,Grep,Read,Write", "--model", "claude-sonnet-5-5",
                                     "--effort", "high", "--max-turns", "40", "--allowedTools", "Bash",
                                     "Edit({WS}/**)", "Glob", "Grep", "Read({WS}/**)", "Write({WS}/**)",
                                     "--resume", "native-1"],
}
_POLICY_ROOTS = ('(allow file-write* (subpath "{WS}"))(allow file-write* (subpath "{ST}"))')
_POLICY_TAIL = ('(allow file-write* (literal "/dev/null"))(deny file-write* (subpath "{WS}/.git"))'
                '(deny file-write* (subpath "{WS}/.agents"))(deny file-write* (subpath "{WS}/.codex"))'
                '(deny file-write* (subpath "{WS}/.aws"))(deny file-write* (subpath "{WS}/.claude"))')
CLAUDE_FENCE_GOLDEN = {
    # The OS write fence: deny all writes, then allow workspace + state root; no child processes for a leaf.
    "worker": "(version 1)(allow default)(deny file-write*)(deny process-fork)(deny process-exec)"
              + _POLICY_ROOTS + _POLICY_TAIL,
    # A manager runs commands, so only process creation is relaxed; its extra root is writable.
    "manager": "(version 1)(allow default)(deny file-write*)" + _POLICY_ROOTS
               + '(allow file-write* (subpath "{WS}/extra"))' + _POLICY_TAIL,
}
EXEC_RULE = '(allow process-exec (literal "/bin/x"))'
INITIALIZER_RULE = '(deny file-write* (subpath "{WS}"))'

MODELS_GOLDEN = {
    "codex": {"normal": ("gpt-5.6-luna", "high"), "xhard": ("gpt-5.6-sol", "high")},
    "claude-code": {"normal": ("claude-haiku-5-5", "high"), "xhard": ("claude-sonnet-5-5", "high")},
}


class Stop(OSError):
    """Raised by the fake process factory after the command is captured; nothing is launched."""


def otto_tools():
    """Otto's own Claude tool policy. The fleet package no longer carries it; the caller supplies it."""
    from otto.agents import claude_cli
    return claude_cli.WORKER_TOOLS, claude_cli.MANAGER_TOOLS


def _canon(argv, **paths):
    out = list(argv)
    for key, value in paths.items():
        out = [a.replace(value, "{%s}" % key) for a in out]
    return out


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hostkit-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root = str(base / "w")
        os.mkdir(self.root)
        self.extra = str(Path(self.root, "extra"))
        os.mkdir(self.extra)
        self.state = str(base / "st")          # the host-owned state root is never inside the workspace
        os.mkdir(self.state)
        self.sock = str(Path(self.root, "s.sock"))

    def flat(self, argv):
        return _canon(argv, ST=self.state, WS=self.root)


# ---------------------------------------------------------------------------
# XHARD: runtime-level flag parity (passes on canon: proves the goldens are the pre-move flags)
# ---------------------------------------------------------------------------
class CodexRuntimeFlags(Workspace):
    def command(self, operation, profile, **kw):
        from herzchen.adapters import host as codex_host
        from herzchen.contracts import HostIdentity, HostOperation, HostRequest, ResourceRef
        captured = {}

        def popen(command, **kwargs):
            captured["command"] = list(command)
            captured["cwd"] = kwargs.get("cwd")
            raise Stop("stop")

        binding = codex_host.CodexCliBinding(self.root, launcher="/L/codex", model="M", reasoning="high",
                                             prompt="p", **kw)
        op = HostOperation(operation)
        session = "sess-1" if operation == "resume" else None
        request = HostRequest(op, HostIdentity("worker", session), ResourceRef("o", "work.task", "t"), profile)
        with mock.patch.object(codex_host.subprocess, "Popen", popen):
            binding.execute(request)
        self.assertEqual(captured["cwd"], self.root)
        return self.flat(captured["command"])

    def test_every_recorded_codex_launch_is_unchanged_in_the_real_binding(self):
        cases = {
            "invoke.read-only": ("invoke", "read-only", {}),
            "invoke.workspace-write": ("invoke", "workspace-write", {"writable_roots": (self.extra,)}),
            "resume.read-only": ("resume", "read-only", {}),
            "resume.workspace-write": ("resume", "workspace-write", {"writable_roots": (self.extra,)}),
            "resume.workspace-write.receipt": ("resume", "workspace-write",
                                               {"native_receipt_path": self.root + "/r.json"}),
            "resume.workspace-write.socket": ("resume", "workspace-write", dict(
                writable_roots=(self.extra,), native_caller_socket=self.sock,
                native_caller_profile="otto-native-caller",
                recipient_authorizer=lambda r: None, native_process_observer=lambda p, a: (lambda: None))),
        }
        self.assertEqual(set(cases), set(CODEX_GOLDEN))
        for name, (operation, profile, kw) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.command(operation, profile, **kw), CODEX_GOLDEN[name])


class ClaudeRuntimeFlags(Workspace):
    def transport(self, **kw):
        from otto.agents import claude_cli as cc
        root, state = self.root, self.state

        class Scope:
            identity = cc.MacWriteScope.identity
            workspace, state_root, allow_subprocesses = root, state, True
            pin = {"identity": identity}

            def preflight(self):
                return {"verified": True}

            def wrap(self, command, **options):
                return ["WRAP:init=%s" % options.get("initializer", False)] + list(command)

        class Pin:
            realpath = "/L/claude"

            def verify(self):
                pass

        captured = {}

        def factory(command, **kwargs):
            captured["command"] = list(command)
            raise Stop("stop")

        t = cc.ClaudeCliTransport(Pin(), Scope(), model="claude-sonnet-5-5", reasoning="high",
                                  process_factory=factory, authentication="existing-user", **kw)
        return cc, t, captured

    def command(self, tools, session=None, initializer=False, max_turns=8):
        cc, t, captured = self.transport(tools=tools, max_turns=max_turns)
        with self.assertRaises(Stop):
            t.run("prompt", session=session, initializer=initializer)
        wrap, *command = captured["command"]
        self.assertEqual(wrap, "WRAP:init=%s" % initializer)
        return self.flat(command)

    def test_every_recorded_claude_launch_is_unchanged_in_the_real_transport(self):
        from otto.agents import claude_cli as cc
        self.assertEqual(self.command(cc.WORKER_TOOLS, initializer=True), CLAUDE_GOLDEN["worker.initializer"])
        self.assertEqual(self.command(cc.WORKER_TOOLS), CLAUDE_GOLDEN["worker.fresh"])
        self.assertEqual(self.command(cc.WORKER_TOOLS, session="native-1"), CLAUDE_GOLDEN["worker.resume"])
        self.assertEqual(self.command(cc.MANAGER_TOOLS, session="native-1", max_turns=40),
                         CLAUDE_GOLDEN["manager.resume"])

    def test_the_real_os_write_fence_is_unchanged(self):
        from otto.agents.claude_cli import MacWriteScope
        worker = MacWriteScope(self.root, self.state, authentication="isolated")
        manager = MacWriteScope(self.root, self.state, authentication="isolated", allow_subprocesses=True,
                                extra_write_roots=(self.extra,))
        self.assertEqual(self.flat([worker.policy]), [self._policy("worker")])
        self.assertEqual(self.flat([manager.policy]), [self._policy("manager")])
        self.assertEqual(self.flat(worker.wrap(["/bin/x", "a"]))[:2], ["/usr/bin/sandbox-exec", "-p"])
        self.assertEqual(self.flat([worker.wrap(["/bin/x", "a"])[2]]), [self._policy("worker") + EXEC_RULE])
        self.assertEqual(self.flat([worker.wrap(["/bin/x"], initializer=True)[2]]),
                         [self._policy("worker") + EXEC_RULE + INITIALIZER_RULE])

    @staticmethod
    def _policy(name):
        return CLAUDE_FENCE_GOLDEN[name]


# ---------------------------------------------------------------------------
# XHARD: the same flags, now asserted through the contract
# ---------------------------------------------------------------------------
class ContractFlags(Workspace):
    def codex_plan(self, session, profile, **options):
        H = hosts()
        spec = H.TurnSpec(executable="/L/codex", workspace=self.root, prompt="p", model="M", reasoning="high",
                          session=session, profile=profile,
                          writable_roots=options.pop("writable_roots", ()), options=options)
        return H.get_host("codex").launch(spec)

    def test_codex_contract_emits_exactly_the_recorded_flags(self):
        got = {
            "invoke.read-only": self.codex_plan(None, "read-only"),
            "invoke.workspace-write": self.codex_plan(None, "workspace-write", writable_roots=(self.extra,)),
            "resume.read-only": self.codex_plan("sess-1", "read-only"),
            "resume.workspace-write": self.codex_plan("sess-1", "workspace-write", writable_roots=(self.extra,)),
            "resume.workspace-write.receipt": self.codex_plan("sess-1", "workspace-write",
                                                              receipt_path=self.root + "/r.json"),
            "resume.workspace-write.socket": self.codex_plan(
                "sess-1", "workspace-write", writable_roots=(self.extra,), native_caller_socket=self.sock,
                native_caller_profile="otto-native-caller"),
        }
        self.assertEqual(set(got), set(CODEX_GOLDEN))
        for name, plan in got.items():
            with self.subTest(name):
                self.assertEqual(self.flat(plan.command()), CODEX_GOLDEN[name])
                self.assertEqual(plan.cwd, self.root)
                self.assertEqual(plan.session, "sess-1" if name.startswith("resume") else None)

    def test_codex_fence_is_the_native_sandbox_flag_not_an_os_wrapper(self):
        plan = self.codex_plan(None, "workspace-write", writable_roots=(self.extra,))
        self.assertEqual(plan.fence.kind, "codex-sandbox")
        self.assertEqual(tuple(plan.command()), tuple(plan.argv))      # nothing wraps the command
        self.assertEqual(plan.fence.pin["profile"], "workspace-write")
        self.assertEqual(plan.fence.pin["roots"], [self.root, self.extra])

    def claude_plan(self, tools, session=None, initializer=False, max_turns=8, **options):
        H = hosts()
        _, manager_tools = otto_tools()
        spec = H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="prompt", model="claude-sonnet-5-5",
                          reasoning="high", session=session, profile="workspace-write", initializer=initializer,
                          options={"tools": tools, "allowed_tools": manager_tools, "max_turns": max_turns,
                                   "state_root": self.state, **options})
        return H.get_host("claude-code").launch(spec)

    def test_claude_contract_emits_exactly_the_recorded_flags(self):
        H = hosts()
        W, M = otto_tools()
        for name, plan in {
            "worker.initializer": self.claude_plan(W, initializer=True),
            "worker.fresh": self.claude_plan(W),
            "worker.resume": self.claude_plan(W, session="native-1"),
            "manager.resume": self.claude_plan(M, session="native-1", max_turns=40,
                                               allow_subprocesses=True),
        }.items():
            with self.subTest(name):
                self.assertEqual(self.flat(plan.argv), CLAUDE_GOLDEN[name])
        self.assertEqual(plan.session, "native-1")
        self.assertEqual(plan.cwd, self.root)

    def test_claude_contract_fence_is_the_recorded_os_write_fence(self):
        worker_tools, manager_tools = otto_tools()
        worker = self.claude_plan(worker_tools)
        manager = self.claude_plan(manager_tools, allow_subprocesses=True, extra_write_roots=(self.extra,))
        self.assertEqual(worker.fence.kind, "sandbox-exec")
        command = worker.fence.wrap(["/bin/x", "a"])
        self.assertEqual(command[:2], ["/usr/bin/sandbox-exec", "-p"])
        self.assertEqual(self.flat([command[2]]), [CLAUDE_FENCE_GOLDEN["worker"] + EXEC_RULE])
        self.assertEqual(command[3:], ["/bin/x", "a"])
        self.assertEqual(self.flat([manager.fence.wrap(["/bin/x"])[2]]),
                         [CLAUDE_FENCE_GOLDEN["manager"] + EXEC_RULE])
        init = worker.fence.wrap(["/bin/x"], initializer=True)
        self.assertEqual(self.flat([init[2]]),
                         [CLAUDE_FENCE_GOLDEN["worker"] + EXEC_RULE + INITIALIZER_RULE])

    def test_session_and_workspace_flags_cannot_drift_between_hosts(self):
        """One host's flags must not change because the other's tests pass: pin the shared surface."""
        codex_resume = self.codex_plan("sess-1", "read-only").argv
        worker_tools, _ = otto_tools()
        claude_resume = self.claude_plan(worker_tools, session="native-1").argv
        self.assertEqual(codex_resume[codex_resume.index("resume") + 1], "sess-1")
        self.assertEqual(claude_resume[claude_resume.index("--resume") + 1], "native-1")
        self.assertEqual(codex_resume[codex_resume.index("-C") + 1], self.root)
        self.assertNotIn("--resume", self.codex_plan(None, "read-only").argv)
        self.assertNotIn("--resume", self.claude_plan(worker_tools).argv)
        self.assertIn("--dangerously-skip-permissions", claude_resume)       # the OS fence, not the CLI, is the boundary
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", codex_resume)

    def test_a_profile_the_host_does_not_translate_is_refused_not_guessed(self):
        H = hosts()
        with self.assertRaises(H.HostContractError):
            self.codex_plan(None, "danger-full-access")
        with self.assertRaises(H.HostContractError):
            self.codex_plan(None, "default")
        with self.assertRaises(H.HostContractError):
            self.codex_plan(None, "read-only", unexpected_option=True)
        with self.assertRaises(H.HostContractError):    # a socket grant is only for an owner-authorized resume
            self.codex_plan(None, "workspace-write", native_caller_socket=self.sock,
                            native_caller_profile="otto-native-caller")

    def test_a_socket_grant_without_a_native_caller_profile_is_refused(self):
        H = hosts()
        with self.assertRaises(H.HostContractError):
            self.codex_plan("sess-1", "workspace-write", writable_roots=(self.extra,), native_caller_socket=self.sock)

    def test_the_codex_binding_refuses_a_socket_without_a_native_caller_profile(self):
        from herzchen.adapters import host as codex_host
        with self.assertRaises(ValueError):
            codex_host.CodexCliBinding(self.root, native_caller_socket=self.sock,
                                       native_process_observer=lambda p, a: (lambda: None))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelSlots(unittest.TestCase):
    def test_the_bare_fleet_host_carries_no_models_and_otto_supplies_the_recorded_ones(self):
        from otto.agents import host_profiles
        H = hosts()
        for kind, golden in MODELS_GOLDEN.items():
            host = H.get_host(kind)
            self.assertIsNone(host.models)
            with self.assertRaises(H.HostContractError):
                host.normal
            served = host_profiles.serving_host(kind)
            self.assertEqual((served.normal.model, served.normal.reasoning), golden["normal"])
            self.assertEqual((served.xhard.model, served.xhard.reasoning), golden["xhard"])

    def test_otto_model_plans_come_from_its_own_table_and_the_fleet_kinds_agree(self):
        from otto.agents import host_profiles
        H = hosts()
        self.assertEqual(set(host_profiles.PROFILES), {"codex", "claude"})
        for kind in MODELS_GOLDEN:
            profile = host_profiles.profile_for_host(kind)
            roles = host_profiles.PROFILES[profile]["roles"]
            expected = H.ModelPlan(H.ModelBinding(roles["worker_normal"]["model"], roles["worker_normal"]["reasoning"]),
                                   H.ModelBinding(roles["worker_xhard"]["model"], roles["worker_xhard"]["reasoning"]))
            self.assertEqual(host_profiles.model_plan(profile), expected)
        otto_kinds = {k for p in host_profiles.PROFILES.values() for k in p["host_kinds"]}
        self.assertEqual(set(H.known_kinds()), otto_kinds)


# ---------------------------------------------------------------------------
# MCP tools and a token
# ---------------------------------------------------------------------------
class McpAndToken(Workspace):
    def grant(self):
        H = hosts()
        return H.McpGrant(servers=(H.McpServer("otto", "/bin/otto-tools", ("serve",), tools=("ask", "land")),),
                          token_env="OTTO_TOOL_TOKEN", token_env_prefix="OTTO_", token="s3cret-token")

    def plan(self, kind, **kw):
        H = hosts()
        worker_tools, manager_tools = otto_tools()
        options = ({"tools": worker_tools, "allowed_tools": manager_tools, "state_root": self.state}
                   if kind == "claude-code" else {})
        spec = H.TurnSpec(executable="/L/x", workspace=self.root, prompt="p", model="m", reasoning="high",
                          profile="workspace-write", options=options, **kw)
        return H.get_host(kind).launch(spec)

    def test_the_token_travels_in_the_environment_never_in_argv(self):
        for kind in ("codex", "claude-code"):
            with self.subTest(kind):
                plan = self.plan(kind, mcp=self.grant())
                self.assertEqual(plan.env, {"OTTO_TOOL_TOKEN": "s3cret-token"})
                self.assertFalse(any("s3cret-token" in part for part in plan.command()))
                self.assertNotIn("s3cret-token", repr(self.grant()))

    def test_no_grant_changes_no_flag_and_adds_no_environment(self):
        for kind in ("codex", "claude-code"):
            plan = self.plan(kind)
            self.assertEqual(plan.env, {})
        self.assertIn('{"mcpServers":{}}', self.plan("claude-code").argv)      # still the strict-empty config

    def test_claude_receives_the_servers_as_one_strict_config_and_allows_exactly_their_tools(self):
        argv = self.plan("claude-code", mcp=self.grant()).argv
        config = json.loads(argv[argv.index("--mcp-config") + 1])
        self.assertEqual(config, {"mcpServers": {"otto": {"command": "/bin/otto-tools", "args": ["serve"],
                                                          "env": {"OTTO_TOOL_TOKEN": "${OTTO_TOOL_TOKEN}"}}}})
        self.assertIn("--strict-mcp-config", argv)
        allowed = argv[argv.index("--allowedTools") + 1:]
        self.assertIn("mcp__otto__ask", allowed)
        self.assertIn("mcp__otto__land", allowed)

    def test_codex_receives_the_servers_as_config_overrides_and_forwards_the_token_by_name(self):
        argv = self.plan("codex", mcp=self.grant()).argv
        self.assertIn('mcp_servers.otto.command="/bin/otto-tools"', argv)
        self.assertIn('mcp_servers.otto.args=["serve"]', argv)
        self.assertIn('mcp_servers.otto.env_vars=["OTTO_TOOL_TOKEN"]', argv)

    def test_a_grant_that_could_leak_or_collide_is_refused(self):
        H = hosts()
        server = H.McpServer("otto", "/bin/t")
        with self.assertRaises(H.HostContractError):
            H.McpGrant(servers=(server,), token_env="HOME", token="x", token_env_prefix="OTTO_")  # not an OTTO_* name
        with self.assertRaises(H.HostContractError):
            H.McpGrant(servers=(server,), token_env="OTTO_T", token=None, token_env_prefix="OTTO_")  # name, no value
        with self.assertRaises(H.HostContractError):
            H.McpGrant(servers=(server,), token_env="OTTO_T", token="x")              # no prefix given: refused
        with self.assertRaises(H.HostContractError):
            H.McpGrant(servers=(server,), token_env="OTTO_T", token="x", token_env_prefix="OTHER_")  # wrong prefix
        with self.assertRaises(H.HostContractError):
            H.McpGrant(servers=(server, server))                                       # duplicate server
        with self.assertRaises(H.HostContractError):
            H.McpServer("has space", "/bin/t")
        with self.assertRaises(H.HostContractError):
            H.McpServer("otto", "relative-command")

    def test_claude_native_init_must_report_exactly_the_granted_servers_and_tools(self):
        from otto.agents.claude_cli import ClaudeStream, ClaudeBindingError
        H = hosts()
        base = dict(prompt="x", cwd=self.root, model="m", tools=("Read",))
        init = {"type": "system", "subtype": "init", "session_id": "s", "cwd": self.root, "model": "m",
                "permissionMode": "bypassPermissions", "plugins": [], "skills": [], "slash_commands": []}
        granted = ClaudeStream(**base, mcp_tools=("mcp__otto__ask",), mcp_servers=("otto",))
        granted.feed(json.dumps({**init, "tools": ["Read", "mcp__otto__ask"],
                                 "mcp_servers": [{"name": "otto", "status": "connected"}]}).encode())
        self.assertEqual(granted.session, "s")
        with self.assertRaises(ClaudeBindingError):       # a server nobody granted
            ClaudeStream(**base).feed(json.dumps({**init, "tools": ["Read"],
                                                  "mcp_servers": [{"name": "otto"}]}).encode())
        with self.assertRaises(ClaudeBindingError):       # a granted server missing from the native init
            ClaudeStream(**base, mcp_tools=("mcp__otto__ask",), mcp_servers=("otto",)).feed(
                json.dumps({**init, "tools": ["Read", "mcp__otto__ask"], "mcp_servers": []}).encode())


# ---------------------------------------------------------------------------
# The fake third CLI: a new harness is ONE implementation of the contract
# ---------------------------------------------------------------------------
FAKE_CLI = textwrap.dedent('''\
    #!@PYTHON@
    import json, os, sys
    args = sys.argv[1:]
    def flag(name):
        return args[args.index(name) + 1] if name in args else None
    prompt = sys.stdin.read()
    session = flag("--resume") or "fake-session-1"
    print("SESSION " + session, flush=True)
    print("TURN turn-" + str(len(prompt)), flush=True)
    print("NOTE token_seen=%s argv_has_token=%s cwd=%s" % (
        os.environ.get("OTTO_TOOL_TOKEN") == "tok-123", any("tok-123" in a for a in args), os.getcwd()), flush=True)
    print("NOTE mcp=%s write_roots=%s" % (",".join(a for a in args if a.startswith("--mcp=")),
                                         ",".join(a.split("=", 1)[1] for a in args if a.startswith("--write-root="))), flush=True)
    print("DONE in=7 out=3", flush=True)
''')


def fake_host_class():
    H = hosts()

    class FakeStream:
        """Line protocol: SESSION <id> | TURN <id> | DONE in=<n> out=<n> | anything else is a note."""

        def __init__(self):
            self.session = self.turn = None
            self.usage_metrics = None

        def feed(self, raw):
            line = (raw.decode() if isinstance(raw, bytes) else raw).rstrip("\n")
            word, _, rest = line.partition(" ")
            if word == "SESSION":
                self.session = rest
                return (H.HostEvent("session", session_id=rest),)
            if word == "TURN":
                self.turn = rest
                return (H.HostEvent("turn", session_id=self.session, turn_id=rest),)
            if word == "DONE":
                self.usage_metrics = {k: int(v) for k, v in (p.split("=") for p in rest.split())}
                return (H.HostEvent("done", session_id=self.session, turn_id=self.turn, data=self.usage_metrics),)
            return (H.HostEvent("other", session_id=self.session, data={"line": line}),)

        def finish(self, exit_code):
            outcome = "succeeded" if exit_code == 0 and self.usage_metrics is not None else "failed"
            usage = ({"state": "observed", "metrics": self.usage_metrics} if self.usage_metrics
                     else {"state": "unavailable"})
            return H.TurnResult(self.session, self.turn, outcome, usage=usage)

    class FakeFence:
        kind = "fake-write-roots"

        def __init__(self, roots):
            self.roots = tuple(roots)
            self.flags = tuple("--write-root=" + r for r in self.roots)
            self.pin = {"roots": list(self.roots)}

        def wrap(self, argv, *, initializer=False):
            return list(argv)

    class FakeHost(H.HostKind):
        kind = "fakecli"
        profiles = frozenset({"workspace-write"})
        models = H.ModelPlan(H.ModelBinding("fake-small", "low"), H.ModelBinding("fake-large", "high"))

        def make_fence(self, spec):
            return FakeFence((spec.workspace, *spec.writable_roots))

        def render_mcp(self, grant, spec):
            return tuple("--mcp=%s:%s" % (s.name, s.command) for s in grant.servers)

        def build_argv(self, spec, fence_flags, mcp_flags):
            argv = [spec.executable, "--cwd", spec.workspace, "--model", spec.model, *fence_flags, *mcp_flags]
            if spec.session:
                argv += ["--resume", spec.session]
            return argv

        def build_stdin(self, spec):
            return spec.prompt.encode()

        def make_parser(self, spec, **callbacks):
            return FakeStream()

    return FakeHost


class FakeHarness(Workspace):
    def setUp(self):
        super().setUp()
        self.exe = str(Path(self.root, "fakecli"))
        Path(self.exe).write_text(FAKE_CLI.replace("@PYTHON@", sys.executable))
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IXUSR)

    def test_fake_harness_runs_full_loop(self):
        H = hosts()
        registry = H.HostRegistry(H.CodexHost(), H.ClaudeHost(), fake_host_class()())
        self.assertEqual(sorted(registry.kinds()), ["claude-code", "codex", "fakecli"])
        host = registry.get("fakecli")

        # which models serve normal and xhard
        self.assertEqual((host.normal.model, host.xhard.model), ("fake-small", "fake-large"))

        # launch a turn, pass MCP tools + a token, fence writes to a workspace
        grant = H.McpGrant(servers=(H.McpServer("otto", "/bin/otto-tools"),), token_env="OTTO_TOOL_TOKEN",
                           token_env_prefix="OTTO_", token="tok-123")
        spec = H.TurnSpec(executable=self.exe, workspace=self.root, prompt="hello", model=host.normal.model,
                          reasoning=host.normal.reasoning, profile="workspace-write",
                          writable_roots=(self.extra,), mcp=grant)
        first = H.run_turn(host, spec)

        # parse the output stream into events and usage
        self.assertEqual([e.kind for e in first.events], ["session", "turn", "other", "other", "done"])
        self.assertEqual(first.session_id, "fake-session-1")
        self.assertEqual(first.outcome, "succeeded")
        self.assertEqual(first.usage, {"state": "observed", "metrics": {"in": 7, "out": 3}})
        notes = [e.data["line"] for e in first.events if e.kind == "other"]
        self.assertIn("token_seen=True argv_has_token=False", notes[0])      # token by environment only
        self.assertIn("cwd=" + self.root, notes[0])
        self.assertIn("--mcp=otto:/bin/otto-tools", notes[1])                # tools passed
        self.assertIn("write_roots=%s,%s" % (self.root, self.extra), notes[1])  # write fence applied

        # resume the session the host reported
        again = H.run_turn(host, H.TurnSpec(executable=self.exe, workspace=self.root, prompt="more",
                                            model=host.xhard.model, reasoning=host.xhard.reasoning,
                                            profile="workspace-write", session=first.session_id))
        self.assertEqual(again.session_id, first.session_id)
        self.assertEqual(again.outcome, "succeeded")
        self.assertIn("--resume", again.plan.argv)
        self.assertEqual(again.plan.argv[again.plan.argv.index("--model") + 1], "fake-large")
    def test_run_turn_reports_a_failed_process_without_inventing_success(self):
        H = hosts()
        script = Path(self.root, "dies")
        script.write_text("#!%s\nimport sys\nsys.stdin.read()\nprint('SESSION s1')\nsys.exit(3)\n" % sys.executable)
        os.chmod(script, 0o755)
        spec = H.TurnSpec(executable=str(script), workspace=self.root, prompt="p", model="m", reasoning="low",
                          profile="workspace-write")
        result = H.run_turn(fake_host_class()(), spec)
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.exit_status, 3)

    def test_a_host_that_skips_part_of_the_contract_cannot_register(self):
        H = hosts()

        class Incomplete(H.HostKind):
            kind = "half"
            profiles = frozenset({"read-only"})

        with self.assertRaises(TypeError):                 # no parser, fence, mcp or launch: cannot even be built
            Incomplete()
        FakeHost = fake_host_class()

        class DictModels(FakeHost):
            kind = "dictmodels"
            models = {"worker_normal": H.ModelBinding("m", "low"), "worker_xhard": H.ModelBinding("m", "high")}

        with self.assertRaises(H.HostContractError):       # models must be a ModelPlan (or None), not a dict
            H.HostRegistry(DictModels())

        class NotAHost:
            kind = "duck"

        with self.assertRaises(H.HostContractError):
            H.HostRegistry(NotAHost())
        with self.assertRaises(H.HostContractError):
            H.HostRegistry(FakeHost(), FakeHost())          # one kind, one implementation


# ---------------------------------------------------------------------------
# continued worker sessions
# ---------------------------------------------------------------------------
class ContinuationContract(Workspace):
    def test_claude_continuation_uses_exact_parked_session_and_landing_log(self):
        H = hosts()
        C = importlib.import_module("herzchen.fleet.hosts.contract")
        W, M = otto_tools()
        spec = H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="retry this work",
                          model="claude-sonnet-5-5", reasoning="high", profile="workspace-write",
                          session="native-parked", options={"tools": W, "allowed_tools": M,
                          "state_root": self.state})
        request = C.ContinuationRequest(session_id="native-parked", workspace=self.root,
                         attempt_id="attempt-1", landing_log="merge conflict: exact detail\nnext line",
                         settled=True, landing_outcome="conflict")
        authorized = []
        captured = {}
        def fake_run_turn(host, resumed, **kwargs):
            captured["spec"] = resumed
            captured["plan"] = host.launch(resumed, kwargs.get("fence"))
            return object()
        with mock.patch("herzchen.fleet.hosts.contract.run_turn", fake_run_turn):
            result = C.run_continuation(H.ClaudeHost(), spec, request,
                                        authorize=lambda r: authorized.append(r.attempt_id) or True)
        self.assertIsNotNone(result)
        self.assertEqual(authorized, ["attempt-1"])
        plan = captured["plan"]
        self.assertEqual(plan.cwd, self.root)
        self.assertEqual(plan.session, "native-parked")
        self.assertEqual(plan.argv[-2:], ("--resume", "native-parked"))
        frame = json.loads(plan.stdin.decode())
        admitted = frame["message"]["content"][0]["text"]
        self.assertIn(request.landing_log, admitted)
        self.assertIn("[Landing log from the prior settled attempt]", admitted)

    def test_authorization_is_fresh_and_owner_enforces_retry_bound(self):
        H = hosts()
        C = importlib.import_module("herzchen.fleet.hosts.contract")
        W, M = otto_tools()
        spec = H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="p", model="m",
                          reasoning="high", profile="workspace-write", session="s",
                          options={"tools": W, "allowed_tools": M, "state_root": self.state})
        req = C.ContinuationRequest("s", self.root, "attempt", "failed", True, "failed")
        calls, launches = [], []
        def authorize(request):
            calls.append(request.attempt_id)
            return len(calls) < 2
        def fake_run_turn(*args, **kwargs):
            launches.append(1)
            return object()
        with mock.patch("herzchen.fleet.hosts.contract.run_turn", fake_run_turn):
            C.run_continuation(H.ClaudeHost(), spec, req, authorize=authorize)
            with self.assertRaises(H.HostContractError):
                C.run_continuation(H.ClaudeHost(), spec, req, authorize=authorize)
        self.assertEqual(calls, ["attempt", "attempt"])
        self.assertEqual(launches, [1])

    def test_unsettled_and_mismatched_requests_refuse_before_authorize(self):
        H = hosts()
        C = importlib.import_module("herzchen.fleet.hosts.contract")
        W, M = otto_tools()
        spec = H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="p", model="m",
                          reasoning="high", profile="workspace-write", session="s",
                          options={"tools": W, "allowed_tools": M, "state_root": self.state})
        authorize = mock.Mock(return_value=True)
        with self.assertRaises(H.HostContractError):
            C.run_continuation(H.ClaudeHost(), spec, C.ContinuationRequest(
                "s", self.root, "a", "log", False, "failed"), authorize=authorize)
        with self.assertRaises(H.HostContractError):
            C.run_continuation(H.ClaudeHost(), spec, C.ContinuationRequest(
                "other", self.root, "a", "log", True, "failed"), authorize=authorize)
        with self.assertRaises(H.HostContractError):
            C.run_continuation(H.ClaudeHost(), spec, C.ContinuationRequest(
                "s", self.extra, "a", "log", True, "failed"), authorize=authorize)
        self.assertEqual(authorize.call_count, 0)

    def test_claude_continuation_refuses_command_capable_specs(self):
        H = hosts()
        C = importlib.import_module("herzchen.fleet.hosts.contract")
        _, manager_tools = otto_tools()
        spec = H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="p", model="m",
                          reasoning="high", profile="workspace-write", session="s",
                          options={"tools": manager_tools, "allowed_tools": manager_tools,
                                   "state_root": self.state, "allow_subprocesses": True})
        request = C.ContinuationRequest("s", self.root, "a", "failed log", True, "failed")
        authorize = mock.Mock(return_value=True)
        with self.assertRaises(H.HostContractError):
            C.run_continuation(H.ClaudeHost(), spec, request, authorize=authorize)
        self.assertEqual(authorize.call_count, 0)


# ---------------------------------------------------------------------------
# unknown_host_refused
# ---------------------------------------------------------------------------
class UnknownHostRefused(unittest.TestCase):
    def test_unknown_host_refused(self):
        H = hosts()
        for kind in ("mystery-cli", "Codex", "claude", "", None):
            with self.subTest(kind=kind), self.assertRaises(H.UnknownHostKind) as caught:
                H.get_host(kind)
            self.assertIn("known: ", str(caught.exception))
            self.assertIn("codex", str(caught.exception))
        self.assertTrue(issubclass(H.UnknownHostKind, ValueError))

    def test_unknown_kind_is_never_silently_given_codex(self):
        from otto.agents import host_profiles
        H = hosts()
        with self.assertRaises(H.UnknownHostKind):
            host_profiles.profile_for_host("mystery-cli")
        with self.assertRaises(H.UnknownHostKind):
            host_profiles.resolve_profile_name(host_kind="mystery-cli", environ={})
        with self.assertRaises(H.UnknownHostKind):
            host_profiles.resolve_profile_name(environ={"OTTO_HOST_KIND": "mystery-cli"})
        with self.assertRaises(H.UnknownHostKind):
            host_profiles.slot_binding("worker_normal", host_kind="mystery-cli", environ={})
        self.assertFalse(hasattr(host_profiles, "DEFAULT_PROFILE"))
        # known kinds still resolve
        self.assertEqual(host_profiles.profile_for_host("claude-code"), "claude")
        self.assertEqual(host_profiles.profile_for_host("codex"), "codex")

    def test_a_host_added_to_the_registry_is_resolved_without_touching_host_profiles(self):
        H = hosts()
        registry = H.HostRegistry(H.CodexHost(), fake_host_class()())
        self.assertEqual(registry.get("fakecli").normal.model, "fake-small")
        self.assertEqual(registry.get("fakecli").xhard.model, "fake-large")


# ---------------------------------------------------------------------------
# The fleet is product-neutral: Otto's tool policy is supplied by the caller
# ---------------------------------------------------------------------------
class FleetIsNeutral(Workspace):
    def claude_spec(self, initializer=False, **options):
        H = hosts()
        return H.TurnSpec(executable="/L/claude", workspace=self.root, prompt="p", model="claude-sonnet-5-5",
                          reasoning="high", profile="workspace-write", initializer=initializer,
                          options={"state_root": self.state, **options})

    def test_the_fleet_claude_host_carries_no_otto_tool_policy(self):
        H = hosts()
        for name in ("WORKER_TOOLS", "MANAGER_TOOLS", "PARSER_SCHEMA"):
            self.assertFalse(hasattr(H.claude, name), name)

    def test_a_non_initializer_claude_turn_without_allowed_tools_is_refused(self):
        from otto.agents.claude_cli import WORKER_TOOLS
        H = hosts()
        with self.assertRaises(H.HostContractError):
            H.get_host("claude-code").launch(self.claude_spec(tools=WORKER_TOOLS, max_turns=8))
        with self.assertRaises(H.HostContractError):           # and without tools either
            H.get_host("claude-code").launch(self.claude_spec(allowed_tools=WORKER_TOOLS, max_turns=8))

    def test_a_tool_outside_allowed_tools_is_refused(self):
        H = hosts()
        with self.assertRaises(H.HostContractError):
            H.get_host("claude-code").launch(self.claude_spec(tools=("Bash",), allowed_tools=("Read", "Write"),
                                                              allow_subprocesses=True, max_turns=8))

    def test_an_initializer_turn_needs_neither_option_and_still_launches(self):
        H = hosts()
        plan = H.get_host("claude-code").launch(self.claude_spec(initializer=True))
        self.assertEqual(self.flat(plan.argv), CLAUDE_GOLDEN["worker.initializer"])


# ---------------------------------------------------------------------------
# one_codex_binding
# ---------------------------------------------------------------------------
def _classes_named(pattern_parts):
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and all(p in node.name for p in pattern_parts):
                found.append((str(path.relative_to(ROOT)), node.name))
    return found


class OneCodexBinding(unittest.TestCase):
    def test_one_codex_binding(self):
        # one Codex binding class in the tree, and it is the one the live service constructs
        launchers = [c for c in _classes_named(("Codex",)) if "Binding" in c[1] or "CliAdapter" in c[1]]
        self.assertEqual(launchers, [("src/herzchen/adapters/host.py", "CodexCliBinding")])
        # the retired binding is gone: no class, no module, no package export
        self.assertFalse((SRC / "otto" / "agents" / "codex_cli.py").exists())
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("otto.agents.codex_cli")
        agents = importlib.import_module("otto.agents")
        for name in ("CodexCliAdapter", "CodexCliAdapterError", "LaunchUncertainError"):
            self.assertFalse(hasattr(agents, name), name)

    def test_the_codex_launch_argv_is_built_in_exactly_one_place(self):
        needle = '"exec", "-C"'
        builders = [str(p.relative_to(ROOT)) for p in sorted(SRC.rglob("*.py")) if needle in p.read_text("utf-8")]
        self.assertEqual(builders, ["src/herzchen/fleet/hosts/codex.py"])

    def test_the_kept_binding_takes_its_flags_from_the_contract(self):
        source = (SRC / "herzchen" / "adapters" / "host.py").read_text("utf-8")
        self.assertIn("get_host(\"codex\")", source)
        self.assertNotIn("--ignore-user-config", source)
        self.assertNotIn("model_reasoning_effort", source)

    def test_the_live_service_path_reaches_the_kept_binding(self):
        """herzchen_adapter._new_host (the live Codex path) constructs CodexCliBinding from herzchen.adapters."""
        source = (SRC / "otto" / "agents" / "herzchen_adapter.py").read_text("utf-8")
        self.assertIn("from herzchen.adapters import CodexCliBinding", source)
        self.assertNotIn("codex_cli", source)

    def test_herzchen_package_still_imports_nothing_from_otto(self):
        for path in sorted((SRC / "herzchen" / "fleet").rglob("*.py")):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                self.assertFalse([n for n in names if n == "otto" or n.startswith("otto.")], str(path))


if __name__ == "__main__":
    unittest.main()

"""The one owner service end to end on a synthetic project (no provider, no real CLI).

The owner service runs in-process (a thread) and holds a disposable Store.
The orchestrator is a client: its commands travel through its host lane and
the service relays owner-custody manager commands to the attached project.
Activation is exercised only here, on a synthetic project: operating-setup
apply, then an explicit start-manager. The "Claude" launcher is a local
script that speaks the pinned stream-json shape; it runs under the real
macOS write fence and, as the manager's Bash steps, calls `ottoctl manager`
over its own lanes: the caller socket for identity-bearing commands (the
owner authenticates it by kernel ancestry) and its file lane for the rest.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

from otto.hostctl import config as host_config
from otto.hostctl import manager_client

from test_hostctl_cli import HostctlFixture

SRC = str(Path(__file__).resolve().parents[1] / "src")

LAUNCHER = r'''#!{python} -B
import json, os, subprocess, sys, uuid
sys.path.insert(0, {src!r})
if "--version" in sys.argv:
    print("2.1.293 (Claude Code)"); sys.exit(0)
argv = sys.argv
tools = argv[argv.index("--tools") + 1].split(",") if argv[argv.index("--tools") + 1] else []
model = argv[argv.index("--model") + 1]
resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
frame = json.loads(sys.stdin.readline())
prompt = frame["message"]["content"][0]["text"]
session = resumed or frame.get("session_id") or "synthetic-" + uuid.uuid4().hex[:12]
emit = lambda event: print(json.dumps(event), flush=True)
emit({{"type": "system", "subtype": "init", "session_id": session, "cwd": os.getcwd(), "model": model,
      "permissionMode": "bypassPermissions", "tools": tools, "mcp_servers": [], "plugins": [], "skills": [],
      "slash_commands": []}})
emit({{"type": "user", "uuid": "input-" + uuid.uuid4().hex[:8], "session_id": session,
      "message": {{"role": "user", "content": [{{"type": "text", "text": prompt}}]}}}})
def finish(text):
    emit({{"type": "result", "subtype": "success", "is_error": False, "session_id": session,
          "uuid": "r-" + uuid.uuid4().hex[:8], "result": text, "usage": {{"input_tokens": 3, "output_tokens": 2}}}})
    sys.exit(0)
def bash(name, command):
    emit({{"type": "assistant", "uuid": "a-" + name, "session_id": session, "message": {{"role": "assistant",
          "model": model, "content": [{{"type": "tool_use", "id": name, "name": "Bash",
          "input": {{"command": " ".join(command)}}}}]}}}})
    done = subprocess.run(command, capture_output=True, text=True)
    emit({{"type": "user", "uuid": "t-" + name, "session_id": session, "message": {{"role": "user", "content": [
          {{"type": "tool_result", "tool_use_id": name, "is_error": done.returncode not in (0, 1),
            "content": done.stdout[-2000:]}}]}}}})
    return done.stdout
if not tools:
    finish("READY")
cwd = os.getcwd()
if "Bash" not in tools:
    path = os.path.join(cwd, "answer-" + model + ".txt")
    content = "Worker artifact from " + model + "\\n"
    emit({{"type": "assistant", "uuid": "a-w", "session_id": session, "message": {{"role": "assistant", "model": model,
          "content": [{{"type": "tool_use", "id": "write-1", "name": "Write",
          "input": {{"file_path": path, "content": content}}}}]}}}})
    with open(path, "w") as stream:
        stream.write(content)
    emit({{"type": "user", "uuid": "t-w", "session_id": session, "message": {{"role": "user", "content": [
          {{"type": "tool_result", "tool_use_id": "write-1", "is_error": False, "content": "written"}}]}}}})
    finish("Worker delivered answer.txt for T1.")
ottoctl = [sys.executable, "-B", "-c", "import sys; sys.path.insert(0, {src!r}); "
           "from otto.hostctl.cli import main; sys.exit(main(sys.argv[1:]))", "--home", {home!r}, "manager"]
# The first work turn also resumes the initializer's session; count work
# turns per session to tell the first turn from owner continuations.
marker = os.path.join(cwd, ".turns-" + session)
open(marker, "a").write("turn\n")
turn = len(open(marker).read().splitlines())
open(os.path.join(cwd, "manager-turn-%d.txt" % turn), "w").write(prompt)
if turn == 1:
    open(os.path.join(cwd, "whoami.json"), "w").write(bash("bash-1", ottoctl + ["whoami"]))
    open(os.path.join(cwd, "documents.json"), "w").write(bash("bash-docs", ottoctl + ["project-documents"]))
    open(os.path.join(cwd, "brief-T1.json"), "w").write(bash("bash-brief", ottoctl + [
        "project-documents", "--operation", "read", "--path", "briefs/T1.md"]))
if {escalate!r}:
    if turn == 1:
        out = bash("bash-help", ottoctl + ["request-help", "--request-key", "help-1", "--issue-key", "ruling-1",
            "--problem", "Two valid designs for T1", "--impact", "Blocks T1", "--requested-decision",
            "Pick design A or B", "--return-condition", "A ruling is recorded", "--evidence", "[\"design note\"]"])
        open(os.path.join(cwd, "request-help.json"), "w").write(out)
        finish("Manager turn 1: escalated to the oracle and yielding.")
    if turn == 2:
        issue = json.load(open(os.path.join(cwd, "request-help.json")))["issue_id"]
        out = bash("bash-resolve", ottoctl + ["resolve-help", "--request-key", "resolve-1", "--issue-id", issue,
            "--evidence", "[\"applied the oracle ruling\"]", "--next-action", "Continue T1 with design A"])
        open(os.path.join(cwd, "resolve-help.json"), "w").write(out)
        finish("Manager turn 2: applied the ruling.")
    finish("Manager turn %d: done." % turn)
if {dispatch!r} and turn in (1, 2):
    task, route = ("T1", "normal") if turn == 1 else ("T2", "xhard")
    out = bash("bash-run-%d" % turn, ottoctl + ["run-worker", "--task", task, "--route", route, "--principal",
                                               "demo-run-worker-%d" % turn, "--request-key", task + "-worker",
                                               "--focus", "Write the " + task + " answer"])
    open(os.path.join(cwd, "run-worker-%d.json" % turn), "w").write(out)
    finish("Manager turn %d: dispatched %s (%s) and yielding for its result." % (turn, task, route))
finish("Manager turn %d: done." % turn)
'''


BRIEF_T1 = "# Brief: T1\n\nBuild the first outcome. Proof: tests pass.\n"


@unittest.skipUnless(sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec"), "macOS fence")
class ServeTests(HostctlFixture):
    dispatch = False
    escalate = False

    def setUp(self):
        super().setUp()
        # A Unix socket address is limited to 103 bytes: use a short home.
        short = os.path.realpath(tempfile.mkdtemp(prefix="ohs-", dir="/tmp"))
        self.addCleanup(lambda: shutil.rmtree(short, ignore_errors=True))
        self.home = os.path.join(short, "h")
        Path(self.launcher).write_text(LAUNCHER.format(python=sys.executable, src=SRC, home=self.home,
                                                       dispatch=self.dispatch, escalate=self.escalate))
        os.chmod(self.launcher, 0o755)
        os.makedirs(os.path.join(self.bundle, "briefs"))
        Path(self.bundle, "briefs", "T1.md").write_text(BRIEF_T1)
        self._ready()
        self.config = host_config.load(Path(self.home))

    def orchestrator(self, *argv, wait="120"):
        """The orchestrator's owner-custody manager command, relayed through its host lane."""
        code, out = self._ottoctl("--wait-seconds", wait, "manager", "--project", "demo-run", *argv)
        return out

    def attached(self):
        code, status = self._ottoctl("service", "status")
        return status["attached_project"]

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        code, before = self._ottoctl("schedules", "--project", "demo-run")
        status = self.orchestrator("status")
        self.assertEqual(status["outcome"], "ok", status)
        self.assertEqual(status["relayed"]["from"], "manager lane")
        self.assertEqual(status["manager"], "demo-run-manager")
        self.assertEqual(sorted(status["task_refs"]), ["T1", "T2"])
        attached = self.attached()
        self.assertEqual(attached["run_id"], "demo-run")
        self.assertTrue(os.path.exists(attached["caller_socket"]))
        # This test process was not launched by the owner: the socket refuses it.
        foreign = manager_client.run_launched(["whoami"], {"OTTO_CALLER_SOCKET": attached["caller_socket"]})
        self.assertEqual(foreign["outcome"], "error", foreign)
        self.assertFalse(foreign["provider_called"])
        # An identity-bearing command cannot be relayed for the orchestrator either.
        refused = self.orchestrator("whoami")
        self.assertEqual(refused["outcome"], "error", refused)
        code, busy = self._ottoctl("service", "run")
        self.assertEqual((code, busy["error"]["code"]), (3, "owner_service_running"))
        code, after = self._ottoctl("schedules", "--project", "demo-run")
        self.assertEqual(after["schedules"], before["schedules"])
        self.assertTrue(all(row["host_state"] == "paused" for row in after["schedules"]
                            if row.get("purpose") == "orchestrator-check"))

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        self.assertEqual((code, applied["outcome"], applied["started"]), (0, "replayed", False), applied)
        schedule = applied["setup"]["roles"]["manager"]
        started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        root = Path(self.worktree)
        whoami = json.loads((root / "whoami.json").read_text())
        self.assertEqual(whoami["outcome"], "read", whoami)
        context = whoami["caller_context"]
        self.assertEqual((context["role"], context["principal"]), ("manager", "demo-run-manager"), context)
        # The manager reads its project's documents THROUGH Otto, over its own caller socket.
        listed = json.loads((root / "documents.json").read_text())
        self.assertEqual(listed["outcome"], "listed", listed)
        self.assertIn("briefs/T1.md", {row["path"] for row in listed["documents"]})
        self.assertEqual(listed["caller_context"]["principal"], "demo-run-manager")
        brief = json.loads((root / "brief-T1.json").read_text())
        self.assertEqual((brief["outcome"], brief["content"]), ("read", BRIEF_T1), brief)
        # The orchestrator's lane still answers while the manager is settled; a replay starts nothing.
        self.assertEqual(self.orchestrator("status")["outcome"], "ok")
        replay = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(replay.get("outcome"), "replayed", replay)
        code, schedules = self._ottoctl("schedules", "--project", "demo-run")
        checks = [row for row in schedules["schedules"] if row.get("purpose") == "orchestrator-check"]
        self.assertEqual([row["host_state"] for row in checks], ["paused", "paused"])


class ManagerLoopTests(ServeTests):
    """The manager dispatches a Claude worker over the socket, yields, and is resumed."""
    dispatch = True

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        self.skipTest("covered by ServeTests")

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        self.skipTest("covered by ServeTests")

    @staticmethod
    def service_adapter_factory(*, principal, model, reasoning, service):
        """Real manager fence (children allowed); the worker leaf skips sandbox-exec.

        A scripted launcher is an interpreter script, which the leaf fence's
        single-executable exec rule correctly refuses; the leaf fence itself is
        proven in test_claude_binding and test_claude_manager_admission.
        """
        from otto.agents.claude_adapter import ClaudeWorkerAdapter
        from otto.agents.claude_cli import ClaudeCliTransport, LauncherPin, MANAGER_TOOLS, MacWriteScope
        from otto.hostctl.adapters import claude_settings, native_state_root
        pin = LauncherPin.inspect(claude_settings(service.config)["launcher"])
        state = str(native_state_root(service.config))
        launch = service.manager_launch()
        worktree = service.worktree()
        unfenced = type("UnfencedScope", (), {"identity": MacWriteScope.identity, "workspace": worktree,
            "state_root": state, "allow_subprocesses": False,
            "pin": {"identity": MacWriteScope.identity, "workspace": worktree, "state_root": state,
                    "evidence_kind": "SYNTHETIC-UNFENCED-LEAF"},
            "preflight": lambda self: {**self.pin, "verified": True}, "wrap": lambda self, command, **o: command})()
        worker = ClaudeCliTransport(pin, unfenced, model=model, reasoning=reasoning, timeout_seconds=60)
        manager = ClaudeCliTransport(pin, MacWriteScope(worktree, state, allow_subprocesses=True,
                                                        extra_write_roots=launch["write_roots"]),
            model=model, reasoning=reasoning, timeout_seconds=120, tools=MANAGER_TOOLS, max_turns=200,
            extra_env=launch["env"])
        return ClaudeWorkerAdapter(owner=principal, source=worktree, worktree=worktree, launcher_pin=pin,
            state_root=state, requested_model=model, requested_reasoning=reasoning, transport=worker,
            roles=("worker", "manager"), manager_transport=manager, native_caller_socket=launch["env"]["OTTO_CALLER_SOCKET"],
            native_process_observer=service.native_callers.observe)

    def test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        self.assertEqual(applied["outcome"], "replayed", applied)
        schedule = applied["setup"]["roles"]["manager"]
        root = Path(self.worktree)
        started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        deadline = time.monotonic() + 120
        while not (root / "manager-turn-3.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        first = json.loads((root / "run-worker-1.json").read_text())
        second = json.loads((root / "run-worker-2.json").read_text())
        # Routing is proven from run.json (Otto's generated view): normal -> Haiku, xhard -> Sonnet.
        self.assertEqual((first["outcome"], first["selection"]["model"], first["selection"]["reasoning"]),
                         ("admitted", "claude-haiku-5-5", "high"), first)
        self.assertEqual((second["outcome"], second["selection"]["model"]), ("admitted", "claude-sonnet-5-5"), second)
        self.assertEqual(first["caller_context"]["role"], "manager")
        self.assertTrue((root / "answer-claude-haiku-5-5.txt").exists(), "normal-route worker did not run")
        self.assertTrue((root / "answer-claude-sonnet-5-5.txt").exists(), "xhard-route worker did not run")
        # Each worker result was delivered back by resuming the same manager session.
        self.assertTrue((root / "manager-turn-2.txt").exists(), "manager not resumed after T1")
        self.assertTrue((root / "manager-turn-3.txt").exists(), "manager not resumed after T2")
        self.assertEqual(len(list(root.glob(".turns-*"))), 1, "the manager continued one session")
        self.assertEqual(self.orchestrator("status")["outcome"], "ok")


class EscalationTests(ServeTests):
    """Manager -> oracle (help request) -> the orchestrator's reply -> the manager continues."""
    escalate = True

    def test_service_starts_no_due_relays_status_and_denies_a_foreign_socket_caller(self):
        self.skipTest("covered by ServeTests")

    def test_activation_launches_the_manager_which_authenticates_and_reads_its_documents(self):
        self.skipTest("covered by ServeTests")

    def test_manager_escalates_the_orchestrator_answers_and_the_manager_applies_it(self):
        code, applied = self._ottoctl("operating-setup", "--project", "demo-run", "--operation", "apply")
        schedule = applied["setup"]["roles"]["manager"]
        root = Path(self.worktree)
        started = self.orchestrator("start-manager", "--schedule-id", schedule)
        self.assertEqual(started.get("outcome"), "succeeded", started)
        # The manager's request-help went through its file lane during its own turn.
        requested = json.loads((root / "request-help.json").read_text())
        self.assertIn("issue_id", requested, requested)
        issue_id = requested["issue_id"]
        code, read = self._ottoctl("help", "read", "--project", "demo-run")
        issue = next(item for item in read["issues"] if item["issue_id"] == issue_id)
        self.assertEqual(issue["current_owner_ref"]["kind"], "wrk.assignment")
        attached = self.attached()
        fields = ["--issue-id", issue_id, "--authority-source", "x", "--response", "Use design B",
                  "--proposed-solution", "x", "--next-action", "x"]
        # A launched process cannot answer for the oracle: not over its file lane (no owner grant) ...
        forged = manager_client.run_launched(["--timeout-seconds", "30", "respond-help", "--request-key", "forged",
            *fields], {"OTTO_MANAGER_IPC": attached["manager_ipc"]})
        self.assertNotEqual(forged.get("outcome"), "responded", forged)
        self.assertIn("host lane", json.dumps(forged))
        # ... and the orchestrator cannot smuggle it through the manager relay.
        smuggled = self.orchestrator("respond-help", "--request-key", "smuggled", *fields)
        self.assertEqual(smuggled["outcome"], "error", smuggled)
        code, answered = self._ottoctl("--wait-seconds", "60", "help", "respond", "--project", "demo-run",
            "--issue-id", issue_id, "--request-key", "ruling-1-answer", "--response", "Use design A",
            "--proposed-solution", "Design A keeps one resolver", "--next-action", "Implement T1 with design A")
        self.assertEqual(code, 0, answered)
        self.assertNotIn(answered.get("outcome"), {"error", "pending"}, answered)
        deadline = time.monotonic() + 60
        while not (root / "resolve-help.json").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        resolved = json.loads((root / "resolve-help.json").read_text())
        self.assertNotEqual(resolved.get("outcome"), "error", resolved)
        self.assertIn("Use design A", (root / "manager-turn-2.txt").read_text())
        self.assertNotIn("Use design B", (root / "manager-turn-2.txt").read_text())


if __name__ == "__main__":
    unittest.main()

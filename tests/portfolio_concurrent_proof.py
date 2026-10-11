"""needs-unsandboxed: opt-in two-project authenticated manager proof.

Default invocation is inert and does not start a service or bind sockets:

    python3 tests/portfolio_concurrent_proof.py

Run only on the unsandboxed macOS host (the real caller socket and
``sandbox-exec`` fence are part of the evidence):

    python3 tests/portfolio_concurrent_proof.py --run

The proof uses a disposable Store and removes its temporary home on exit.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)
from test_hostctl_cli import HostctlFixture, RUN, _write_bundle


FAKE_VERSION = "2.1.293 (Claude Code)"

# This fake Claude CLI waits until the controller has observed both native
# manager processes, then makes real identity-bearing reads over each process'
# own Otto caller socket. Each read is written into that project's fenced
# worktree for assertions by the controller.
LAUNCHER = r'''#!{python} -B
import json, os, subprocess, sys, time, uuid
sys.path.insert(0, {src!r})
if "--version" in sys.argv:
    print({version!r}); sys.exit(0)
argv = sys.argv
tools = argv[argv.index("--tools") + 1].split(",") if argv[argv.index("--tools") + 1] else []
model = argv[argv.index("--model") + 1]
resumed = argv[argv.index("--resume") + 1] if "--resume" in argv else None
frame = json.loads(sys.stdin.readline())
prompt = frame["message"]["content"][0]["text"]
session = resumed or frame.get("session_id") or "synthetic-" + uuid.uuid4().hex[:12]
emit = lambda event: print(json.dumps(event), flush=True)
emit({{"type":"system","subtype":"init","session_id":session,"cwd":os.getcwd(),"model":model,
      "permissionMode":"bypassPermissions","tools":tools,"mcp_servers":[],"plugins":[],"skills":[],"slash_commands":[]}})
emit({{"type":"user","uuid":"input-"+uuid.uuid4().hex[:8],"session_id":session,
      "message":{{"role":"user","content":[{{"type":"text","text":prompt}}]}}}})
def finish(text):
    emit({{"type":"result","subtype":"success","is_error":False,"session_id":session,
          "uuid":"r-"+uuid.uuid4().hex[:8],"result":text,"usage":{{"input_tokens":3,"output_tokens":2}}}})
    sys.exit(0)
def bash(name, command):
    emit({{"type":"assistant","uuid":"a-"+name,"session_id":session,"message":{{"role":"assistant","model":model,
          "content":[{{"type":"tool_use","id":name,"name":"Bash","input":{{"command":" ".join(command)}}}}]}}}})
    done = subprocess.run(command,capture_output=True,text=True)
    emit({{"type":"user","uuid":"t-"+name,"session_id":session,"message":{{"role":"user","content":[
          {{"type":"tool_result","tool_use_id":name,"is_error":done.returncode not in (0,1),"content":done.stdout[-3000:]}}]}}}})
    return done.stdout
if not tools:
    finish("READY")
if "Bash" not in tools:
    finish("No Bash tool was admitted to the synthetic manager")
cwd=os.getcwd()
marker=os.path.join(cwd,".otto-concurrent-turns-"+session)
with open(marker,"a") as stream: stream.write("turn\n")
turn=len(open(marker).read().splitlines())
if turn == 1:
    open(os.path.join(cwd,"proof-started"),"w").write("started")
    release=os.path.join(cwd,"proof-release")
    deadline=time.time()+90
    while not os.path.exists(release) and time.time()<deadline: time.sleep(.05)
    if not os.path.exists(release): finish("Timed out waiting for proof controller")
    home={home!r}
    ottoctl=[sys.executable,"-B","-c","import sys;sys.path.insert(0,"+repr({src!r})+");from otto.hostctl.cli import main;sys.exit(main(sys.argv[1:]))",
             "--home",home,"manager"]
    suffix="a" if "portfolio-proof-a" in cwd else "b"
    own="briefs/"+suffix+".md"
    foreign="briefs/"+("b" if suffix=="a" else "a")+".md"
    open(os.path.join(cwd,"whoami.json"),"w").write(bash("proof-whoami",ottoctl+["whoami"]))
    open(os.path.join(cwd,"own-brief.json"),"w").write(bash("proof-own",ottoctl+["project-documents","--operation","read","--path",own]))
    open(os.path.join(cwd,"foreign-brief.json"),"w").write(bash("proof-foreign",ottoctl+["project-documents","--operation","read","--path",foreign]))
    open(os.path.join(cwd,"shared.json"),"w").write(bash("proof-shared",ottoctl+["project-documents","--operation","read","--path","portfolio/portfolio.md"]))
finish("Concurrent authenticated project-document proof complete")
'''


class Proof(HostctlFixture):
    def _ottoctl(self, *args: str):
        # Separate CLI processes avoid process-global redirect_stdout races
        # when two start-manager requests are in flight concurrently.
        result = subprocess.run([sys.executable, '-B', '-m', 'otto.hostctl.cli',
            '--home', self.home, *args], capture_output=True, text=True, timeout=150,
            env=dict(os.environ, PYTHONPATH=SRC, PYTHONDONTWRITEBYTECODE='1'))
        return result.returncode, json.loads(result.stdout)

    """Fixture helpers inherited from the existing disposable-store setup."""

    def _assert(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    def run(self) -> dict[str, Any]:
        self.setUp()
        try:
            short = os.path.realpath(tempfile.mkdtemp(prefix="otp-", dir="/tmp"))
            # Replace the fixture's longer default home so every Unix socket
            # address remains under macOS's pathname limit.
            self.home = os.path.join(short, "h")
            self.launcher = os.path.join(short, "bin", "claude-fake")
            Path(self.launcher).parent.mkdir(parents=True)
            self.bundle = os.path.join(short, "initial-bundle")
            self.worktree = os.path.join(short, "initial-worktree")
            Path(self.bundle).mkdir(); Path(self.worktree).mkdir()
            _write_bundle(self.bundle)
            self.addCleanup(lambda: shutil.rmtree(short, ignore_errors=True))

            # Install and admit one Claude supervisor, then register and
            # activate two independent projects through the public host flow.
            self._write_fake_launcher(short)
            self._init()
            from otto.hostctl import config as host_config
            def isolated_authentication():
                config = host_config.load(Path(self.home))
                config['hosts']['claude-code']['adapters']['claude-code']['authentication'] = 'isolated'
                host_config.write(Path(self.home), config, replace=True)
                self.owner_service.config = config
            self.owner_service.call(isolated_authentication)
            projects: dict[str, dict[str, str]] = {}
            for suffix in ("a", "b"):
                run_id = "portfolio-proof-" + suffix
                bundle = Path(short, "projects", run_id)
                worktree = Path(short, "worktrees", run_id)
                bundle.mkdir(parents=True); worktree.mkdir(parents=True)
                _write_bundle(str(bundle))
                run = copy.deepcopy(RUN)
                run["run_id"] = run_id
                (bundle / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
                brief_dir = bundle / "briefs"
                brief_dir.mkdir()
                own_brief = "briefs/" + suffix + ".md"
                (bundle / own_brief).write_text("# Brief " + suffix + "\nPrivate to " + run_id + ".\n")
                foreign_brief = "briefs/" + ("b" if suffix == "a" else "a") + ".md"
                projects[suffix] = {"run_id": run_id, "bundle": str(bundle), "worktree": str(worktree),
                                    "own_brief": own_brief, "foreign_brief": foreign_brief}
                code, registered = self._ottoctl("project", "register", "--bundle", str(bundle),
                                                  "--worktree", str(worktree))
                self._assert(code == 0 and registered.get("outcome") in {"registered", "replayed"},
                             "registration failed: " + repr(registered))
                code, activated = self._ottoctl("project", "activate", "--project", run_id,
                                                 "--worktree", str(worktree))
                self._assert(code == 0 and activated.get("outcome") == "prepared",
                             "activation failed: " + repr(activated))
                setup = activated['operating_setup']
                projects[suffix]["schedule_id"] = setup["setup"]["roles"]["manager"]

            # Enroll a real shared portfolio document before either manager
            # launches; the service exposes it only through its project view.
            shared = Path(short, "shared"); shared.mkdir()
            (shared / "portfolio.md").write_text("# Shared portfolio\nTwo-project routing proof.\n")
            code, result = self._ottoctl("portfolio", "sync-docs", "--dir", str(shared))
            self._assert(code == 0 and result.get("outcome") in {"synced", "in_sync"},
                         "portfolio document sync failed: " + repr(result))

            # Submit both starts concurrently. Each fake manager writes its
            # ready marker from inside its own worktree; only after observing
            # both does the controller release them to exercise socket reads.
            results: dict[str, Any] = {}
            failures: list[BaseException] = []
            def start(suffix: str) -> None:
                item = projects[suffix]
                try:
                    results[suffix] = self._ottoctl("--wait-seconds", "120", "manager", "--project", item["run_id"],
                        "start-manager", "--schedule-id", item["schedule_id"])[1]
                except BaseException as exc:
                    failures.append(exc)
            threads = [threading.Thread(target=start, args=(suffix,), daemon=True) for suffix in ("a", "b")]
            for thread in threads: thread.start()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if all(Path(projects[s]["worktree"], "proof-started").exists() for s in ("a", "b")):
                    break
                if failures or any(not thread.is_alive() for thread in threads):
                    break
                time.sleep(.05)
            started = {s: Path(projects[s]["worktree"], "proof-started").exists() for s in ("a", "b")}
            overlap_status: dict[str, Any] = {}
            overlap_error = None
            if all(started.values()):
                code, overlap_status = self._ottoctl("service", "status")
                turns = overlap_status.get("manager_turns", {})
                if not (code == 0 and turns.get("active") == 2 and
                        turns.get("active", 0) <= turns.get("limit", 0)):
                    overlap_error = "service did not report two bounded concurrent manager turns: " + repr(overlap_status)
                for suffix in ("a", "b"):
                    Path(projects[suffix]["worktree"], "proof-release").write_text("go")
            else:
                # Release any one-sided turn so cleanup can drain the service.
                for suffix in ("a", "b"):
                    Path(projects[suffix]["worktree"], "proof-release").touch()
            for thread in threads: thread.join(timeout=150)
            self._assert(all(not thread.is_alive() for thread in threads), "manager start command did not settle")
            self._assert(all(started.values()), "both native managers did not overlap: " + repr(started))
            self._assert(not failures, "manager start raised: " + repr(failures))
            self._assert(overlap_error is None, overlap_error or "")
            for suffix in ("a", "b"):
                self._assert(results[suffix].get("outcome") in {"succeeded", "replayed"},
                             "manager did not complete: " + repr(results[suffix]))

            # Authenticated manager identity and document scope checks.
            for suffix in ("a", "b"):
                item = projects[suffix]
                root = Path(item["worktree"])
                who = json.loads((root / "whoami.json").read_text())
                self._assert(who.get("outcome") == "read" and
                             who.get("caller_context", {}).get("role") == "manager" and
                             who.get("caller_context", {}).get("principal") == item["run_id"] + "-manager",
                             "manager socket did not authenticate expected principal: " + repr(who))
                own = json.loads((root / "own-brief.json").read_text())
                self._assert(own.get("outcome") == "read" and item["run_id"] in own.get("content", ""),
                             "manager could not read own brief: " + repr(own))
                foreign = json.loads((root / "foreign-brief.json").read_text())
                self._assert(foreign.get("outcome") == "unavailable",
                             "manager read a brief absent from its own project: " + repr(foreign))
                shared_doc = json.loads((root / "shared.json").read_text())
                self._assert(shared_doc.get("outcome") == "read" and
                             "Two-project routing proof" in shared_doc.get("content", ""),
                             "manager could not read shared portfolio document: " + repr(shared_doc))

            code, status = self._ottoctl("service", "status")
            turns = status.get("manager_turns", {})
            attached_rows = status.get("attached_projects", status.get("projects", []))
            self._assert(code == 0 and turns.get("active", 0) == 0 and
                         {row.get("run_id") or row.get("project_id") for row in attached_rows} >=
                         {projects["a"]["run_id"], projects["b"]["run_id"]},
                         "service status did not report both drained project journeys: " + repr(status))

            # Drain one project, confirm it leaves the attached set, then
            # issue a fresh project-bound read to prove on-demand re-attach.
            code, drained = self._ottoctl("service", "drain", "--project", projects["a"]["run_id"])
            self._assert(code == 0 and drained.get("outcome") in {"drained", "already_drained"},
                         "project drain failed: " + repr(drained))
            code, after_drain = self._ottoctl("service", "status")
            attached_rows = after_drain.get("attached_projects", after_drain.get("projects", []))
            attached = {row.get("run_id") or row.get("project_id") for row in attached_rows}
            self._assert(projects["a"]["run_id"] not in attached,
                         "drained project remained attached: " + repr(after_drain))
            code, reattached = self._ottoctl("--wait-seconds", "30", "manager", "--project",
                                             projects["a"]["run_id"], "status")
            self._assert(code == 0 and reattached.get("outcome") == "ok",
                         "project did not answer after re-attach: " + repr(reattached))
            code, after_reattach = self._ottoctl("service", "status")
            attached_rows = after_reattach.get("attached_projects", after_reattach.get("projects", []))
            attached = {row.get("run_id") or row.get("project_id") for row in attached_rows}
            self._assert(projects["a"]["run_id"] in attached,
                         "project did not return to attached set: " + repr(after_reattach))
            return {"outcome": "passed", "projects": {s: projects[s]["run_id"] for s in projects},
                    "authenticated_reads": 2, "concurrent_overlap": started,
                    "overlap_status": overlap_status, "status_manager_turns": turns,
                    "drain": drained, "reattach": reattached}
        finally:
            self.doCleanups()

    def _write_fake_launcher(self, root: str) -> None:
        Path(self.launcher).write_text(LAUNCHER.format(
            python=sys.executable, src=SRC, version=FAKE_VERSION, home=self.home), encoding="utf-8")
        os.chmod(self.launcher, 0o755)
def main() -> int:
    if "--run" not in sys.argv[1:]:
        print("needs-unsandboxed: no sockets or service started. Re-run on the unsandboxed macOS host with --run.")
        return 0
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        print("needs-unsandboxed: this proof requires macOS sandbox-exec and authenticated Unix sockets.", file=sys.stderr)
        return 2
    proof = Proof(methodName="run")
    result = proof.run()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

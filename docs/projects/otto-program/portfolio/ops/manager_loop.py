"""Drive the program manager on Codex (Luna): one turn per event, effects run outside its sandbox.

    python3 ops/manager_loop.py            loop; each wake is a fresh, small Codex session (detach it with nohup)
    python3 ops/manager_loop.py --keep-session [--resume]   one growing session instead (the first design)

Codex can't run the manager the way `claude -p` did. Its sandbox keeps .git read-only and can't
start a sandboxed worker inside itself, and `codex exec` has no /goal: a turn ends when the model
stops. So this loop holds the parts that need neither judgment nor a model:
  - it runs the manager's turn (`codex exec`, then `codex exec resume`), with stream events in ops/manager.log;
  - after the turn, it runs the effects the manager asked for in ops/effects/*.json (an allowlisted
    argv each: launch, run-task.sh, land.sh, otto-lab.sh, lab-rebase, workers.py-remove);
  - it waits with workers.py wait (a worker exits, a landing finishes, a new `## Orchestrator`
    heading) and wakes the manager with the reasons and the effects' output.
It stops when the manager writes ops/manager-goal-met, or when a turn fails twice in a row.

Each wake starts a fresh session by default. The manager's memory is ops/manager-state.md, which it
rewrites at the end of every turn. One resumed session re-sent its whole context on every call: by its
third wake (16 Oct) a turn that wrote two log lines cost 1.29M input tokens, from the same ChatGPT
allowance the workers use.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.home() / "Developer" / "otto-program"
OPS = ROOT / "ops"
BOOT = Path.home() / "Developer" / "otto-claude-host" / "otto" / "ops" / "bootstrap"
LABS = Path.home() / "Developer" / "otto-claude-host" / "labs"
HEAVY_STATE = Path(os.environ.get("OTTO_HEAVY_DIR") or Path.home() / ".local" / "state" / "otto")
PY = "/opt/homebrew/bin/python3.11"
MODEL, EFFORT = "gpt-6-luna", "high"
SESSION_FILE, LOG, EFFECTS = OPS / "manager-session.json", OPS / "manager.log", OPS / "effects"
GOAL_MET, INBOX, WORKERS = OPS / "manager-goal-met", OPS / "requests.md", OPS / "workers.json"
TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STATE = OPS / "manager-state.md"
WAKE = ("You are the Otto program manager (Luna), woken by ops/manager_loop.py in a fresh session. Read "
        "ops/manager-codex.md (your rules) and ops/manager-state.md (where things stand; you keep it). Handle "
        "this wake: act, request effects, log to ops/STATUS.log. Then rewrite ops/manager-state.md (at most 60 "
        "lines: in flight, next in order, waiting on, open asks, anything the next wake must know) and end your "
        "turn. Read other files only in the parts you need (grep, sed -n ranges, tail).\n\n")

GOAL = ("First read ops/manager-codex.md (how you run on Codex), then ops/manager-handoff.md and every "
        "'## Orchestrator' section of ops/requests.md written after it. Then work strictly by "
        "ops/manager-bootstrap-brief.md (read it first, then PLAN.md, RUNBOOK.md and projects/program/tasklist.md); "
        "where ops/manager-codex.md differs, it wins. Your goal is met when (a) every wave 0 and wave 1 task in "
        "projects/program/tasklist.md (SKEL0 included) has landed on canon/main as a 'Land <TASK>' merge, is in "
        "ops/LANDED-PRIOR.txt or is marked skipped, and you have requested CUTOVER in ops/requests.md; OR (b) no worker "
        "is running and none can be launched, and you are waiting only on open requests in ops/requests.md. Then "
        "write ops/manager-goal-met with the clause. Until then, end each turn when there is nothing more to do "
        "now; this loop wakes you on the next event.")


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def note(text):
    with open(LOG, "a") as f:
        f.write(json.dumps({"type": "loop", "at": utc(), "text": text}) + "\n")


def headings():
    try:
        return [l.rstrip("\n") for l in open(INBOX) if l.startswith("## Orchestrator")]
    except OSError:
        return []


def codex_turn(session, message):
    """One manager turn; returns (session id, exit code)."""
    common = ["-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"', "-c", 'sandbox_mode="workspace-write"',
              "-c", "sandbox_workspace_write.writable_roots=[%s]" % ",".join(json.dumps(str(p)) for p in (LABS, HEAVY_STATE)),
              "--ignore-user-config", "--skip-git-repo-check", "--json", "-o", str(OPS / "manager-last.md")]
    argv = ["codex", "exec", "resume", *common, session, "-"] if session else ["codex", "exec", *common, "-"]
    # Events stream into the log as they happen, so a check-in can read a turn in progress.
    with open(LOG, "ab") as log:
        proc = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        proc.stdin.write(message.encode())
        proc.stdin.close()
        for raw in proc.stdout:
            log.write(raw)
            log.flush()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "thread.started":
                session = event.get("thread_id") or session
    return session, proc.wait()


def effect_argv(argv):
    """The command an effect stands for, or a reason it is refused."""
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        return None, "an effect is a JSON array of strings"
    name, rest = argv[0], argv[1:]
    if name == "land-batch":
        # ["land-batch", NAME, TASK, TASK, ..., "--d19", "TASK=ops/reviews/D19-TASK.md", ...]: one gate run
        # for several labs (LANDBATCH); output ops/runs/NAME/land.out, NAME starting "BATCH-".
        if len(rest) < 2 or not rest[0].startswith("BATCH-") or not TASK.match(rest[0]):
            return None, "land-batch takes BATCH-<name> TASK [TASK ...] [--d19 TASK=ops/reviews/D19-TASK.md ...]"
        tasks, d19, i = [], [], 1
        while i < len(rest):
            if rest[i] == "--d19" and i + 1 < len(rest) and "=" in rest[i + 1]:
                who, path = rest[i + 1].split("=", 1)
                decision = (ROOT / path).resolve()
                if not TASK.match(who) or (OPS / "reviews") not in decision.parents or not decision.is_file():
                    return None, "--d19 takes TASK=an existing file under ops/reviews/"
                d19 += ["--d19", f"{who}={decision}"]; i += 2
            elif TASK.match(rest[i]):
                tasks.append(rest[i]); i += 1
            else:
                return None, f"land-batch: unexpected argument {rest[i]!r}"
        if not tasks:
            return None, "land-batch needs at least one task"
        return ["bash", str(BOOT / "land.sh"), "--batch", *tasks, *d19], None
    if not rest or not TASK.match(rest[0]):
        return None, "the second element must be a task id"
    task = rest[0]
    if name in {"launch", "run-task.sh"}:
        allowed = {"--route", "--days", "--resume", "--message", "--host"}
        opts = rest[1:]
        if len(opts) % 2 or any(k not in allowed for k in opts[0::2]):
            return None, f"{name} takes TASK then pairs of {sorted(allowed)}"
        values = dict(zip(opts[0::2], opts[1::2]))
        if "--message" in values:
            message = (ROOT / values["--message"]).resolve()
            if OPS not in message.parents or not message.is_file():
                return None, "--message must be an existing file under ops/"
            values["--message"] = str(message)
        flat = [x for kv in values.items() for x in kv]
        return ["bash", str(BOOT / "run-task.sh"), task, *flat], None
    if name == "land.sh":
        opts = rest[1:]
        if len(opts) % 2 or any(k not in {"--check", "--title", "--d19"} for k in opts[0::2]):
            return None, "land.sh takes TASK [--check CMD] [--title T] [--d19 ops/reviews/D19-TASK.md]"
        values = dict(zip(opts[0::2], opts[1::2]))
        if "--d19" in values:
            decision = (ROOT / values["--d19"]).resolve()
            if (OPS / "reviews") not in decision.parents or not decision.is_file():
                return None, "--d19 must be an existing file under ops/reviews/"
            values["--d19"] = str(decision)
        return ["bash", str(BOOT / "land.sh"), task, *[x for kv in values.items() for x in kv]], None
    if name == "otto-lab.sh" and len(argv) == 3 and argv[1] in {"create", "remove"} and TASK.match(argv[2]):
        return ["bash", str(BOOT / "otto-lab.sh"), argv[1], argv[2]], None
    if name == "lab-rebase" and len(rest) == 1:
        return ["git", "-C", str(LABS / task), "rebase", "canon/main"], None
    if name == "workers.py-remove" and len(rest) == 1:
        return [PY, "-I", str(BOOT / "workers.py"), "remove", "--file", str(WORKERS), "--task", task], None
    if name == "check-run" and len(rest) == 1:
        # A lab's own check command, outside the sandbox (PLAN.md §17.6). Detached; its last line wakes you.
        return ["bash", str(OPS / "check-run.sh"), task], None
    if name == "stage-run":
        # A perch stage on canon/main merged with the named labs, run outside any sandbox (staging
        # needs sandbox-exec, which can't nest inside Codex's). Detached like a landing (17 Oct).
        if len(rest) < 2 or not re.fullmatch(r"[0-6]", rest[1]) or not all(TASK.match(t) for t in rest[2:]):
            return None, "stage-run takes NAME STAGE(0-6) [TASK ...]: the labs to merge onto canon/main"
        return ["bash", str(OPS / "stage-run.sh"), *rest], None
    return None, "unknown effect " + json.dumps(argv)


def run_effects():
    """Run pending effects in name order. Returns (report lines, any failed, landing outputs started)."""
    EFFECTS.mkdir(exist_ok=True)
    lines, failed, landings = [], False, []
    for path in sorted(EFFECTS.glob("*.json")):
        try:
            argv = json.loads(path.read_text())
        except ValueError as exc:
            argv, command, why = None, None, f"not JSON: {exc}"
        else:
            command, why = effect_argv(argv)
        done = path.with_suffix(".done")
        if command is None:
            lines.append(f"- {path.name}: REFUSED: {why}")
            failed = True
            path.rename(done)
            continue
        if argv[0] == "launch":
            task = argv[1]
            brief = OPS / "briefs" / f"{task}.brief.md"
            lab = LABS / task
            if not brief.is_file():
                lines.append(f"- {path.name}: REFUSED: launch needs ops/briefs/{task}.brief.md")
                failed = True
                path.rename(done)
                continue
            if not lab.exists():
                made = subprocess.run(["bash", str(BOOT / "otto-lab.sh"), "create", task], stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True)
                if made.returncode:
                    lines.append(f"- {path.name}: FAILED creating the lab: {(made.stdout + made.stderr).strip()[-600:]}")
                    failed = True
                    path.rename(done)
                    continue
            (lab / ".brief.md").write_text(brief.read_text())
        if argv[0] in ("land.sh", "stage-run", "land-batch") and ((OPS / "land.lock").exists() or unfinished_landings()):
            # One landing at a time. Starting another would truncate its land.out with a lock refusal,
            # and the loop read that refusal as the running landing's result (MGR, 17 Oct).
            lines.append(f"- {path.name}: not started: a landing is running; request it again when that one ends")
            path.rename(done)  # not a failure: no immediate wake, or a manager could spin until the landing ends
            continue
        if argv[0] == "check-run":
            out = OPS / "runs" / argv[1] / "check.out"
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w") as f:
                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            landings.append(str(out))
            lines.append(f"- {path.name}: check-run started; output {out.relative_to(ROOT)}")
            path.rename(done)
            continue
        if argv[0] in ("land.sh", "stage-run", "land-batch"):
            # A landing (or a stage run) runs detached, as the Claude manager ran it; its result line ends the wait.
            out = OPS / "runs" / argv[1] / "land.out"
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w") as f:
                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            landings.append(str(out))
            lines.append(f"- {path.name}: landing started; output {out.relative_to(ROOT)}")
            path.rename(done)
            continue
        # Output goes to a file, never a pipe: run-task.sh leaves a detached worker behind, and a pipe
        # it inherited kept this loop blocked until the worker ended (16 Oct, LAND's launch).
        out = path.with_suffix(".out")
        with open(out, "w") as f:
            code = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT).returncode
        tail = out.read_text(errors="replace").strip()[-1500:]
        lines.append(f"- {path.name} (exit {code}): {tail}")
        failed = failed or code != 0
        path.rename(done)
    return lines, failed, landings


def wait(landings):
    argv = [PY, "-I", str(BOOT / "workers.py"), "wait", "--file", str(WORKERS), "--inbox", str(INBOX)]
    for out in landings:
        argv += ["--land-out", out]
    return subprocess.run(argv, capture_output=True, text=True).stdout.strip()


def dead_workers(reported):
    """Recorded workers whose process is gone, not yet reported. workers.py wait only watches workers
    alive when it starts, so one that exited during a turn was never reported (R1d, 16 Oct)."""
    try:
        entries = json.loads(WORKERS.read_text())
    except (OSError, ValueError):
        return []
    found = []
    for e in entries:
        key = (e.get("task"), e.get("pid"))
        if key in reported or not isinstance(e.get("pid"), int):
            continue
        if subprocess.run(["ps", "-p", str(e["pid"])], capture_output=True).returncode != 0:
            reported.add(key)
            found.append(f"worker exited: {e.get('task')} (pid {e.get('pid')}; it ended during your last turn)")
    return found


def landing_results():
    """{land.out path: its last LAND RESULT line} for every landing that has one."""
    found = {}
    for out in (OPS / "runs").glob("*/land.out"):
        lines = [l for l in out.read_text(errors="replace").splitlines() if l.startswith("LAND RESULT:")]
        if lines:
            found[str(out)] = (out.stat().st_mtime, lines[-1])
    return found


def finished_landings(seen):
    """Landings that ended since the last look. workers.py wait only watches landings still running
    when it starts, so one that ended during a turn was never reported (TOOLING15, 16 Oct)."""
    now = landing_results()
    # Compare the result line only: a running landing appending to its land.out (after a refused
    # duplicate overwrote it) changed the mtime on every sweep line and woke the manager in a spin (17 Oct).
    news = [f"landing finished: {path}: {result}" for path, (mtime, result) in sorted(now.items())
            if (seen.get(path) or (None, None))[1] != result]
    seen.clear()
    seen.update(now)
    return news


def _workers():
    try:
        return json.loads(WORKERS.read_text())
    except (OSError, ValueError):
        return []


def alive_pid(pid):
    return isinstance(pid, int) and subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


def landing_queue():
    """Tasks `ops/ready.py --all` lists as committed and waiting to land."""
    out = subprocess.run([PY, "-I", str(OPS / "ready.py"), "--all"], capture_output=True, text=True).stdout
    return [l.split()[0] for l in out.splitlines() if "committed, waiting to land" in l]


def unfinished_landings():
    found = []
    for out in (OPS / "runs").glob("*/land.out"):
        text = out.read_text(errors="replace")
        pattern = "land.sh --batch" if out.parent.name.startswith("BATCH-") else f"land.sh {out.parent.name}"
        if "LAND RESULT:" not in text and subprocess.run(["pgrep", "-f", pattern],
                                                        capture_output=True).returncode == 0:
            found.append(str(out))
    return found


def main(argv):
    record = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else {}
    keep = "--keep-session" in argv
    session = record.get("session_id") if keep and "--resume" in argv and record.get("host") == "codex" else None
    if keep:
        message = GOAL if session is None else "Resumed by the loop at %s. Re-read ops/manager-codex.md, then carry on." % utc()
    else:
        message = WAKE + "The loop has just started (%s). %s" % (
            utc(), "Carry on from ops/manager-state.md." if STATE.exists() else
            "There is no ops/manager-state.md yet: read ops/manager-handoff.md and the newest '## Orchestrator' sections, then write it.")
    strikes = 0
    reported = set()
    seen_landings = landing_results()
    reported_queue = [[]]
    while True:
        before = len(headings())
        note("turn starts" + (f" (session {session})" if session else " (fresh session)"))
        session, code = codex_turn(session if keep else None, message)
        SESSION_FILE.write_text(json.dumps({
            "host": "codex", "session_id": session, "loop_pid": os.getpid(), "pid": os.getpid(),
            "model": MODEL, "effort": EFFORT, "started": record.get("started") if record.get("session_id") == session else utc(),
            "goal": GOAL}, indent=1))
        record = json.loads(SESSION_FILE.read_text())
        strikes = strikes + 1 if code else 0
        note(f"turn ended (exit {code})")
        if GOAL_MET.exists():
            note("goal met: " + GOAL_MET.read_text().strip())
            return 0
        if strikes >= 2 or session is None:
            note("two failed turns in a row (or no session): stopping; the orchestrator resumes with --resume")
            return 1
        missed = headings()[before:]
        # An orchestrator section that arrived during the turn can countermand what the turn asked for
        # (four resumes ran after a "don't resume" on 17 Oct). Hold that turn's effects unrun and wake the
        # manager with the new sections; it re-requests what still applies.
        pending = sorted(EFFECTS.glob("*.json")) if missed else []
        if pending:
            for path in pending:
                path.rename(path.with_suffix(".held"))
            prefix = "" if keep else WAKE
            message = prefix + (f"Wake at {utc()}.\nNew orchestrator sections arrived during your turn:\n" + "\n".join(missed) +
                       "\n\nSo the effects you requested were HELD, not run: " + ", ".join(x.name for x in pending) +
                       ". Read the new sections first; then re-request (as new ops/effects/*.json) only what still applies.")
            note("held effects after new orchestrator sections: " + ", ".join(x.name for x in pending))
            continue
        lines, failed, started = run_effects()
        effects = ("Effects you requested:\n" + "\n".join(lines)) if lines else "No effects were requested."
        gone = dead_workers(reported) + finished_landings(seen_landings)
        prefix = "" if keep else WAKE
        # With no live worker and no landing there is nothing to wait for: a manager that asked only for
        # a step (a rebase) would sleep until an orchestrator section (16 Oct 21:28Z: 1 h idle).
        idle = lines and not unfinished_landings() and not any(
            alive_pid(e.get("pid")) for e in _workers())
        # Work waiting to land with no landing running: wake the manager with the queue (it left the
        # queue idle four times on 16-17 Oct).
        queue = [] if (OPS / "land.lock").exists() or unfinished_landings() else landing_queue()
        if queue and queue != reported_queue[0]:  # once per queue, so a blocked queue can't spin the loop
            gone = gone + ["no landing is running; waiting to land: " + ", ".join(queue)]
        reported_queue[0] = queue
        if failed or missed or gone or idle:
            message = prefix + (f"Wake at {utc()}.\n" + effects +
                       ("\nNew orchestrator sections during your turn:\n" + "\n".join(missed) if missed else "") +
                       ("\nEvents:\n" + "\n".join(gone) if gone else ""))
            continue
        # A worker that exits between the dead-worker check above and the wait's own start is
        # invisible to the wait (it only watches workers alive when it starts): OPERATOR-ADMIT's
        # exit at 04:25:47Z, the second the turn ended, went unreported (17 Oct). Look once more.
        late = dead_workers(reported)
        if late:
            message = prefix + (f"Wake at {utc()}.\n" + effects + "\nEvents:\n" + "\n".join(late))
            continue
        reasons = wait(sorted(set(started + unfinished_landings())))
        finished_landings(seen_landings)  # what the wait just reported counts as seen
        for task, pid in re.findall(r"worker exited: (\S+) \(pid (\d+)\)", reasons):
            reported.add((task, int(pid)))  # reported by the wait: dead_workers mustn't repeat it
        message = prefix + (f"Wake at {utc()}. Events:\n{reasons}\n\n{effects}\n\n"
                   "Read any new '## Orchestrator' sections, act, request effects, then end your turn.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Astra writes the D19 decisions the landing gate asks for (the orchestrator, 17 Oct 2026).

Watches ops/requests.md for "## Manager <UTC>: <TASK> D19 decision" headings. For each task without
ops/reviews/D19-<TASK>.md, runs one read-only Astra (gpt-6-astra, xhigh) session that writes the decision
there (its first LAND / SEND BACK line is the verdict the gate reads; it names every changed test file),
then appends a "## Orchestrator <UTC>" section telling the manager what to do. At most MAX at once.
The orchestrator spot-checks these decisions at the hourly check-in.
    python3 ops/d19_watch.py            (runs until killed)
"""
import datetime, json, os, re, subprocess, time
OPS = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(OPS)
OTTO = os.path.expanduser("~/Developer/otto-claude-host/otto")
INBOX, REVIEWS, LOG = os.path.join(OPS, "requests.md"), os.path.join(OPS, "reviews"), os.path.join(OPS, "d19-watch.log")
HEADING = re.compile(r"^## Manager (\S+): (?:([A-Za-z0-9][A-Za-z0-9._-]*) D19 decision|D19 request: ([A-Za-z0-9][A-Za-z0-9._-]*))", re.M)
SINCE = "2026-10-17T20:00"  # earlier requests were answered by hand
MAX = 3

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{now()} {msg}\n")

def brief(task):
    return f"""You are Astra (the program's strongest reviewer), deciding one D19 question for the Otto program's landing gate. Read-only: never edit, create or delete files, never commit, never run an owner, staging or `ottoctl`, never pass `--help` to an Otto command, never read ~/.otto, ~/.otto-clients, ~/.codex or ~/Documents/Codex. You may run focused tests read-only only if you need evidence (`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>` inside the lab, with PYTHONDONTWRITEBYTECODE=1). Hand legwork to Luna sub-agents (`spawn_agent` with `model: "gpt-6-luna"`) and check their claims.

The orchestrator owns test design (PLAN.md §17): before deciding, read every "## Orchestrator" section in {ROOT}/ops/requests.md that names {task}; its rulings bind you (for example: a poll interval without a deadline is acceptable; a time limit is not). The rule (PLAN.md §15.3): a change to what an existing test asserts needs a decision. LAND when the changed expectation follows the behaviour change the task's row asks for, keeps (or strengthens) what the test protects, and the test would still fail if the protected property broke. SEND BACK when the change weakens a check, asserts the implementation's own computation, patches a product method, adds a timer, or changes behaviour the row didn't ask for; then say exactly what to restore.

Task {task}. Its lab: {OTTO.rsplit('/', 1)[0]}/labs/{task} (branch lab/{task}). The gate's D19 line is in {ROOT}/ops/runs/{task}/land.out (grep "D19:"), naming the test files whose expectations changed. Read the row ({ROOT}/projects/program/tasklist.md, the line starting "| {task} |"), its design if any ({OPS}/prework/{task}.md), the worker's report ({ROOT}/ops/runs/{task}/worker*.last.md, newest), and the diff: `git -C {OTTO} diff canon/main...lab/{task} -- <each file>` plus the product change it tests.

Your answer is saved verbatim as the decision file, so write exactly this shape:
Line 1: `# D19 decision (Astra for the orchestrator, {now()[:10]}): <every changed test file from the gate's D19 line, comma-separated, exact paths>` (do not write the task id anywhere in the file: the gate reads the first line containing the word LAND)
Line 3: exactly `Decision: LAND` or `Decision: SEND BACK` (plain text, no bold or other markup: the gate reads this line literally; it must be the first line containing either word)
Then one bullet per changed test file, naming its exact path, what changed in its assertions and why that is (or isn't) the row's intended behaviour, with `file:line` evidence. For SEND BACK, end with "Restore:" and the exact changes the worker must make. At most 40 lines. Don't use the words LAND or SEND BACK before line 3."""

def landed(task):
    out = subprocess.run(["git", "-C", OTTO, "log", "--first-parent", "--format=%s", "canon/main", "-n", "400"],
                         capture_output=True, text=True).stdout
    return any(line.startswith(f"Land {task}:") for line in out.splitlines())

def run(task):
    out = os.path.join(REVIEWS, f"D19-{task}.md")
    cmd = ["codex", "exec", "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="xhigh"', "--skip-git-repo-check",
           "-C", OTTO, "-s", "read-only", "-o", out, brief(task)]
    errf = open(os.path.join(REVIEWS, f".D19-{task}.log"), "w")
    log(f"start {task}")
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=errf, stderr=subprocess.STDOUT)

def finish(task, rc):
    out = os.path.join(REVIEWS, f"D19-{task}.md")
    text = open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""
    verdict = next((l for l in text.splitlines() if l.strip().lstrip("*").startswith("Decision:")), "")
    if "SEND BACK" in verdict:
        action = (f"D19-{task} (Astra): SEND BACK. Resume {task}'s worker with the \"Restore:\" part of "
                  f"ops/reviews/D19-{task}.md, then land it again with `--d19 ops/reviews/D19-{task}.md` "
                  f"after Astra's next decision (post a new D19 request).")
        os.replace(out, out + ".sendback")  # the gate must not read a SEND BACK as the current decision
    elif "LAND" in verdict:
        action = f"D19-{task} (Astra): LAND. Land {task} with `--d19 ops/reviews/D19-{task}.md`."
    else:
        action = f"D19-{task}: Astra produced no decision (exit {rc}); the orchestrator will look at the hourly check-in."
    with open(INBOX, "a") as f:
        f.write(f"\n## Orchestrator {now()}\n{action}\n")
    log(f"done {task} rc={rc} {verdict.strip()[:80]}")

def main():
    # handled[task] = how many D19 requests for it have been answered; a new request after a SEND BACK runs again.
    state = os.path.join(ROOT, "ops", "runs", ".d19-handled.json")
    running = {}
    handled = json.load(open(state)) if os.path.exists(state) else {}
    while True:
        wanted = [a or b for ts, a, b in HEADING.findall(open(INBOX, encoding="utf-8", errors="replace").read())
                  if ts >= SINCE and not landed(a or b)]
        asked = {t: wanted.count(t) for t in wanted}
        for task, proc in list(running.items()):
            if proc.poll() is not None:
                del running[task]; handled[task] = asked.get(task, 1); finish(task, proc.returncode)
                json.dump(handled, open(state, "w"))
        for task, n in asked.items():
            if task in running or handled.get(task, 0) >= n or len(running) >= MAX:
                continue
            if os.path.exists(os.path.join(REVIEWS, f"D19-{task}.md")):
                handled[task] = n; continue  # an existing LAND decision already answers it
            running[task] = run(task)
        time.sleep(30)

if __name__ == "__main__":
    main()

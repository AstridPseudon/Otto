# Brief: REWORK (xhard, 0.75 focused days)

**Outcome:** A failed or conflicting landing resumes the same worker session in its parked lab with the log. Only settled failed attempts resume, with fresh authorization and bounded retries. The Claude host can continue a worker session; Otto keeps the retry policy and its bounds.

**Why it matters:** A safe recovery must preserve the worker's exact native session and enough context to continue while refusing unsettled attempts that could duplicate side effects.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REWORK`, on branch `lab/REWORK`, from `canon/main` at `83f8c5d`. Work only here.

**Layer:** Herzchen fleet. Keep the host continuation capability in `src/herzchen/fleet/`; Otto retains retry policy.

**Files you own:**
- `src/herzchen/fleet/hosts/contract.py`
- `src/herzchen/fleet/hosts/claude.py`
- `tests/test_host_contract.py`

**Do not touch:**
- other tasks' files;
- `production/`, any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `TurnSpec.session` in `src/herzchen/fleet/hosts/contract.py` and Claude's exact-session `--resume` handling in `src/herzchen/fleet/hosts/claude.py`; extend the host contract so the continuation is explicit and testable without moving retry policy into Herzchen.

**Your check.** Cover the row's three cases: same-session continuation with its log, refusal when the attempt is unsettled, and the retry bound. Keep the existing host contract tests green. Run the task-owned test file; the landing gate runs changed-module sweeps.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_host_contract.py`

**Regression at the level the friction appears:** settled failed landing resumes the exact same native worker session with the log; unsettled attempts are never resumed; retries stop at the configured bound.

**Deletion budget:** replace the Claude host's refusal to continue a worker session with the explicit fleet continuation contract; Otto continues to own retry policy.

**XHARD only:**
- invariant: Only settled failed attempts resume.
- plausible mistake to avoid: Resuming an attempt whose effects are still unknown, risking duplicate side effects.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. Never wait: no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: you lead, a cheaper model executes.** Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** leave changes for the launcher to commit and report the commit, focused check results, red/green evidence, what was replaced, each sub-agent and whether you corrected it, and anything incomplete.

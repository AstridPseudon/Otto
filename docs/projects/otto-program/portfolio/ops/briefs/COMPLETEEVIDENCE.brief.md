# Brief: COMPLETEEVIDENCE (xhard, 0.75 focused days)

**Outcome:** After a dispatched task is accepted with managed evidence, the manager's ordinary `complete_task` path completes it only after verifying the exact evidence pinned by that acceptance. Missing or tampered evidence remains blocked. Log which completion input was missing and supply it through the manager path as the landing transaction does.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/COMPLETEEVIDENCE`, on branch `lab/COMPLETEEVIDENCE`, from `canon/main` at `7000cdd61a4a8c4f0ab08a692dadbafb1a1f6328`. Work only here.

**Layer:** Otto product. The bug is in the manager's product completion path; keep evidence verification in the existing Herzchen owner gate and pass its required inputs from Otto's owner wiring.

**Files you own:**
- `src/otto/portfolio/completion_gate.py`
- `src/otto/portfolio/owner_completion.py`
- `src/herzchen/domains/assessment/module.py`
- `tests/test_manager_completion_gate.py`
- `tests/test_manager_completion_command.py`

**Other files:** you may also edit any other file your outcome directly requires (a caller, a fixture, a CLI entry, a guard on the path), except the files under "Do not touch". List each one in your report with the reason. Don't stop to ask for a file: stop only if the outcome itself is unclear, or a file you need is under "Do not touch".

**Do not touch:**
- the files of tasks running now: none;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `completion_gate_from_command` in `src/otto/portfolio/completion_gate.py:10` already supplies the authenticated actor and exact evidence refs/hashes to `completion_owner.completion_blockers`; the gate in `src/herzchen/domains/assessment/module.py:1235` requires the acceptance's pinned digest/read grant, actor, and evidence store, and verifies the bytes at lines 1248-1267. Find which input the ordinary owner completion path omits and pass it as the landing's transactional completion path does. Do not treat unknown as verified.

**Your check.** Add a regression on the real owner that activates, admits, dispatches, and finishes a task, then exercises manager `complete_task` with accepted managed evidence. Show it fails on canon and passes with the fix. Also prove tampered or missing evidence still blocks completion. Run the focused files below; staging-owner checks are left to the landing gate because they need `ps` and write outside the lab:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_completion_gate.py tests/test_manager_completion_command.py`

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_completion_gate.py tests/test_manager_completion_command.py`

**Regression at the level the friction appears:** real owner journey from activation through dispatch and done to manager completion, preserving the pinned evidence verification requirement.

**XHARD only:**
- invariant: Completion verifies the exact evidence the acceptance pinned on every completion path.
- plausible mistake to avoid: Treating `unknown` as verified on the manager path.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final report.
- Each sub-brief is self-contained: the goal, exact files and functions, what not to touch, the command to run, and what to report back.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** leave the work in the lab for the launcher to commit. Report the commit, red then green checks, what you deleted, and anything you couldn't finish. Stop and ask if the brief contradicts the code.

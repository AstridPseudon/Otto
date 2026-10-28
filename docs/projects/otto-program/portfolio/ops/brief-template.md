# Brief: <TASK> (<normal | xhard>, <size> focused days)

Required: **Outcome**, **Layer**, **Files you own**, **Your check** and the **Check command:** line (`land.sh` reads it). Everything else is optional; include it when it helps. Fill in from the task's row in tasklist.md.

**Outcome:** <the row's outcome, in plain words: what is true when you are done>

**Why it matters:** <one or two sentences, from PLAN.md>

**Your lab:** `<lab path>`, on branch `lab/<TASK>`, from `canon/main` at `<sha>`. Work only here.

**Layer:** <Herzchen model | Herzchen fleet | Otto product> (PLAN.md D14, §11). New code goes in <package path>. The test: would another product that deploys agents need it? Then it goes in Herzchen, and Otto passes in its own names, roles and policies; Otto keeps only the wiring. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:** <paths>

**Other files:** you may also edit any other file your outcome directly requires (a caller, a fixture, a CLI entry, a guard on the path), except the files under "Do not touch". List each one in your report with the reason. Don't stop to ask for a file: stop only if the outcome itself is unclear, or a file you need is under "Do not touch". (16 Oct: workers stopped five times to ask for one file at a time.)

**Do not touch:**
- the files of tasks running now: <the manager lists them>;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists** (from PLAN.md §11): <the existing functions or modules to reuse, with file:line>

**Your check.** Make it green and keep everything else green:
- <test selectors, or the command>. Run tests with no env prefix (your Bash allowlist refuses one; `pyproject.toml` sets pytest's `pythonpath`): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight N --purpose "<TASK>" -- /opt/homebrew/bin/python3.11 -m pytest …`;
- regression tests must fail on `canon/main` first; show both runs;
- run the test files you changed or added; don't sweep the rest: the landing gate runs every test file that imports a module you changed, twice, and re-runs a failure beside `canon/main` before it refuses (D19);
- run heavy commands as `otto-heavy --weight N --purpose "<TASK>" -- <cmd>`.

**Check command:** `<one shell command, run from the lab, that is the task's own check>`
It is plain pytest (`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <files>`), never prefixed with `otto-heavy`: the gate already runs it under the heavy pool, and `otto-heavy` isn't on its PATH (MGR and LIVENESS were refused for it, 17 Oct).

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** <a journey step, a budget, a refusal → recovery pair, or "n/a: feature task">

**XHARD only:**
- invariant: <the row's invariant>;
- the plausible mistake to avoid: <from §12 or the row>.

**Deletion budget:** a new mechanism must remove or replace one that serves the same purpose. Name it.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/<TASK>` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.

- **A check a worker can't run in its sandbox** (anything that runs `perch.sh` or staging: it needs `ps` and writes outside the lab): say so in the brief. The worker builds and unit-tests the code; the landing gate runs the check outside the sandbox and its output comes back on a refusal (PERCH2B, 17 Oct).
- **Never weaken a test to pass in the worker sandbox.** A failure only the sandbox causes (`sandbox_apply: Operation not permitted`, `ps` denied, nested `sandbox-exec`) is not a red: the gate runs the test outside it. Don't stub `MacWriteScope.preflight` or `wrap`, swap a real fence for a synthetic one, or stub `ps` in a test that checks real processes (REDS3 did all three to pass in its sandbox, 17 Oct; the real fence passed at once outside it).
- **Never run a test that starts a staging owner in the worker sandbox** (`tests/test_staging_startup.py`, `tests/test_perch_staging.py`, the staging cases of `tests/test_perch.py`): they time out there, and a live one overlapping a landing trips the gate's orphan check. The gate runs them.

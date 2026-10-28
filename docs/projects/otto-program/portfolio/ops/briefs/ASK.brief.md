# Brief: ASK (xhard, 1.0 focused days)

**Outcome:** `ask` routes a question to the responsible person and pauses the asking session; an answer resumes exactly that asking session. `otto wait` blocks on Herzchen's event cursor and returns when the relevant event arrives. A paused task never dispatches.

**Why it matters:** Questions that need a human answer must preserve the waiting task and return control to the same session, without duplicate work.

**Your lab:** `labs/ASK`, on branch `lab/ASK`, from `canon/main` at `ac6153d96027a8da0961e8d81d2a8cea9b8c6a91`. Work only here.

**Layer:** Herzchen fleet. New wait/resume behavior belongs in `src/herzchen/domains/work/decisions.py`, `src/herzchen/kernel/recovery.py`, and `src/herzchen/fleet/runner/`. Otto keeps only ask commands and recipient routing in `src/otto/portfolio/issue_loop.py` and `src/otto/portfolio/help_delivery.py`. The test: would another product that deploys agents need it? Then it goes in Herzchen, and Otto passes in its own names, roles and policies; Otto keeps only the wiring. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:** `src/herzchen/domains/work/decisions.py`, `src/herzchen/kernel/recovery.py`, `src/herzchen/fleet/runner/`, `src/otto/portfolio/issue_loop.py`, `src/otto/portfolio/help_delivery.py`, and the task's regression tests.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Herzchen's `record_wait` in `src/herzchen/domains/work/decisions.py` around line 611, event-cursor long-poll in `src/herzchen/kernel/recovery.py` around line 770, and the existing ask/help routing in `src/otto/portfolio/issue_loop.py` and `src/otto/portfolio/help_delivery.py`.

**Your check.** Make the task's ask/wait/resume behavior green and keep everything else green. Run tests with no env prefix (your Bash allowlist refuses one; `pyproject.toml` sets pytest's `pythonpath`): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight N --purpose "ASK" -- /opt/homebrew/bin/python3.11 -m pytest …`;
- regression tests must fail on `canon/main` first; show both runs;
- run the test files you changed or added; don't sweep the rest: the landing gate runs every test file that imports a module you changed, twice, and re-runs a failure beside `canon/main` before it refuses (D19);
- run heavy commands as `otto-heavy --weight N --purpose "ASK" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_journey_client_help.py tests/test_final_recovery_composition.py tests/test_setup_read_native_wait.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** an answer resumes exactly its asking session, a paused task is not dispatched, and `otto wait` returns on the event.

**XHARD only:**
- invariant: An answer resumes exactly the asking session; a paused task never dispatches.
- the plausible mistake to avoid: Resuming by task rather than by session and generation.

**Deletion budget:** replace manager-only answer handling with session-bound answer routing and resume; do not preserve a second, competing resume path.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with a question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/ASK` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/ASK` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.

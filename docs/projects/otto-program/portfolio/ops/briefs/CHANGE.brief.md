# Brief: CHANGE (xhard, 1.25 focused days)

**Outcome:** Agent-changed tasks wait for the user's decision while unchanged tasks keep running; completed work stays immutable. At admission, the existing `work.policy` namespace declares the permitted additions. No change outside that allowance is admitted automatically, and no second ledger is introduced.

**Why it matters:** Admission should authorize a bounded change to the work already reviewed. An edit must not quietly become a new task or rewrite completed work.

**Your lab:** `labs/CHANGE`, on branch `lab/CHANGE`, from `canon/main`. Work only here.

**Layer:** Herzchen model. New admission and change semantics go in `src/herzchen/domains/work/`; Otto declares narrow policy fields through its existing work policy and keeps `worker_occurrences.py` as wiring. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/domains/work/admission.py`
- `src/herzchen/domains/work/assignments.py`
- `src/herzchen/domains/work/sheet.py`
- `src/otto/portfolio/worker_occurrences.py`
- `src/otto/portfolio/tests/test_worker_occurrences.py`
- `tests/test_fresh_worker_admission.py`

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `admission.py` defines content digests and exact admitted revisions; `assignments.py` checks admitted task scope; `sheet.py` owns `amend_policy` for the existing `work.policy` namespace; `worker_occurrences.py` currently bounds launches in `check_turn_allowance` (`:194`).

**Your check.** Show regression tests red on `canon/main` first, then green in the lab. Run the task's test files and keep the Herzchen boundary green; don't sweep unrelated tests. Run tests without an env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Heavy commands use `otto-heavy --weight N --purpose "CHANGE" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider src/otto/portfolio/tests/test_worker_occurrences.py tests/test_fresh_worker_admission.py`

**Callers, including production:** if you change a signature, constructor argument or default, find and update every caller, including `install/controller/` where production startup lives.

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation must change, put it in a separate commit, list each changed assertion as file:line, and report why; it lands only after an Opus D19 decision.

**Regression at the level the friction appears:** an agent edit outside its declared allowance waits; an in-allowance addition is admitted; unchanged tasks keep running; completed work is immutable.

**XHARD only:**
- invariant: No change outside the allowance is admitted automatically.
- plausible mistake to avoid: Classifying an edit to an admitted task as an addition.

**Deletion budget:** extend the existing admission and allowance checks; do not add a second ledger.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with a question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent. Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** leave the work for the launcher to commit. Report the commit, red and green checks, deletions, and anything unfinished. Stop and ask if the brief contradicts the code.

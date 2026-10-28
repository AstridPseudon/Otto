# Brief: ADMIT (xhard, 1.25 focused days)

**Outcome:** `otto admit` pins the exact task revision a reviewer approved. Herzchen's work domain stamps admission on the work record, and `assignments.dispatch` refuses any revision that is not admitted. Otto's reviewed activation calls admission and never re-creates tasks. The user's own edits are admitted by being made. Only agent-written revisions need `otto admit`. When you are done, the admit refuses an unreviewed agent revision, and a lost reply followed by a replay resumes without duplicates.

**Why it matters:** Without a pin, a task can be resolved to a later revision after an edit and run work nobody reviewed (PLAN.md §15, W2 M2/M3). DISPATCH, CHANGE and SKEL all depend on admission being the one gate.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ADMIT`, on branch `lab/ADMIT`, from `canon/main` at `f167aab`. Work only here.

**Layer:** Herzchen model for the mechanism, Otto wiring for the caller (PLAN.md D14, §11). The admission stamp and the dispatch refusal are the work domain's, so they go in Herzchen. Otto keeps only the `otto admit` command and the call from reviewed activation. The test: `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/domains/work/assignments.py` (admission stamps and the dispatch refusal; the dispatch function is at `:789`, and the generation fence and pinned inputs are around `:777`);
- `src/herzchen/domains/work/` other files only as the admission record needs (for example `module.py` if a stamp must be registered);
- `src/otto/portfolio/reviewed_activation.py` (only the call into admission, at the pin and replay handling around `:41-47` and `:291-313`);
- `tests/test_admit.py` (new).

**Do not touch:**
- other tasks' files (DISPATCH owns the launch path in `herzchen/fleet/dispatch.py`, which does not exist yet; don't create it);
- `src/otto/portfolio/cli.py` beyond the `admit` verb's parser entry, and `status.py`;
- `install/controller/`;
- `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists** (PLAN.md §11):
- The dispatch path with its generation fence and pinned inputs: `src/herzchen/domains/work/assignments.py:777-800`, and the `dispatch` function at `:789`.
- The work record and lifecycle: `src/herzchen/domains/work/module.py`, `lifecycle.py`, `sheet.py` (the namespace `work.policy` at `sheet.py:480` is where policy lives; don't add a ledger).
- Otto's reviewed activation and replay: `src/otto/portfolio/reviewed_activation.py:41-47, 291-313`.
- The user-edit path is authoring's own (`src/herzchen/domains/authoring/`); do not reimplement it, and use it to tell a user edit from an agent revision.

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_admit.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Regression tests (in `tests/test_admit.py`) must fail on `canon/main` first. Show both runs.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "ADMIT check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_admit.py tests/test_herzchen_boundary.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: the staging Otto starts there at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** a refusal → recovery pair: an agent revision that is not admitted is refused at dispatch, and admitting it lets dispatch proceed.

**XHARD only:**
- invariant: Admit pins exactly the reviewed revision. Dispatch, retry and resume never use an unadmitted revision.
- the plausible mistake to avoid: resolving an alias after an edit (the alias points at N+1, but the admitted revision is N). Pin the revision id, not the alias.
- acceptance (from the row): admit refuses an unreviewed agent revision; `user_edit_admitted_by_authoring`; a lost reply then a replay resumes without duplicates; a changed sheet is refused with the diff; also (ASTRA0): admit N, then author N+1: dispatch, retry and resume never use N+1, including through aliases and replay.

**Deletion budget:** the admission stamp replaces the pin-and-replay handling in `reviewed_activation.py:41-47` and `:291-313` where it duplicates admission. Name what you removed or replaced, or say why nothing was.

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**Working rules:** commit work in progress to `lab/ADMIT` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet (the `haiku-worker` sub-agent is already Haiku).

**When done:** commit to `lab/ADMIT` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.

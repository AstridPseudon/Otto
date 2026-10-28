# Brief: REVS (xhard, 1.5 focused days). Written by the manager 11:50Z; copy to the lab as `.brief.md` at launch.

**Outcome:** A revision is an immutable snapshot. Every work-record revision's content is kept, keyed by ref and revision. `get(ref@rev)` returns that revision's content, or refuses a revision that wasn't kept; it never returns the current content under an old name. After a sheet apply, the project's task refs, its history mapping and the reply's `task_refs` name the new revisions. A save carries each task's base revision, as folder check-in does, and is refused when any task changed since, naming it, with nothing written. The history entry lists the changed fields (title, instructions, acceptance, `otto.plan`); a derived `name` follows `title`.

**Why it matters:** Stage 1's review (STAGE1 F1, F9; ASTRA1 F1) found that a revision is only a label. Asking for `task@rev-1` returns rev-2's content, and the project's task refs go stale after an edit. Stage 2's pinned admission (ADMIT) and the stale-save diff both need the base revision's content to exist.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REVS`, on branch `lab/REVS`, from `canon/main` (the manager creates it at launch). Work only here.

**Layer:** Herzchen kernel and work domain (PLAN.md D14, §11). The snapshots and the revision-keyed `get` are Herzchen's, so they go in `src/herzchen/kernel/` and `src/herzchen/domains/work/`. Otto keeps only the save's wiring. The test: `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/kernel/store.py` (the revision keep and the revision-keyed read; the in-place `UPDATE identities ...` at `:1850-1885`, and `get_identity` at `:1435-1441`);
- `src/herzchen/kernel/schema.py` (a snapshot table, if you need one; the row says "snapshots in a second table that drifts from identities" is the mistake, so either keep the content inside the identity row's history or key the second table by identity and revision and write both in one transaction);
- `src/herzchen/domains/work/module.py` (`WorkGraph._resolve` at `:823-825`);
- `src/herzchen/domains/work/batches.py` (the ref update after the task writes: refs taken at `:579-587` and `:642` must name the new revisions after `:688-698`; the reply's refs at `:225`, and `herzchen_binding.py:2359` for the reply);
- `tests/test_revisions.py` (new).

**Do not touch:**
- `src/herzchen/fleet/*` (RUNNER owns the runner; don't change it);
- `src/otto/hostctl/*` (COMPOSE, OWNERLANE and SAVEFIX come later);
- `src/otto/portfolio/cli.py`, `status.py`, `execution_host.py`;
- `install/controller/`, `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:**
- The Store's revision bookkeeping and its one-row-per-record shape: `src/herzchen/kernel/store.py` (`get_identity`, the identities update).
- The work domain's batches and save path: `src/herzchen/domains/work/batches.py` (`:225`, `:579-587`, `:642`, `:688-698`), `module.py:823-825`.
- Folder check-in, which already fences a base revision: find it in `src/herzchen/domains/authoring/` (the row cites it as the model for the task base fence).
- ADMIT's pinned revisions (`src/herzchen/domains/work/admission.py`, landed `c126587`): admitted revisions must resolve to their own content after this change.

**Your check.** Make it green and keep everything else green:
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_revisions.py tests/test_admit.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Each acceptance test below fails on `canon/main` first. Show both runs.
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "REVS check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_revisions.py tests/test_admit.py tests/test_herzchen_boundary.py`

**Acceptance (from the row):** after an edit, `get(task@rev-1).title` is the create's title and `get(task@rev-2).title` is the edit's, and the project names `rev-2`; read the plan, revise one task directly, then save the old plan: refused naming that task, no rows written; ADMIT's pinned revisions resolve to their own content.

**Callers, including production:** if you change a signature, constructor argument or default, find every caller and update it. That includes `install/controller/`: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If one must change, keep the change in its own commit and give the reason in your report. It then goes to an Opus decision (D19) before landing.

**Regression at the level the friction appears:** a stale save after a direct revision is refused naming the task, and writes nothing.

**XHARD only:**
- invariant: `get(ref@rev)` returns the content of exactly that revision, or refuses. Never the current content under an old name.
- the plausible mistake to avoid: snapshots in a second table that drifts from `identities`, or a fence on the project revision alone. A save must fence each task's base revision.
- note: the fix for the stale project refs is part of this task (STAGE1 F1 (a)): after an edit, `project@rev-3.tasks[0].revision` and the reply's `task_refs.A.revision` are both `rev-2`.

**Deletion budget:** the revision-keyed read replaces the current-content lookup under a revision name. Name what you removed or replaced, or say why nothing was.

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): exploring and reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**Working rules:** commit work in progress to `lab/REVS` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet (the `haiku-worker` sub-agent is already Haiku).

**When done:** commit to `lab/REVS` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.

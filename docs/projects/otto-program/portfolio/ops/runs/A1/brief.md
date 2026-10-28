# Brief: A1 (normal, 0.5 focused days)

**Outcome:** the contract is amended and the code follows it. Three rules hold: **no execution without admission**; **tasks and documents live only in Otto**; **a pending project may hold inert tasks**. Today tasks are protected fields on a draft, so they can appear only at activation (from parsed tasklists) or when a running manager authors them. So no host can put a plan's tasks into Otto without running something. After this task: a pending project accepts inert tasks (they never dispatch); direction sync cannot create or edit tasks; the dispatch and direction-sync entry points launch nothing and author no task. The pinning test that encodes the old rule is rewritten to the new rule.

**Why it matters:** every later plan task (TYPE, A2, ADMIT) builds on this rule (PLAN.md §1, D2, D16).

**Your lab:** `~/Developer/otto-claude-host/labs/A1`, on branch `lab/A1`, from `canon/main` at `ed78f58`. Work only here.

**Layer:** Otto product (PLAN.md D14). Plans and intake are Otto's. If you find a task-authoring mechanism that another product would also need, say so in your report rather than moving it.

**Files you own** (start here; confirm each by reading it):
- `src/otto/` intake: the protected task fields on a draft (around `intake.py:46-59`);
- `src/otto/` manager authoring path (around `manager_journey_command.py:180-193`);
- `src/otto/` root direction sync (`root_direction_client.py`, lines 1–8: the second plan-authoring path, syncing direction over DAT and WRK);
- the test that pins the old rule (find it: a test asserting that tasks appear only at activation or from a manager); you rewrite its expectation to the new rule;
- a new test file for the new behaviour.

**Do not touch:**
- `src/otto/portfolio/execution_host.py` and `install/controller/shared_operating_service.py` (POOL and STAGE are editing them);
- `src/herzchen/` (fleet and model placement is other tasks');
- other tasks' files;
- `production/`; any Store, `~/.otto` or `~/.codex`; Codex's projects, vision and Native5;
- the running Otto service and `ottoctl` (never pass `ottoctl` `--help`).

**Build on what exists:** the draft intake path and its validators (`intake.py`); the command lane (`herzchen_binding.py`); the existing activation path, which stays the only way tasks are created from a parsed tasklist for an active project.

**Your check.** Make it green and keep everything else green:
- the rewritten pinning test and the new test file: each new rule has a test that fails before your change (show the red run first), then passes;
- `tests/test_herzchen_boundary.py` must pass;
- every test file that imports a module you changed, each run on its own, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_pending_inert_tasks.py`

(Your new test file is named `tests/test_pending_inert_tasks.py`. Tests run with no env prefix: pytest's `pythonpath` is set in `pyproject.toml`.)

**Callers, including production:** if you change a signature, find every caller, including `install/controller/`.

**Existing tests:** don't change what an existing test asserts to make your change pass. The pinning test is the one exception: its expectation changes to the new rule, and that needs an Opus decision (D19). Keep that change in its own commit with the reason in your report, so the gate can route it.

**Regression at the level the friction appears:** a draft can't carry a task until the rule allows it; a direction sync can't create one.

**Deletion budget:** the old "tasks only at activation" branch in the draft path is replaced by the inert-task rule. Name what you delete.

**Working rules:** commit work in progress to `lab/A1` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`.

**When done:** commit to `lab/A1` and don't push. Report the commit, the check runs (red, then green), what you deleted, the pinning-test change in its own commit, and anything you couldn't finish.

# Brief: TYPE (normal, 0.5 focused days)

**Outcome:** Task metadata is typed. Herzchen's work domain accepts registered metadata namespace types with a validator hook, so an invalid payload is refused before it's saved. Otto registers its own `otto.plan` type (route, size and lines, repo → branch) on that hook. A bad route or an unknown key is refused through every writer. Saved tasks from before this change still read correctly.

**Why it matters:** Every later plan, save and view reads task metadata. Without a typed schema, a wrong route or size is stored silently and only shows up at dispatch. See `projects/program/tasklist.md`, row TYPE, and PLAN.md D14 for the layer rule.

**Your lab:** `~/Developer/otto-claude-host/labs/TYPE`, on branch `lab/TYPE`, from `canon/main` at `aabbdc1`. Work only here.

**Layer:** Herzchen model for the namespace types and the validator hook; Otto product for the `otto.plan` registration. New Herzchen code goes in `src/herzchen/domains/work/`. The Otto registration goes in `src/otto/`, and Herzchen must not import from it. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/domains/work/module.py` (namespace types and the validator hook; today `namespace_types=("work", "work.metadata")` at line 104, and `_validate_payload` checks no metadata);
- the Otto registration of `otto.plan`, under `src/otto/` (choose the module that already registers Otto's work-domain contributions; say which in your report);
- `tests/test_task_metadata.py` (new).

**Do not touch:**
- other tasks' files, in particular PERCH's (`labs/PERCH`, the timeline read in `src/herzchen/domains/work/` as a new module, and `ops/bootstrap/perch.sh`);
- `production/`;
- any Store, `~/.otto` or `~/.codex`;
- the live owner or its socket;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:**
- `_validate_payload` and the work domain's namespace types in `src/herzchen/domains/work/module.py`;
- the existing writers of work records: `work.create` and `work.revise` (the list of operation types at module.py ~line 105), and the batch replay path (`intake.py`, `batches.py`) that the save path will use later.

**Your check.** Make it green and keep everything else green:
- `tests/test_task_metadata.py` (new), plus the existing work-domain tests for the files you changed;
- a bad route, a bad size and an unknown key are each refused through every writer (`work.create`, `work.revise`, and the batch replay path), with no new revision written;
- a task saved before this change (no metadata) still reads through the pre-edition reader;
- run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "TYPE" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`;
- regression tests must fail on `canon/main` first; show both runs;
- every test file that imports a module you changed, each file on its own (the landing gate runs them twice).

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_task_metadata.py`

**Callers, including production:** if you change the signature of `_validate_payload` or the namespace registration, find every caller and update it, including `install/controller/` and the production composition in `src/otto/`.

**Existing tests:** don't change what an existing test asserts. If one must change, keep the change in its own commit and give the reason in your report; it then needs an Opus decision (D19).

**Regression at the level the friction appears:** a refusal → recovery pair: a refused bad route leaves the saved task unchanged, and a corrected one saves.

**Deletion budget:** a new mechanism must remove or replace one that serves the same purpose. Name it, or say "none" and why.

**Working rules:** commit work in progress to `lab/TYPE` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`.

**When done:** commit to `lab/TYPE` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (end your report with the question) if the brief contradicts the code.

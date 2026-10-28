# Brief: A2 (normal, 0.75 focused days)

**Outcome:** `otto save FILE` saves one project from a file, through the existing command lane and batch replay. The file has the template seed shape, so a template and a save file are the same thing. It always passes the base revision it read, so a stale save is refused, not applied. The full row is `A2` in `~/Developer/otto-program/projects/program/tasklist.md` (the row after TYPE). Read that row first. Its acceptance evidence is the contract.

**Why it matters:** today a project is created either by file-mode apply or by an onboarding template, with different results. `otto save` is the one creation route. It is a stage 1 prerequisite.

**Your lab:** `~/Developer/otto-claude-host/labs/A2`, on branch `lab/A2`, from `canon/main` at `4f27fd4`. Work only here.

**Layer:** Otto product (PLAN.md D14, §11). The command, the file reader and the lane wiring are Otto's. If the batch or sheet code in Herzchen needs a change, keep it minimal under `src/herzchen/domains/work/`, say so in your report, and the placement check will judge it. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/portfolio/herzchen_binding.py` (the command lane);
- `src/otto/portfolio/intake.py` (the batch replay path, around line 1094, and the default base revision at line 1111);
- the new save module (for example `src/otto/portfolio/save.py`);
- the `otto save` wiring in `src/otto/portfolio/cli.py` (A3 is not running, so this file is yours for this task);
- the new test file `tests/test_otto_save.py`.

**Build on what exists:** `src/herzchen/domains/work/batches.py:150` (batch replay), `src/herzchen/domains/work/sheet.py:558` (`instantiate_new_template`), `src/herzchen/packs/templates.py:390-395` (the template seed shape). A TYPE-landed `otto.plan` metadata is validated on every writer, so a save file's metadata must pass that validator.

**Do not touch:**
- other tasks' files;
- `~/.otto`, `~/.codex`, `~/Documents/Codex`, `production/`, and any Store;
- the live owner. Do not run `ottoctl`, and never pass it `--help`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Your check.** Make it green and keep everything else green:
- the new `tests/test_otto_save.py` covers: unknown deps and cycles are refused; a replay makes no duplicates; omitting a task never withdraws it; and a save from base revision N, after revision N+1 exists, through the real command lane, is refused with a diff and changes nothing;
- run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`;
- regression tests must fail on `canon/main` first; show that run too;
- run only the test files you changed or added. The landing gate sweeps every test file that imports a module you changed, twice (D19);
- run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "A2 check" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_save.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: the staging Otto starts there at landing (D17).

**Existing tests:** do not change what an existing test asserts to make your change pass. If an expectation really must change, keep it in its own commit and give the reason in your report. It then needs an Opus decision (D19). Note that `intake.py:1111` (the default base revision) is the behaviour the row says to change: if an existing test pins the old default, stop and report instead of editing it.

**Regression at the level the friction appears:** a stale save refused, with the diff named, and nothing changed. That is the journey step to test.

**Deletion budget:** a new mechanism must replace one that serves the same purpose. Name what it replaces, or say "nothing: new route".

**Working rules:** commit work in progress to `lab/A2` as you go. Never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on. Run tests in the foreground. If a question blocks you, decide it within this brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**When done:** commit to `lab/A2` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.

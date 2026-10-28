# Brief: A3FIX (normal, 0.5 focused days). Written by the manager 2026-10-16T12:44:25Z; copy to the lab as `.brief.md` at launch.

**Outcome:** A3's own gaps, closed (A3's report, `ops/runs/A3/worker.json`; the orchestrator's 11:31Z section). (1) An `otto` console entry point runs `otto.portfolio.cli`; today only `python -m otto.portfolio.cli` works. (2) `otto open` wraps the project folder too: `work.project.folder-export`, check-in and release, as the A3 row says. (3) The stale-check-in race: a second writer between the stale pre-check and `finish` parks the session; pass `expected_base_revision` into `document_editor_host.py` so `finish` refuses the late writer instead. (4) `otto release` frees a parked session from the CLI.

**Why it matters:** A3 landed (`f167aab`) with these gaps. Without them the human entry point doesn't run from a fresh shell, folder edits don't round-trip, and a race parks sessions for good.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/A3FIX`, on branch `lab/A3FIX`, from `canon/main` at `2880f74`. Work only here.

**Layer:** Otto product for the console entry point, the CLI and the portfolio wiring (PLAN.md D14, §11). The release of a parked session is an authoring mechanism: if the release function is missing from `src/herzchen/authoring/sessions.py`, add it there (Herzchen), and keep only the CLI wiring in Otto. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `pyproject.toml` (`[project.scripts]` at `:12`: add `otto = "otto.portfolio.cli:main"`, if `main` exists there; check first);
- `src/otto/portfolio/cli.py` (the verbs, `open`, `release`);
- `src/otto/portfolio/document_editor_host.py` (`finish` and `expected_base_revision`);
- `src/herzchen/authoring/sessions.py` (release, only if missing);
- `tests/test_otto_open_release.py` (new);
- `tests/test_document_editor_host.py` (only to add cases; don't change what an existing case asserts).

**Do not touch:**
- `src/otto/hostctl/*` (OWNERLANE's files; its lab is awaiting an Opus decision);
- `src/herzchen/kernel/*` and `src/herzchen/domains/work/*` (REVS's files);
- `src/otto/portfolio/status.py`, `show.py` (A3's, unless a test needs them);
- `production/`, any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:**
- A3's `otto.portfolio.cli` verbs and its `show`/`status` (`src/otto/portfolio/cli.py`, `show.py`, `status.py`), landed in `f167aab`;
- `document_editor_host.py`'s `finish` and its stale pre-check;
- the folder-export work item `work.project.folder-export`: find it in the canon tree before writing a new one.

**Your check.** Make it green and keep everything else green:
- `tests/test_otto_open_release.py` (new): the acceptance cases below, each red on `canon/main` first. Show both runs.
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_open_release.py tests/test_otto_show_status.py tests/test_document_editor_host.py tests/test_herzchen_boundary.py`. Run tests with no env prefix (`pyproject.toml` sets pytest's `pythonpath`).
- Run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "A3FIX check" -- <cmd>`.
- Run the test files you changed or added; don't sweep the rest. The landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_open_release.py tests/test_otto_show_status.py tests/test_document_editor_host.py tests/test_herzchen_boundary.py`

**Acceptance (from the row):**
- `otto open`, `otto show` and `otto status` run as `otto …` from a fresh shell (test: the console entry point resolves and runs the verb);
- a folder edit through `open` round-trips (open, edit a file in the folder, check in: the change is in the project);
- two writers racing: the late one is refused with the base it lost to, never parked (test: the stale `finish` returns a refusal naming `expected_base_revision`);
- a parked session is released by `otto release` (test: park, release, the session is free).

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** a late writer's `finish` is refused with a message naming the base it lost to, and nothing is parked.

**Deletion budget:** a new mechanism must remove or replace one that serves the same purpose. Name it, or say why nothing was.

**Working rules:** commit work in progress to `lab/A3FIX` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**When done:** commit to `lab/A3FIX` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.

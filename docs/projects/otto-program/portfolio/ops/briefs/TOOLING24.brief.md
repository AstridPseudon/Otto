# Brief: TOOLING24 (normal, 0.25 focused days)

**Outcome:** Update the landing gate's sweep in `ops/bootstrap/land.sh` so a changed file under `ops/` selects every test file that names it by file or module name. Run those selected files alone twice, as the gate does for other changed files. Add coverage for a doctored landing that changes `ops/bootstrap/perch_stage2_owner.py` and selects `tests/test_perch.py`.

**Why it matters:** The current sweep misses tests that load changed bootstrap scripts, allowing a landing to break their callers without running their coverage.

**Your lab:** The launcher creates the TOOLING24 lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto landing gate and its test coverage.

**Files you own:** `ops/bootstrap/land.sh` and the focused tests for its sweep behavior. `tests/test_perch.py` is the required test file selected by the doctored landing scenario.

**Other files:** You may edit any other file directly needed for this outcome, except the files listed under Do not touch. Explain each additional file in your report.

**Do not touch:**
- `ops/bootstrap/perch_stage2_owner.py` implementation; PERCH2C is being held for stage-2 diagnosis. You may add focused sweep coverage in `tests/test_perch.py` but must not change its stage-2 product assertions.
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** Extend the existing changed-file test selection in `ops/bootstrap/land.sh`; retain its current per-file isolated execution behavior.

**Your check:** Add a doctored landing regression proving a change to `ops/bootstrap/perch_stage2_owner.py` selects `tests/test_perch.py`, and show that the selected test file is run alone twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <the focused test file or files you add/change>`

**Regression at the level the friction appears:** A doctored landing changing a bootstrap script selects the tests that name it, including `tests/test_perch.py`; the selected file runs twice in isolation.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the commit, focused checks, and any additional files changed. Stop and report if the existing gate structure does not support the required selection without broadening unrelated behavior.

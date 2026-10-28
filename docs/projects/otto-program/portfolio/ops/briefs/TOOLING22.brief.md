# Brief: TOOLING22 (normal, 0.5 focused days)

**Outcome:** The landing gate detects every pytest failure, runs every `&&`-joined check part, and `tests/test_perch.py` uses short temp roots that stay under the socket path limit.

**Your lab:** `lab/TOOLING22`, on branch `lab/TOOLING22`, from `canon/main`. Work only here.

**Layer:** Otto product. The landing gate and its tests live in Otto's tooling.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_perch.py`.

**Other files:** you may also edit any other file your outcome directly requires, except the files under "Do not touch". List each one in your report with the reason. Don't stop to ask for a file: stop only if the outcome itself is unclear, or a file you need is under "Do not touch".

**Do not touch:**
- `ops/bootstrap/canary/project.json`, `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py` (owned by the running SKEL0 worker);
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Your check.** Regression tests must prove: a `SUBFAILED` failure is detected; for `false-pre-existing && new-failure`, both parts run and the new failure refuses landing; and `tests/test_perch.py` passes using short roots. Run the focused test files and report both red-on-canon and green runs for regressions.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py tests/test_perch.py`

**A check a worker can't run in its sandbox:** `tests/test_perch.py` needs short temp roots under `/private/tmp`; the landing gate runs its check outside the worker sandbox. Don't weaken the test for sandbox-only failures.

**Working rules:** never run `git stash`, check out another commit, or run `ottoctl`. Never wait. On Codex, don't commit; the launcher commits when you exit. Give long tests enough time to finish. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

# TOOLING22 resume 1: landing gate found a surviving service run

The fresh landing gate passed the check and all sweep tests, then refused because pid 29717 remained under `/private/tmp/ps-vc825222/_staging/home` after the sweep. See `${TRANSFER_ROOT}/portfolio/ops/runs/TOOLING22/land.log` and `land.out`.

**Outcome:** Find the concrete owner/lifecycle of this service run and make TOOLING22's changes ensure test or staging services are fully stopped before the landing gate's post-sweep census. Keep the intended behavior of detecting leaked processes. Reproduce or otherwise provide evidence for the fix; report the pid/process identity and cleanup path. If the finding is unrelated to TOOLING22's changes, explain that with evidence instead of weakening the census.

**Your lab:** `lab/TOOLING22`, on branch `lab/TOOLING22`, rebased onto current `canon/main` before this resume.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_perch.py`.

**Other files:** you may also edit any other file your outcome directly requires, except the files under "Do not touch". List each one in your report with the reason. Don't stop to ask for a file: stop only if the outcome itself is unclear, or a file you need is under "Do not touch".

**Do not touch:**
- `ops/bootstrap/canary/project.json`, `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py` (owned by the running SKEL0 worker);
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Checks:** Add or adjust a focused regression for the concrete lifecycle defect. Run the focused tests and report results. Do not weaken existing process-census assertions. The landing gate will rerun `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py tests/test_perch.py` outside the worker sandbox.

**Working rules:** never run `git stash`, check out another commit, or run `ottoctl`. Never wait. On Codex, don't commit; the launcher commits when you exit. Give long tests enough time to finish. A test that fails only because the worker sandbox denies a process operation is not a red. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

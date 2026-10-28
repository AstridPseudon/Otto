# Brief: REALSTAGE3 (xhard, 1.0 focused days)

**Outcome:** `perch.sh 3` runs three real Haiku worker tasks through the owner and judges only owner-recorded evidence, including the stage-3 coverage items and six invariants.
**Why it matters:** Stage 3 currently cannot run without `--fake`, and its canary does not declare stage 3.
**Your lab:** Launcher creates this from current `canon/main`; work only there.
**Layer:** Otto proof harness and canary.
**Files you own:** `ops/bootstrap/perch.sh`, `ops/bootstrap/canary/project.json`, and directly required stage-3 tests. You own stage-3 scenario construction; do not edit `ops/bootstrap/perch_report.py` or `tests/test_perch_report.py` (INVARIANTS is queued and will own those). Coordinate evidence needs through your report.
**Other files:** Any other file the stage-3 outcome directly requires, except Do not touch; explain each in report.
**Do not touch:** `ops/bootstrap/perch_report.py`, `tests/test_perch_report.py`; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside the lab.
**Before editing:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/REALSTAGE3.md`.
**Build on:** Existing stages 2 and 4 in `ops/bootstrap/perch.sh`; canary declarations in `ops/bootstrap/canary/project.json`; stage report contract in `ops/bootstrap/perch_report.py` (read only).
**Your check:** Add stage-3 focused tests beside `tests/test_perch.py`; each new assertion must fail on doctored evidence. Don't run the real staging-owner test in the sandbox. Report required outside-sandbox stage invocation.
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`
**XHARD invariant:** A stage verdict reads what the owner did with real workers. Avoid harness bookkeeping or fake worker output as evidence.
**Working rules:** Follow the Codex XHARD rules in the manager brief template: delegate execution to Luna sub-agents; never stash or switch commits; no `ottoctl`; keep tests running to completion. Leave changes uncommitted for launcher.

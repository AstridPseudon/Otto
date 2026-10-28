# Resume LABPIN: resolve round-3 integration regressions

Rebase `lab/LABPIN` onto current `canon/main`, reproduce and fix the new round-3 failures identified in `${TRANSFER_ROOT}/portfolio/ops/integ/culprit-LABPIN.md`. Fix LABPIN's product change, not the tests. Run both named whole test files plus `tests/test_fleet_custody.py`, then `git diff --check`; report reproductions, fixes, and results. Work only in the LABPIN lab and leave changes for the launcher to commit.

**Current ownership:** SCRIPTMGR is running and owns `ops/bootstrap/perch_stage2_owner.py`, `ops/bootstrap/perch_fake_claude.py`, `src/otto/portfolio/worker_custody.py`, `tests/test_perch.py`, and `tests/test_worker_custody.py`; do not edit these or any other file it owns. TESTPATCH has exited; its outside check is being rerun before LABPIN resumes because both checks include `tests/test_fleet_custody.py`.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_serve.py tests/test_reworkwire.py tests/test_fleet_custody.py`

**On Codex:** Do not commit or push; the launcher commits when you exit. Give long tests a long timeout and let them finish. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

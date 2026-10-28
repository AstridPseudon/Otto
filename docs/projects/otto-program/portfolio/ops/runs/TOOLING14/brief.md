# Brief: TOOLING14 (normal, 0.1 focused days), done by the orchestrator

**Title:** perch.sh runs stage 1 without --fake, and a fatal error is never exit 0

**Outcome:** (1) `perch.sh 1` without `--fake` died on `"${INIT_ARGS[@]}"`: bash 3.2 under `set -u` calls an empty array unbound. The gate always passes `--fake`, so the path was never run. The expansion is now guarded. (2) It died without a report and exited 0: bash 3.2 hands the EXIT trap `$? = 0` after a `set -u` abort inside a function. Only the normal end sets `PERCH_FINISHED`, and an exit 0 without it becomes 70. Checked: canon's perch with an error injected in `run_stage` exits 0; this one exits 70.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_stage1.py`

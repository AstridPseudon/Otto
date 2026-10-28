Resume the existing PERCH2C xhard task in the same Sol session after rebasing on current canon. Preserve its existing commit and continue the task row's stage-2 evidence assertions.

The Orchestrator released the PROJECTPIN dependency by landing PROJECTPIN as b62b3ea. Keep PERCH2C's landing hold in force; the Orchestrator reruns stage 2. Implement these source fixes and tests:
- The canary repo's first commit ignores `.perch-*.pid` in its `.gitignore`.
- Verify `git status --porcelain` on canon stays empty with the manager marker present, and a landed lab commit contains no marker. Add one unit test for each.

The fake manager's cwd is the canary canon checkout (`canary_workspace_role` returns `manager` for `.../canon`), so `await_release(".perch-manager.pid")` currently dirties the line and makes A's `done` fail with `LandingError: line checkout must be clean and at its branch tip`.

Keep ORPHANWORKER's census lines in `ops/bootstrap/perch.sh` and `ops/bootstrap/perch_report.py` unchanged. Re-read the current task row and lab brief. Run the task's focused tests; do not start a staging owner or run stage 2. Report the changed files and test results, then stop. Do not land PERCH2C until the Orchestrator releases the hold.

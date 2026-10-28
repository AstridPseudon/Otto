# EVWIRE: finish the open items (resume message)

Your commit e5cdab6 is the production wiring. Your last report says two things are still open: the install compositions, and the regression sweep. Finish them in `lab/EVWIRE` and report.

**Do this:**
1. **Install compositions.** Check `install/controller/` for any `AssessmentModule(` construction that sees DAT evidence (you noted `install/controller/w0_completion_policy.py:106`). Either pass the resolver there too, or say with evidence why that path never sees DAT evidence. Update any caller you change.
2. **Checks.** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_wiring.py` must be green. Show that `production_owner_accepts_verified_managed_result` and `production_owner_refuses_tampered_managed_result` were red on canon before your change (f49e17c) and green after.
3. **Regression sweep.** Every test file that imports a module you changed, each file alone, twice. Run through `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "EVWIRE sweep" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`. Report every failing file. For each failure, say whether canon also fails it (run the same file in `labs/_baseline`).
4. **Don't change existing assertions.** If a test would need one changed, stop and report it instead.
5. **Waiting:** nothing in this environment can schedule a wake-up or keep a watch running. Don't try `ScheduleWakeup`, `CronCreate`, or `sleep` loops. If a heavy run queues, run the next one and report the state; the manager re-launches you if needed.
6. Commit to `lab/EVWIRE` (don't push). Report the commit, the red and green runs, the sweep results, and the net lines by file.

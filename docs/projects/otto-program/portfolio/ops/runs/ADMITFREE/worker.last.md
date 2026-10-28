**Cause:** Admission passed `hold_during_turn=True`, so the owner boundary could hold it while a manager turn was active.

**Fix:** Removed that hold from `admit` only. The existing pre-dispatch deferral remains, and other hold-sensitive operations retain their behavior.

**Checks:** The requested command passed: **19 passed, 1 skipped** (the opt-in macOS authentication probe). Coverage checks one presence call, preserves worker A’s capacity and task content pin, and confirms other held operations and mid-dispatch deferral.

Changed only `service.py` and the two requested test files. The worker is represented by a live execution record in the regression test.
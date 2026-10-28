# D19-TOOLING7: orchestrator decision (no Opus call)

1. **Verdict: LAND.**
2. **What changed:** five tests in `tests/test_heavy_lease.py`, the orchestrator's own tests of the bootstrap heavy pool. Their timestamp comparisons became exact order checks on a marks file:
   - `test_a_small_job_uses_a_slot_the_waiting_head_cannot_and_never_delays_it`;
   - `test_status_shows_capacity_and_what_is_running`;
   - `test_a_heavier_job_waits_for_enough_slots_and_is_not_starved`;
   - `test_when_capacity_is_full_the_next_job_waits_and_says_who_holds_it`;
   - `test_no_wait_returns_busy_and_names_what_is_running`.
   
   Each job they observe now holds its state on a go-file until the test releases it, so the tests no longer depend on fixed sleeps.
3. **Why it's not a weakened expectation:** each original intent is still asserted, as an exact order instead of a timing window:
   - the check backfilled while the render held its slots;
   - the head started only after the render ended, and before the check ended;
   - a second small job never started before the head;
   - a heavier job isn't starved;
   - a full pool makes the next job wait and names the holder.
   
   The old forms could hang under load (one did, in the TOOLING7 run at load ~43: `holding()` waited for a count that existed only for a 0.5 s window). That breaks the user's rule: only a hang fails, and tests aren't timed.
4. **Why the orchestrator decides it:** D19 keeps workers and the manager from rewriting expectations to pass. These are the orchestrator's own bootstrap-tooling tests, rewritten at its direction (requests.md 02:33Z; the Sonnet agent's commit 9757cda cites it), so an Opus call would buy nothing. Logged in `ops/STATUS.log`.

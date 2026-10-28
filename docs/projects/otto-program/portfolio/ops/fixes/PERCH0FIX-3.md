# PERCH0FIX: the D19 decision, and one fix (manager, 10:01Z)

Your proof is good and the pool rename stays. One change goes back. The Opus D19 answer is `ops/reviews/D19-PERCH0FIX.md`. Read its F1 first.

## The decision
- **Change 1, the pool rename (`28f1358`): LAND.** Nothing to do.
- **Change 2, the `staging` fault's red set: SEND BACK.** Its third red comes from the Store half of `timeline-events` (`ops/bootstrap/perch_report.py` around lines 438–443, which still adds Store failures and the timeline `error` to `timeline-events`). The row says `store-matches-stage` replaces that half. Do this, and nothing beyond it:

  (a) Move the Store half of `timeline-events` (the gap loop over `timeline.json`, and `if timeline.get("error")`) into `store-matches-stage`. No Store coverage may be lost.
  (b) When `staging_restart != 0`, `store-matches-stage` **skips** with "staging did not start", the same way the lifecycle checks skip.

  The reviewer approves exactly this retarget: `test_a_store_gap_fails_the_timeline_assertion` (`tests/test_perch.py` around line 163) now asserts the gap on `store-matches-stage`, and `EXPECTED_RED["staging"] = {"staging-ready"}`. Any other expectation change needs a new D19, so don't make one.

- **The `lab` fault's two reds (`labs-left-behind`, `timeline-events`): keep as they are.** The orchestrator will change the row's wording. Don't change the code or the test for it.

## The check, after the fix
1. `tests/test_perch.py` and `tests/test_perch_timeline.py`, through `otto-heavy`. `test_perch_timeline` needs `PYTHONPATH=src` to import `herzchen`: that's how it already ran before, so set it in the command, and say so in your report.
2. `tests/test_perch_staging.py` through `otto-heavy`.
3. `bash ops/perch/_scratch/run-perch.sh 0 --fake` must pass 12 of 12.
4. `bash ops/perch/_scratch/run-fault.sh 0 --fake` with `PERCH_FAULT=staging`: the red set must be exactly `{staging-ready}`. Show the report's line for it.
5. Re-run `PERCH_FAULT=timeline` and `PERCH_FAULT=store` once each. Each must still turn only its own assertion red (`timeline-events` and `store-matches-stage`). Report the two red sets.

Keep to the allowed command forms from `ops/fixes/PERCH0FIX-2.md`: `git -C <lab> …`, the tilde path for `otto-heavy`, `bash <script>`, `/opt/homebrew/bin/python3.11 …`.

## Rules, as before
- Commit only the files you own, never `.brief.md` or `ops/perch/_scratch/`.
- Never wait: no Monitor, no sleep loops. Foreground runs only.
- Report: the commit, the red and green results, and the fault red sets, with the exact lines you changed.

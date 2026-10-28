1. **Verdict**
   - **Change 1 (`28f1358`, pool rename): LAND.**
   - **Change 2 (`EXPECTED_RED["staging"]` = three reds): SEND BACK.** Of the three reds, `timeline-events` is red only because the Store half of that check is still there. The row says to replace it with `store-matches-stage`, and the worker didn't. The `lab` fault's two reds are acceptable.

2. **Findings** (most severe first)

   **F1. The `staging` fault turns `timeline-events` red through the Store half of `timeline-events`, which the row says to remove.**
   - **The check:** `ops/bootstrap/perch_report.py:438-443` still adds Store failures to `timeline-events`: tasks with gaps from `timeline.json`, and `if timeline.get("error"): failures.append("store timeline: " + …)`.
   - **The worker never touched it:** `git diff 1b91364 HEAD -- ops/bootstrap/perch_report.py` has no lines that change it.
   - **What the row asks:** row 54 says "`store-matches-stage` replaces the vacuous Store half of `timeline-events`". STAGE0 F4 says the same.
   - **The seeded run shows the cause:** in `ops/perch/_scratch/out/0/20261016T095157Z` (fault `staging`), the `timeline-events` detail is `store timeline: no Store file`, not a missing event. The canary tasks still run when staging fails (`perch.sh:236-248` runs them whatever `RESTART_RC` is), so `events.tsv` is complete.
   - **Same read, two reds:** that one failed Store read also turns `store-matches-stage` red, with `the Store was not read: no Store file; the Store at rest: no Store file` (`perch_report.py:464-472`).
   - **Conflict with the acceptance:** yes. The row requires "each seeded fault turns one red". The SeededFaultRunTests docstring (`tests/test_perch.py:387`) says "turns exactly its assertion kind red".
   - **The code change to make:**
     - (a) Move the Store half (the gap loop and the timeline `error`) out of `timeline-events` and into `store-matches-stage`. That way no Store coverage is lost: today `store-matches-stage` checks counts, read errors and size, but not gaps.
     - (b) When `staging_restart != 0`, `store-matches-stage` should **skip** with "staging did not start", as the lifecycle checks already do (`perch_report.py:499-502`, `perch.sh:221-233`). The run is red anyway through `staging-ready`, so a skip hides nothing.
     - The `staging` fault then turns exactly `{staging-ready}`.
   - **What this decision approves:** part (a) changes an existing expectation. `test_a_store_gap_fails_the_timeline_assertion` (`tests/test_perch.py:163-167`) must now assert the gap on `store-matches-stage`. This decision approves that retarget, and `EXPECTED_RED["staging"] = {"staging-ready"}`. Anything beyond that comes back to D19.

   **F2. The `lab` fault's two reds are acceptable. They predate this task (canon has the same entry and comment). Amend the row's wording rather than the code.**
   - **Why the two reds are different:** `labs-left-behind` reads `leftovers.txt`. `timeline-events` fails on `canary-refused missing lab-deleted` (run `095138Z`), and that event is genuinely absent: the seeded fault returns before `event lab-deleted` (`perch.sh:175-178`). These are two separate true observations. That differs from F1, where one Store read is counted twice.
   - **Wording fix:** change the row and the docstring at `test_perch.py:387` to "turns its own assertion red; any other red is a documented consequence in `EXPECTED_RED`".
   - **Optional:** to get exactly one red, the lab fault could record `lab-deleted` and still leave the lab behind. That is the "claimed removed but still there" case `labs-left-behind` exists to catch.

   **F3 (low). Nothing in the program tracks the "until stage 2" condition on `harness-pool-within-limit`.**
   - It appears only in the code comment (`perch_report.py:448`) and in row 54.
   - `grep -rn "harness-pool\|pool-units" PLAN.md RUNBOOK.md projects/program/*.md ops/*.md` finds row 54 only.
   - Add a stage-2 row: the check reads Otto's `limits` units, and the name `pool-…` comes back.

3. **Sound**
   - **Change 1 matches the acceptance word for word.** Row 54 says "the pool assertion is renamed `harness-pool-within-limit` until stage 2", and STAGE0 F4 prescribes the same.
   - **Change 1 is a rename only.** `git show 28f1358` changes just the string at `perch_report.py:233` and the three test keys. The logic is untouched. Changing or splitting the check isn't possible until stage 2, because no product pool exists yet.
   - **No stale references to the old name.** Grepping `ops/` and `tests/` in the lab finds no `pool-units-within-limit`; it is also absent from PLAN, RUNBOOK and the tasklist.
   - **Q3: no other existing expectation in `tests/test_perch.py` changed.**
     - `NAMES` gained seven names. So did the assertions that iterate over it (`:143`, `:148-155`, and the fake run's all-pass check), which makes them stricter, not looser.
     - `clean_raw` and the `EXPECTED_RED` comment were extended. Everything else is new tests.
   - **No canon drift in the test diff.** The diff against canon `4b3d9d7` equals the diff against the branch base `1b91364`.
   - **The other nine faults each turn exactly one red** in the worker's seeded runs (`095131Z` to `095232Z`).
   - **The tests pass:**
     - `tests.test_perch`: 17 ran, 0 failed, 0 skipped. That includes FakeRunTests and SeededFaultRunTests, which have no gate.
     - `tests.test_perch_staging`: 3 ran, OK.
     - `tests.test_perch_timeline` errors on `import herzchen` without `PYTHONPATH=src`. With it, 8 ran, OK. The worker didn't change that file.

4. **Not checked**
   - I did not build or run the proposed F1 fix, so the "staging turns exactly `{staging-ready}`" result is reasoned from code, not observed.
   - I did not check whether the test runs left any staging process behind.
   - The diffstat against canon also shows `src/` deletions. Those come from canon moving ahead (A2, TYPE) since the branch base, not from the worker. Landing will need a rebase.

5. **Helpers:** 2 (Haiku)
   - One ran the perch test modules and pulled out the bodies of the tests that use `SEEDED_FAULTS` and `EXPECTED_RED`, and checked whether any were gated.
   - One extracted the worker's seeded-fault table, the red sets and details for all 13 runs, and the text of STAGE0 F2–F5 and F7.
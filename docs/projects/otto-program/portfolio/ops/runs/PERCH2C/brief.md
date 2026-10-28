# Brief: PERCH2C (xhard, 1.0 focused days)

**Outcome:** Make every stage-2 check fail when its claim is false, using real product state and stage events. Cover (a) prerequisite completion before dependent dispatch, (b) configured pool/reserve limits with two independent ready tasks and a manager turn, (c) edited admitted instructions are refused while metadata-only edits remain runnable, (d) stage-owned timeline tasks with landed and completed events, (e) owner descriptor count before first dispatch and after last within a small bound, and (f) owner lab-root leftovers before any harness step. Delete the stage-2 fake-worker counter and the two stage-2 tests that call the removed `defer_fake_lab_cleanup`. The report header names `/usr/bin/true` as the real check and says `--fake` also fakes operator presence.

**Why it matters:** Stage 2 currently passes despite false claims about event order, capacity, admission, descriptors, and leftover labs. Each assertion must read evidence the owner produced and fail when the claim is false.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2C`, branch `lab/PERCH2C`. Preserve the existing committed work in this lab and build on it; the launcher will start a fresh Sol session. Rebase on current `canon/main` after ORPHANWORKER lands, before you begin.

**Layer:** Otto staging verification and product-backed stage-2 assertions.

**Files you own:** `ops/bootstrap/perch_report.py` (stage-2 assertions only), `tests/test_perch.py`, `ops/bootstrap/canary/project.json`, and directly required focused fixtures/tests. Read the updated PERCH2C row in `projects/program/tasklist.md` for the exact required evidence and collection path for each assertion.

**Other files:** You may edit any other file the outcome directly requires, except the files/regions below. Explain each such edit in your report.

**Do not touch:** `ops/bootstrap/perch.sh`; the census calls in `ops/bootstrap/perch_report.py` around the start/down census, which ORPHANWORKER owns; `production/`; any Store, `~/.otto` or `~/.codex`; Codex project configuration; anything outside this lab.

**Build on what exists:** The product has a supported capacity configuration: `src/otto/hostctl/product_service.py:56` (`capacity_policy`, with `turn_units` and `manager_reserve`). Set the canary limits through the staging installation's `capacity` setting; add two independent ready tasks beside a manager turn. For (a) and (d), use Store event timestamps already in stage raw data; do not add sleeps. For (c), edit C's instructions after admission through the product task-editing command, record no launch, then make a metadata-only write and record that it launches. For (e), collect `lsof -p <owner pid>` before first dispatch and after last. For (f), list the owner's `<canon>.otto-labs` root before any harness step. Do not invent or infer missing evidence.

**Your check:** Add doctored-input regressions so every assertion fails when its claim is false. Do not run tests that start a staging owner in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** Stage 2 `--fake` rejects false claims about actual task ordering, configured capacity, admission after instruction edits, owner descriptors, and owner labs. Do not run stage 2 or start an owner in this sandbox.

**Invariant:** Each stage-2 check reads evidence the owner produced and fails when its claim is false.

**Plausible mistake to avoid:** Asserting on harness bookkeeping or a fixed list again, or adding sleeps where Store event times already order the run.

**Deletion budget:** Remove the fake-worker counter and the two stale tests that call `defer_fake_lab_cleanup`, deleted by LABCAPTURE (`4c413d7`). Do not restore `stage2_cleanup_owner_labs` or `defer_fake_lab_cleanup`.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the existing commit you preserved, each changed assertion/test file and why, check outcomes (including any sandbox-only failures), and anything incomplete. Stop and report if the product lacks a supported way to collect an input; do not make up evidence.

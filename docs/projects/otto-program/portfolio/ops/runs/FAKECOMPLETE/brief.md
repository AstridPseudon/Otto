# Brief: FAKECOMPLETE (normal, 0.25 focused days)

**Outcome:** Make stage 2's fake completion match the product's real completion path. First determine whether an accepted `done` completes the task in the same transaction; if it does, remove the harness stand-in. Otherwise, read the managed evidence ref and hash recorded by the landing receipt and pass those exact values to completion. Never use the landing candidate or synthesize evidence.

**Why it matters:** Stage 2 must prove that the product's actual task completion and managed evidence flow work, rather than pass because the harness supplies a synthetic ref.

**Your lab:** `lab/FAKECOMPLETE`, on branch `lab/FAKECOMPLETE`, from `canon/main` at `8e360b11b0e064512b35ba9f1fc8d2d7044a79a8`. Work only here.

**Layer:** Otto product. This is stage-2 harness wiring, not a reusable agent runtime capability.

**Files you own:**
- `ops/bootstrap/perch_stage2_owner.py`
- `tests/test_perch.py`

**Do not touch:** no other worker or landing is running. Also do not touch `production/`, Store, `~/.otto`, `~/.codex`, Codex's projects, vision or Native5, or anything outside this lab.

**Build on what exists:** `complete_landed_canary` calls `server.portfolio.complete_task(...)` in `ops/bootstrap/perch_stage2_owner.py`; its current behavior is covered by `tests/test_perch.py` around `PerchStageTwoOwnerTests`.

**Your check:** Add a regression for the correct product path, then run the owned test file. Do not run staging-owner tests in the worker sandbox; the landing gate will run the stage-2 journey outside it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** stage 2 `--fake` completes A, B and C in dependency order without patching any completion the product performs itself.

**Working rules:** Follow the Codex worker rules in the task template. Leave the changes in the lab for the launcher to commit; do not push. Give test commands a long timeout and run them to completion.

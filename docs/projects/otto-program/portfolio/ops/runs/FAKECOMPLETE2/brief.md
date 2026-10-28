# Brief: FAKECOMPLETE2 (normal, 0.1 focused days)

**Outcome:** The stand-in completion reads managed evidence refs from the assessment result's payload, matching the landing path, and the unit test exercises the real `AssessmentResult` shape.

**Why it matters:** Stage 2 must test the product's real completion path so its fake journey can catch errors that staging would expose.

**Your lab:** `lab/FAKECOMPLETE2`, on branch `lab/FAKECOMPLETE2`, from `canon/main` at `ae26807965b98f2b33dc3d5b029baf35515a4820`. Work only here.

**Layer:** Otto product. This is stage-2 harness wiring, not a reusable agent runtime capability.

**Files you own:**
- `ops/bootstrap/perch_stage2_owner.py`
- `tests/test_perch.py`

**Do not touch:** No other worker or landing is running. Also do not touch `production/`, Store, `~/.otto`, `~/.codex`, Codex's projects, vision or Native5, or anything outside this lab.

**Build on what exists:** `complete_landed_canary` reads the assessment result and passes its evidence refs and verified hashes into `complete_task` in `ops/bootstrap/perch_stage2_owner.py` (~line 61). `AssessmentResult.payload` is the evidence source, as in `src/herzchen/domains/assessment/model.py` and `src/otto/hostctl/fleet_landing.py` (~line 439). Update `test_fake_manager_completes_only_landed_canary_with_stored_acceptance` in `tests/test_perch.py` (~line 1264) to use a real `AssessmentResult` (or construct the real class), with the evidence refs in `payload["evidence_refs"]`; ensure it fails on the old code and passes after the fix.

**Your check.** Run the focused unit test only. Do not run staging-owner tests in the worker sandbox; the landing gate runs the stage-2 journey outside it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py::PerchStageTwoOwnerTests::test_fake_manager_completes_only_landed_canary_with_stored_acceptance`

**Regression at the level the friction appears:** Stage 2 `--fake` completes A, B and C in dependency order using the real assessment-result evidence payload.

**Working rules:** Follow the Codex worker rules in the task template. Leave changes in the lab for the launcher to commit; do not push. Give test commands a long timeout and run them to completion.

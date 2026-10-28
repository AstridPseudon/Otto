# Brief: ADMITFREE (normal, 0.5 focused days)

**Outcome:** Admission of an unrelated task succeeds while another worker holds capacity, with one presence check and no effect on the running task's content pin. Admission must not take the owner-boundary hold. Preserve every other caller's `hold_during_turn` behavior, including ADMITHELD's mid-dispatch deferral.

**Why it matters:** Stage 2 showed B held for the whole of A's worker run. An operator must be able to approve the next task while unrelated work runs.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ADMITFREE`, branch `lab/ADMITFREE`, from current `canon/main`. Work only here.

**Layer:** Otto product, owner admission service and tests.

**Files you own:**
- `src/otto/hostctl/service.py`
- `tests/test_operator_admission.py`
- `tests/test_execution_host_manager_turn_queue.py`

**Other files:** You may edit any other file directly required by this outcome, except files under “Do not touch”. List each additional file and why in your report. Do not stop to ask for a file.

**Do not touch:**
- files owned by running PERCH2B worker: `ops/bootstrap/canary/project.json`, `ops/bootstrap/perch.sh`, `ops/bootstrap/staging.sh`, `tests/test_perch.py`, and `tests/test_perch_staging.py`;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** Change only `_admit_revision`'s owner-boundary hold behavior in `src/otto/hostctl/service.py`; do not remove `hold_during_turn` from unrelated operations. Preserve ADMITHELD's queued deferral when its covered window is active. PINCONTENT ensures the metadata-only admission stamp does not invalidate the running worker's content pin.

**Your check.** Add focused regression coverage proving B is admitted while A holds worker capacity, exactly one presence check occurs, A's pin remains valid, and other `hold_during_turn` operations still wait. Preserve existing operator admission and mid-dispatch pending behavior. Run the changed test files in the lab; don't run staging checks in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_operator_admission.py tests/test_execution_host_manager_turn_queue.py`

**Regression at the level the friction appears:** Admit B while A's worker holds capacity; B is admitted at once, exactly one presence check is made, A's run is unaffected, and other boundary-sensitive operations remain held.

**Working rules:** Never stash, check out another commit, or commit. Leave work for `run-task.sh` to commit. Run long tests to completion with a long timeout. Never run `ottoctl` or pass it `--help`.
- **On Codex (Luna):** Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the cause, fix, focused checks, and anything incomplete.

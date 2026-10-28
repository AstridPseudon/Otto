# Brief: ADMITHELD (normal, 0.5 focused days)

**Outcome:** When an operator admission arrives while the owner is dispatching, the owner applies that same admission after the dispatch boundary closes, with one presence check and one admission log line. If presence is declined, no admission is written. Preserve the invariant that nothing is written as the operator without owner-verified presence.

**Why it matters:** Stage 2 showed that admitting C while A was dispatching returned `held` and required a second operator request, which would prompt for Touch ID again. One admission should require one presence check.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ADMITHELD`, branch `lab/ADMITHELD`, from current `canon/main`. Work only here.

**Layer:** Otto product, owner admission and dispatch boundary. Keep presence verification and the operator write in the owner; do not let a request choose or cache an actor.

**Files you own:**
- `src/otto/portfolio/admit.py`
- `src/otto/portfolio/execution_host.py`
- `src/otto/hostctl/service.py`
- `tests/test_operator_admission.py`
- `tests/test_execution_host_manager_turn_queue.py`

**Other files:** You may edit any other file directly required by this outcome, except files under “Do not touch”. List each additional file and why in your report. Do not stop to ask for a file.

**Do not touch:**
- files owned by running workers: `ops/bootstrap/canary/project.json`, `ops/bootstrap/perch.sh`, `ops/bootstrap/staging.sh`, `tests/test_perch.py`, and `tests/test_perch_staging.py` (PERCH2B);
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** Reuse the owner-local admission path in `src/otto/portfolio/admit.py`, the dispatch boundary and owner serialization in `src/otto/portfolio/execution_host.py`, and the owner service request handling in `src/otto/hostctl/service.py`. Keep the same admission request key when retrying a held operation. Either retain the already verified presence result until the boundary closes, or perform the one presence check only once the operation can be applied.

**Your check.** Add focused regression coverage for an admission arriving mid-dispatch: one presence check, admission applied once the boundary closes, one log line, and no write when presence is declined. Preserve existing operator admission, dispatch, and no-forged-presence behavior. Run the changed test files in the lab. Do not run staging checks in the worker sandbox; landing runs them outside.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_operator_admission.py tests/test_execution_host_manager_turn_queue.py`

**Regression at the level the friction appears:** C is admitted while A's dispatch boundary is open, with exactly one presence check and one admission record; a declined presence leaves the Store unchanged.

**Working rules:** Never stash, check out another commit, or commit. Leave work for the launcher to commit. Run long tests to completion with a long timeout. Never run `ottoctl` or pass it `--help`.
- **On Codex (Luna):** Leave work for `run-task.sh` to commit. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the cause, fix, focused checks, and anything incomplete.

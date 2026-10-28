# Brief: AUTODISPATCH (xhard, 1.5 focused days)

**Outcome:** The owner automatically launches admitted, ready worker tasks without a manager turn. Blocked or unadmitted tasks never launch; a manager's `run-worker` for an already dispatched task returns `retained`; concurrent pumps cannot launch the same task generation twice.

**Why it matters:** Routine execution should proceed under the owner's admission, dependency, role and capacity rules without waking a manager for operational work. Every path must pass the existing `admit_execution` gate exactly once per task generation.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/AUTODISPATCH`, on branch `lab/AUTODISPATCH`, from `canon/main` at `61a6e99be5cdef8d36a07736bf601bcf2f09e951`. Work only here.

**Layer:** Otto product composition (`src/otto/hostctl/`, `src/otto/portfolio/`) with the selection loop in Herzchen fleet (`src/herzchen/fleet/dispatch.py`).

**Files you own:**
- `src/otto/hostctl/product_service.py` (`bind_dispatcher`, currently around line 308)
- `src/otto/portfolio/execution_host.py` (`_capacity_tick` around 715, `_pump_owner_calls` around 1388, `_submit_worker` around 1933)
- `src/otto/portfolio/manager_journey_service.py` (`start-retained-worker` around 896-915)
- `src/herzchen/fleet/dispatch.py`
- `tests/test_fleet_dispatch.py`
- `tests/test_execution_host_manager_turn_queue.py`
- `tests/test_manager_journey_service.py`

**Other files:** You may edit any additional file directly required by the outcome, except files under Do not touch. List each in your report with the reason.

**Do not touch:**
- The running PERCH2 worker's files: `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `ops/bootstrap/canary/project.json`, `ops/bootstrap/canary/fake_worker.py`, `tests/test_perch.py`, `tests/test_perch_staging.py`, `tests/test_perch_timeline.py`.
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Keep the selection loop in `src/herzchen/fleet/dispatch.py` (`FleetDispatcher.dispatch_ready`, `dispatch`, `finish`). Compose via `ProductService.bind_dispatcher` in `src/otto/hostctl/product_service.py`; trigger from the owner capacity pump (`src/otto/portfolio/execution_host.py` `_capacity_tick` / `_pump_owner_calls`); reuse the manager-independent launch path around `_submit_worker` and `start-retained-worker` in `src/otto/portfolio/manager_journey_service.py`. Preserve `admit_execution` as the sole launch gate. The task row in `projects/program/tasklist.md` is the acceptance contract.

**Your check:** Cover automatic admitted/ready dispatch without a manager turn; blocked and unadmitted refusal; retained result for a manager request after dispatch; no duplicate launch under concurrent pumps; and one `admit_execution` per task generation. Run each changed or added test file.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_dispatch.py tests/test_execution_host_manager_turn_queue.py tests/test_manager_journey_service.py`

**Regression at the level the friction appears:** Race two owner pumps against the same admitted task generation while a manager requests `run-worker`; exactly one launch occurs and all launch routes pass admission.

**XHARD invariant:** Every launch passes `admit_execution`, once per task generation.

**Plausible mistake:** The pump and a manager race into a second launch, or the pump bypasses the admission gate.

**Deletion budget:** Replace or extend the currently manager-triggered-only routine launch path; identify the obsolete trigger/helper removed in your report.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl` (including `--help`). Never wait or use background jobs you then wait on; run tests in the foreground. Don't change existing test assertions just to make them pass. A long test runs to completion (use a long timeout). **On Codex (Sol):** leave changes in the lab for the launcher to commit; do not push. Any sub-agent you start must use `spawn_agent` with `model: "gpt-6-luna"` and execute almost all exploration, edits and tests; keep design, invariant review, and final report for yourself. Each sub-brief must stand alone. If blocked, decide within the brief or report the question.

**When done:** Leave changes for the launcher to commit and report the commit, check results, deletion, sub-agent work and anything incomplete.

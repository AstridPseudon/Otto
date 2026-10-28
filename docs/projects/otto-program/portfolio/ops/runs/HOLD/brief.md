# Brief: HOLD (xhard, 0.5 focused days)

Title: Capacity follows processes; custody doesn't

**Outcome:** a hold whose process group is provably gone (pgid plus start time) stops costing capacity, but keeps its custody fence. A reused pid or pgid stays held.

**Why it matters:** a stale hold costs a slot forever and blocks activation and supervised restart (PLAN §13: "a supervised restart is refused while any hold exists"). The rule to keep: "process exit does not prove absence of a provider effect" (execution_host.py:1375), so the fence must stay.

**Your lab:** `~/Developer/otto-claude-host/labs/HOLD`, on branch `lab/HOLD`, from `canon/main` at `51fcfb9`. Work only here.

**Files you own:** the execution host module that holds `_capacity_holds` (find it: `grep -rn "_capacity_holds" src`; tasklist cites execution_host.py:277-312 for `restore_execution`) and a new `tests/test_capacity_holds.py`. You are the only writer of execution_host.py during this run.

**Do not touch:**
- `_eligible`, the capacity pool and heavy.py (POOL owns them, next);
- `production/`;
- any Store, `~/.otto` or `~/.codex`, and the running Otto service;
- `ottoctl` (do not run it, and never pass it `--help`);
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `_capacity_holds`, `restore_execution` (execution_host.py:277-312), the existing custody rules (test_worker_custody.py, test_status_owner_custody.py).

**Your check.** Make it green and keep everything else green:
- `dead_pgid_frees_capacity_keeps_fence` and `reused_pid_stays_held` in `tests/test_capacity_holds.py`; write them FIRST and show they fail on `canon/main`;
- the check command below, all green.

Check command: `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "HOLD check" -- env PYTHONPATH=src:tests /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_capacity_holds.py tests/test_execution_host_manager_turn_queue.py tests/test_execution_operations.py tests/test_execution_application.py tests/test_worker_custody.py tests/test_status_owner_custody.py tests/test_stopped_writer_conflict_custody.py`

Regression at the level the friction appears: a restart with a dead hold still lists its fence, and the capacity count after the dead hold is cleared is back to the pre-hold number.

**XHARD only:**
- invariant: capacity follows processes; custody doesn't. A dead group frees capacity and keeps its fence; a reused pid or pgid stays held.
- the plausible mistake to avoid: freeing the custody fence along with capacity, or trusting a reused PID (the pid is re-used but the start time differs; compare both).

**Deletion budget:** none. Name anything you remove, or say "none".

**When done:** commit to `lab/HOLD` (only the files you own; never `.brief.md`, `.worker.json` or `.worker.err`) and don't push. Report the commit, the red and green runs, what you deleted, and anything you couldn't finish.

# Brief: POOL (xhard, 1.25 focused days)

Title: One capacity pool (D3)

**Outcome:** one capacity pool for turns and heavy work, on Herzchen's `limits` units (kernel/limits.py: reserve, settle, release, uncertain, kept in the Store). Weights become units, with a manager reserve and heavy headroom. It replaces `_eligible`'s hard-coded 3 and 2, and the manager constructor cap (execution_host.py around 195 and 332-340). heavy.py's flock pool stays, for the bootstrap only.

**Also (carried from HOLD, c3880e0):** HOLD added `capacity_holds()`, `reconcile_dead_holds()` and `record_process_group(schedule_id, pid)` to the execution host, but nothing calls them, and `_eligible` still counts every fence entry. You do both:
- `_eligible` counts `capacity_holds()` (the fence minus holds whose group is provably dead), not the full fence;
- the wiring: `record_process_group` is called where the owner binds a native session (owner_runtime.py, next to `bind_native_session`), and `reconcile_dead_holds()` runs at restart. Also switch the `_capacity_holds` reads in `project_service.py` that only need capacity.

**Why it matters:** D3 is the one capacity pool. Without it, turns can starve heavy work, and dead holds cost slots forever.

**Your lab:** `~/Developer/otto-claude-host/labs/POOLX`, on branch `lab/POOLX`, from `canon/main` at `c3880e0`. Work only here.

**Files you own:** the execution host module (HOLD's changes are on canon now; you are its only writer during this run), `src/otto/agents/owner_runtime.py` (the wiring call only), `src/otto/portfolio/project_service.py` (the capacity reads only), and a new `tests/test_capacity_pool.py`.

**Do not touch:**
- heavy.py beyond its bootstrap role (no deletion of the flock pool; that is DELETE, later);
- the runner, custody and the host contract (HOSTKIT is rebasing its own work now, in its own lab; it owns `herzchen/fleet/hosts` and the host adapters);
- `production/`;
- any Store, `~/.otto` or `~/.codex`, and the running Otto service;
- `ottoctl` (do not run it, and never pass it `--help`);
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** kernel `limits` (reserve, settle, release, uncertain), reviewed_activation.py:282 and owner_bootstrap.py:971 (the allowance pools that already use it), HOLD's functions above.

**Your check.** Make it green and keep everything else green:
- `six_run_seventh_waits`, `manager_reserve`, `checks_run_while_turns_full` and `dead_waiter_frees_queue` in `tests/test_capacity_pool.py`; write them FIRST and show they fail on `canon/main`;
- the check command below, all green except the 12 pre-existing failures in `tests/test_stopped_writer_conflict_custody.py` (verified red on canon `51fcfb9`; not in the check command, so leave them out and say so).

Check command: `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "POOL check" -- env PYTHONPATH=src:tests /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_capacity_pool.py tests/test_capacity_holds.py tests/test_execution_host_manager_turn_queue.py tests/test_execution_operations.py tests/test_execution_application.py tests/test_worker_custody.py tests/test_status_owner_custody.py`

Regression at the level the friction appears: six turns running, a seventh waits; the manager still gets a slot with the turns full; a check runs with all turns occupied.

**XHARD only:**
- invariant: workers holding turns can always get their checks run; managers always get a slot.
- the plausible mistake to avoid: accounting that is right for one agent but lets turns starve heavy work (a turn unit taken without reserving headroom for a check).

**Deletion budget:** `_eligible`'s hard-coded 3 and 2, and the manager constructor cap. Name anything else you remove.

**When done:** commit to `lab/POOLX` (only the files you own; never `.brief.md`, `.worker.json` or `.worker.err`) and don't push. Report the commit, the red and green runs, what you deleted, and anything you couldn't finish.

**Working rules:** commit work in progress to `lab/POOLX` as you go instead of stashing (never run `git stash`), and never check out another commit in the lab. To show a test fails on canon, run it against canon's code without leaving your branch (for example, write the tests before changing the code, and run them then).

## How you work in this run: you lead, Haiku executes

You are the lead (Sonnet). **Delegate almost all execution** to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`; it runs Haiku 5.5 at high effort): exploring and reading code, writing the tests, making the edits, running the check and reading its output.

Keep for yourself only what needs judgment:
- the design: the pool's units, the reserve and headroom, and how the XHARD invariant above holds;
- writing each sub-brief;
- reviewing each sub-agent's result (`git diff`, the test tail) against the invariant, and sending it back with precise corrections when it's wrong;
- the final commit and the report.

Read code yourself only to check a claim or to make a decision a sub-agent couldn't. Small fixes of a line or two are fine to make yourself; anything larger goes to a sub-agent.

Each sub-brief is self-contained, because a sub-agent starts with no context and doesn't see this brief: the goal, the exact files and functions, what not to touch (copy the relevant lines from "Do not touch"), the command to run, and what to report back (a diff summary and the test output's tail). Run sub-agents in parallel only when their files don't overlap. If a sub-agent fails twice on the same step, sharpen the brief or split the step; do it yourself only as a last resort.

In your final report, also list each sub-agent you ran: what it did, and whether you had to correct it.

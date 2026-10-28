# POOL: three fixes before landing (resume message)

The program was paused after you finished f57688d; it's resuming now. Your work is good and the design is kept: the reserve filled first, and the FIFO heavy queue with dead-owner pruning. Before it lands, it needs the three fixes below. Re-read `.brief.md`, and the "XHARD only: you lead, Haiku executes" section of `~/Developer/otto-program/ops/brief-template.md`: from now on, delegate the execution to the `haiku-worker` sub-agent.

**0. Rebase first.** `canon/main` has moved to 9739a29 (or later). It now has TOOLING, TOOLING2, and SL9–SL12 from another session (Store leanness). SL12 changed `src/otto/portfolio/execution_host.py` (manager-ipc retention, about 25 lines). Rebase `lab/POOL` onto the current `canon/main` and keep both behaviours. Commit the resolution.

**1. Production startup.** You removed `manager_turn_limit` from `ExecutionHost`, but `install/controller/shared_operating_service.py:411` still passes `manager_turn_limit=3`, so the owner would fail at startup with a `TypeError`. No unit test starts it.
- Drop the argument there, and grep `src/` and `install/` for any other caller.
- Add a test that builds the execution host exactly as `shared_operating_service.py` does (compose it inertly on a temporary folder, then stop it), so a constructor change can't break startup again.
- `lab/POOLX` commit 97537fb made this edit; you may take it.

**2. The flaky test.** `tests/test_bounded_project_host.py::test_five_projects_share_slots_and_A_settles_while_B_waits` fails 4 runs in 5 on `lab/POOL` ("manager peak 3 ≠ 2"), and never fails on canon.
- A lead to check, not a conclusion: your fixture change in that file replaced `manager_turn_limit = 2` with `CapacityPolicy(turn_units=2, manager_reserve=1, heavy_headroom=1)` and the comment "the former 3-turn ceiling". If managers may take turn units plus the reserve, that admits 3 managers where the fixture used to allow 2.
- Find the real cause. Fix the code or the fixture's mapping of the old limit, not the assertion.
- Then run the file 10 times through `otto-heavy`: all 10 must pass.

**3. Placement (PLAN.md D14).** `CapacityPolicy`, `CapacityPool` and the ledger logic are a fleet mechanism, so they belong in Herzchen, not in Otto's `execution_host.py` (which grew by 434 lines).
- Move them to `src/herzchen/fleet/capacity.py`. The ledger stays the model's `limits` reservations. `ExecutionHost` keeps only the wiring: it builds the pool and calls it.
- Herzchen imports nothing from Otto: `tests/test_herzchen_boundary.py` must pass.
- `capacity-reservations.json` keeps state a second time, next to the Store's `limits` reservations. Remove it if the ledger can carry the same facts; otherwise explain in your report why it must stay.
- Pinning by polling `ps` every 0.25 s is weaker than wrapping the adapter's process observer, as `lab/POOLX` does (`owner_runtime._pin_process_group`, 97537fb). Take that approach if it fits, and delete the polling.

**Your check:** your four named tests; the file in fix 2, ten runs; the new startup test; `tests/test_herzchen_boundary.py`; and every test file that imports a module you changed, each run on its own, twice. Commit to `lab/POOL`, don't push, and report: the commits, the runs, the net lines by layer (`git diff --stat canon/main...lab/POOL -- src/herzchen src/otto`), and anything you couldn't finish.

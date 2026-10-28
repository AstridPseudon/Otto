# POOL: one fix before landing (second resume)

Your three fixes are in (f5c6baf), and the startup, boundary and bounded-host tests pass. One regression stops the landing.

**1. Worker turns are no longer pinned to their process groups.** You deleted `_pin_process_group` polling and wrapped the adapter's process observer. But the Claude adapter only calls that observer for managers with a caller socket, so a worker's process group is never recorded. Then when the worker exits, its capacity is never freed, and HOLD's rule (capacity follows processes) is broken for workers. No test catches it, so the gate wouldn't either.
- Fix it so every worker turn's process group is recorded through the same observer, without polling. If the adapter has to call the observer for workers too, make that change: say in your report which file and line.
- Add a test that fails before the fix: a worker turn's process group is recorded, and its reservation is released when the process is gone.
- Keep the manager path working. Keep the startup test and the boundary test green.

**2. The matrix failures (your report, last section).** For each file that still fails (`test_stopped_writer_conflict_custody`, `test_manager_correction_planning`, `test_manager_reentrant_ipc`, `test_external_owner_context`, `test_caller_context`, `test_worker_occurrences`):
- say whether its failing tests touch the code you changed, and which lines;
- don't edit the assertions. If a failure is caused by your change, fix the code. If it isn't, say so and give the evidence (the test's own path, not a guess).
- The landing gate compares each failure with canon. Don't try to compare by checking out another commit.

**Rebase first.** `canon/main` may have moved (HOSTKIT may be landing now). Rebase `lab/POOL` onto the current `canon/main` and commit the resolution, then do fix 1.

**Your check:** the new worker-pin test (red, then green); your existing named tests; `tests/test_herzchen_boundary.py`; every test file that imports a module you changed, each run on its own, twice. Commit to `lab/POOL`, don't push, and report the commits, the runs, and the net lines by layer (`git diff --stat canon/main...lab/POOL -- src/herzchen src/otto`).

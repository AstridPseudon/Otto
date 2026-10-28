# OWNERCLAIM resume 1

The landing gate found one NEW failure: `tests/test_fleet_custody.py::test_landed_lab_start_sweep_runs_after_owner_file_custody` (reproduced 3/3 on the candidate; BASE was 0/3). See `${TRANSFER_ROOT}/portfolio/ops/runs/OWNERCLAIM/land.log` and its `.gate/pair-1-*.txt` outputs.

Resume this same worker session in the same lab after the requested fresh canon rebase. Diagnose and fix this regression while preserving the brief's custody invariant, startup recovery order, and deletion budget. Run the focused check in the original brief and report the cause, fix, and results. Do not touch files owned by running ROLEIDS or the other active landing's task. Do not commit; the launcher commits on exit.

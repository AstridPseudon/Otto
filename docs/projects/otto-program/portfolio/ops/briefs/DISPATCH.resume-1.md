The landing sweep refused commit f063608 with two NEW failures, each reproduced 3/3 on the lab and 0/3 on BASE:
- `tests/test_admitted_transport_drain.py::AdmittedDrainTests::test_preparation_crossing_drain_preserves_exact_admitted_transport`
- `tests/test_herzchen_boundary.py::test_fleet_carries_no_otto_or_megado_names`

Repair both regressions within the existing DISPATCH scope and ownership in the original brief. Inspect the paired outputs in `ops/runs/DISPATCH/.gate/pair-1-*` and `pair-2-*` and the corresponding test failures. Add/adjust focused regression coverage as needed, run the exact task check from the lab brief, and report red-to-green evidence and any needed wider scope. Keep the changes limited to DISPATCH-owned files; do not alter unrelated expected behavior. The next landing can be requested after you exit. Stage 1 currently holds landing requests, so no landing should be requested until the orchestrator posts `stage 1 perch done`.

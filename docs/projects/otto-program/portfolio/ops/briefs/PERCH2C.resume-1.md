Resume the existing PERCH2C xhard task on the same lab and session. Preserve the current partial commit and finish the task row's stage-2 evidence assertions.

The Orchestrator answered your scope question: you may edit `ops/bootstrap/perch.sh` for every required stage-2 collection point: C's instruction edit and metadata-only write, the two owner `lsof` samples, and the owner lab-root listing before any harness step. ORPHANWORKER landed as `ac02366`; rebase on current canon before resuming. Preserve ORPHANWORKER's census lines in `perch.sh` and `perch_report.py` exactly.

For (d), do not use the projected timeline. Read landing and completion from the Store events already saved by the stage: each task's `work.assignment.dispatched`, landing observation, and completion in its assignment stream. If a required event is missing, report which one and assert on the rest. Add doctored-input unit tests for each assertion. Do not run stage 2; the Orchestrator runs it.

Re-read the current PERCH2C row and brief. Report each changed file, evidence source, test outcomes, and any missing Store event. Keep within the task outcome; do not alter ORPHANWORKER census behavior.

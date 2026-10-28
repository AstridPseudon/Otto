The landing gate reran `bash ops/bootstrap/perch.sh 2 --fake` against canon base `9d5baf5` and refused the lab tip `5e9b7f5`. Stage 2 failed:

- `store-matches-stage`: the Store contains a work task without an admitted revision.
- `admit-and-dispatch-ran`: scenario did not run against staging COMPOSEFLEET.
- C admission evidence lacks the stored plan review and an approved `prover_result`.
- Follow-on stage-2 assertions were skipped because operator task admission did not complete.

Inspect the latest gate report and raw staging artifacts under `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/` (the latest report is timestamped `20261017T114529Z`). Identify why the latest PERCH2B changes still do not admit/dispatch all stage-2 tasks against the fixed FDLEAK owner. Fix the harness within this task's scope, preserving truthful evidence and all existing assertions. Do not weaken checks, synthesize green observations, or change product code. Keep the fake-only launcher behavior and the prior pending-request protocol. Add focused regression coverage for the failure found.

Run the task's focused tests in the lab. Do not run `bash ops/bootstrap/perch.sh 2 --fake` in the worker sandbox; the landing gate runs it outside and returns its result. Leave changes for the launcher to commit and report the cause, fix, tests, and remaining staging verification. No other task is running; the brief's standing exclusions apply. Follow the existing brief's Codex xhard rules, including Luna subagents if any and long test timeouts.

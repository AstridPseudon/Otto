The landing gate refused `bash ops/bootstrap/perch.sh 2 --fake`. Resume the stage-2 harness work against the exact evidence below. Fix the task's harness causes, keep the scenario real, and do not synthesize green observations or weaken assertions. Keep the restart-persistent `home/run/operator-admission.jsonl` audit log; the 07:50Z Manager decision says to keep it here and allow exactly this file at rest.

Gate output: `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/.gate/check.txt`
Stage-2 report and raw evidence: `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T075816Z/report.md` and `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T075816Z/raw/`

The gate reports `store-matches-stage` failed because the Store contains a work task without an admitted revision; `admit-and-dispatch-ran` failed because the scenario did not run against staging COMPOSEFLEET. Consequently, admission did not complete, stage2-canary-valid and dependency ordering were skipped, and B/C admission logs lack the stored plan review and approved `prover_result`. Read the report and raw evidence to identify and repair the underlying harness issue. Preserve all valid assertions and the real operator admission path.

Run focused unit tests in the lab. Do not run `bash ops/bootstrap/perch.sh 2 --fake` in the worker sandbox; the landing gate runs it outside and will return its result. Leave the changes for the launcher to commit and report what changed and what remains.

The landing gate refused `bash ops/bootstrap/perch.sh 2 --fake` again.

Gate output: `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/.gate/check.txt`
This run's stage-2 report and raw evidence: `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T085653Z/report.md` and its `raw/` directory.

The gate reports `store-matches-stage` failed because the Store contains a work task without an admitted revision; `admit-and-dispatch-ran` failed because the scenario did not run against staging COMPOSEFLEET. B/C admission logs consequently lack the stored plan review and approved `prover_result`; downstream checks were skipped. ACTCRIT and PINCONTENT have landed, and the latest PERCH2B cleanup removed the owner setup/rebind stand-ins. Inspect this run's report/raw evidence and fix the stage-2 harness so it uses the product admission and dispatch path with the shipped product. Keep the scenario truthful: do not patch product code here, synthesize green observations, or weaken assertions. Preserve `home/run/operator-admission.jsonl` and its at-rest allowance.

Run focused unit tests in the lab. Do not run `bash ops/bootstrap/perch.sh 2 --fake` in the worker sandbox; the landing gate runs it outside and returns its result. Leave changes for the launcher to commit and report what changed and what remains.

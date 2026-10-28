The landing gate again refused `bash ops/bootstrap/perch.sh 2 --fake`.

Gate output: `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/.gate/check.txt`
Stage-2 report and raw evidence: `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T082004Z/report.md` and `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T082004Z/raw/`

This run failed before admission/dispatch: the Store contains a work task without an admitted revision, `admit-and-dispatch-ran` did not run against staging, and the B/C admission log assertions consequently failed. The orchestrator traced the product cause: `graph.admit` writes an admission metadata revision after activation, leaving the manager's task pin stale; dispatch rejects it. PINCONTENT is now a separate product task and will make pins survive metadata-only revisions by comparing `admission.content_digest`. For this harness task, inspect the raw evidence and keep the stage-2 scenario truthful. Preserve the manager rebind as a temporary stand-in until PINCONTENT lands; then remove it. Do not patch product code here or synthesize green observations. Keep `home/run/operator-admission.jsonl` and its at-rest allowance.

Run focused unit tests in the lab. Do not run `bash ops/bootstrap/perch.sh 2 --fake` in the worker sandbox; the landing gate runs it outside and returns the result. Leave changes for the launcher to commit and report what changed and what remains.

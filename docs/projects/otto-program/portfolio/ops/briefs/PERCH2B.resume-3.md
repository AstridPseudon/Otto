# PERCH2B resume 3: fix the refused stage-2 gate

Your previous xhard run committed `4eb64ee`. The landing gate has now run `bash ops/bootstrap/perch.sh 2 --fake` outside the worker sandbox and refused it. Fix the task's stage-2 failure using the gate evidence below, then update/unit-test the scenario with stubs. Do not run `perch.sh` in your sandbox; the landing gate runs it after you exit.

Gate output: `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/.gate/check.txt`

Relevant failures:
- Store snapshot: stage expected 6 events and 3 tasks but found 1 event and 1 task.
- `admit-and-dispatch-ran`: the scenario did not run against staging COMPOSEFLEET.
- Stage-2 owner setup exited rc 3, causing canary, dependency-order, unadmitted-revision, pool/reserve, worker-recovery, Store-snapshot and census checks to skip.
- `stage2-review-document`: project status did not contain exactly one stored `reviews/plan-review.md`.
- `operator-presence-approved`: admission logs A, B and C each lack one approved `prover_result`.

The complete gate log and stage report are at `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/land.log` and `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T070436Z/report.md`.

Trace why stage-2 owner setup exits rc 3 and why its registered/activated project does not produce the expected reviewed plan, approved presence admissions, dispatch, and six events/three tasks. Fix the scenario and its fake-only harness path so the full stage runs end to end. Keep the approving presence stub restricted to `--fake`; real `perch.sh 2` must retain the real prover. Admission must use the exact stored review-document ref/revision, and its `--review-ref` must name the review document (a different resource kind and id), not the task. Do not add a self-review refusal assertion or change product policy.

Run the relevant focused unit tests in the lab and report what you could not verify in the sandbox. The landing gate will rerun stage 2. Preserve the existing work and do not change the task's outcome or scope. Do not touch files owned by running tasks: REDS3 is active; inspect its brief/task-owned files before editing any overlap.

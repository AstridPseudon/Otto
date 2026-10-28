# FAILCLOSED landing resume: update admission stamp fixtures

The landing was refused with NEW test failures. Read the complete failing-file and failure list in `${TRANSFER_ROOT}/portfolio/ops/runs/FAILCLOSED/land.out` and paired evidence under `${TRANSFER_ROOT}/portfolio/ops/runs/FAILCLOSED/.gate/`.

The Orchestrator reproduced `tests/test_landing.py::test_forged_lab_result_ignored`: `LandingError: task payload is not admitted at its current revision` at `src/herzchen/fleet/landing.py:255`. FAILCLOSED now correctly treats an admission stamp without `reviewed_digest` as unadmitted. The hand-built test fixtures use the old stamp shape.

Fix the shared fixture writer(s) so stamps include `reviewed_digest = reviewed_content_digest(payload)`, preferably by calling the product's real writer or one shared helper. Keep the stamp check strict; do not weaken it. For every failing test file listed in `land.out`, inspect its paired evidence and determine whether it has this same stale-stamp cause before changing it. In the report, name every changed test file and give one line per file describing its specific cause and fix. Run every failing file from `land.out` after the changes and report results. Report sandbox-only failures separately.

Do not change production behavior for this fix. Do not run staging-owner tests in the worker sandbox. Leave changes uncommitted for the launcher.

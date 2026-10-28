# Resume: PINALL (xhard)

Apply the SEND BACK restore in `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-PINALL.md.sendback` after the requested rebase.

1. In `tests/test_capacity_pool.py`, restore the assertion that the registration call runs on `seen["owner"]`, observing the unchanged method with test-scoped profiling rather than patching the product method.
2. In `tests/test_claude_manager_admission.py`, remove the `_atomic_json` patch and wrapper. On the second process-factory invocation, create a collision at `.capacity-process-groups.json.tmp` after the initializer record exists, using the real writer's exclusive-create behavior. Preserve initializer-record, no-input, dead-group, failed-settlement, and restart assertions; remove the collision before restart and during cleanup.

Preserve all other PINALL outcome coverage and current committed work. Work only in the PINALL lab and directly needed files; do not edit production/, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside the lab. No other worker currently owns files. Run the task's original `Check command:` to completion, then `git diff --check`. Report exact results and remaining work. Leave changes uncommitted for the launcher. Never stash, switch commits, or run ottoctl. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

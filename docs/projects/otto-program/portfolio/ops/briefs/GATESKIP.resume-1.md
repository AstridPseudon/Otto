# Resume: GATESKIP (normal)

**Outcome:** Apply the current D19-GATESKIP SEND BACK restore and finish the real-owner manager journey migration without weakening its substantive checks.

**Decision:** Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-GATESKIP.md.sendback` first. In `tests/test_manager_journey_service.py`:

1. In the starvation journey, assert the terminal worker response has `outcome == "succeeded"`. Keep the event-based assertion that the report commits before release; do not restore an elapsed-time starvation expectation.
2. At the finish-task journey, save the actual `finish-task` response into `review.json`; keep the pending assertion on that response and preserve subsequent completion and continuation assertions.
3. Remove the pre-existing product-method substitutions identified in the decision: exercise real answer/route operations instead of `_help`, `_submit_worker`, and `_execution_control` patches; inspect persisted Store/Due and budget effects instead of `save_due` and `_journal` wrappers; seed historical acceptance and tampered-content fixtures instead of patching `_instruction_document`, `_retain_task_settlement`, and content `read`; persist unsettled Due state instead of mocking `read_due`. Preserve the refusal, retained-effect, budget, and no-repeat protections through real paths.

Use current line locations after the required rebase. Do not broaden scope beyond files directly needed for this outcome; report any additional file and why.

**Check:** Run the task's original `Check command:` from the lab to completion, then `git diff --check`. Report results, changed assertions, and any unfinished item. Leave changes uncommitted for the launcher. Never stash, switch commits, run ottoctl, or wait on background work. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

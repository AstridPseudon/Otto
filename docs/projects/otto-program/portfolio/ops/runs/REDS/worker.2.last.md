Updated [manager_capture_reconciliation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS/src/otto/agents/manager_capture_reconciliation.py) to remove the timestamp comparison and match admission identity to the exact native trace. The existing aborted-terminal and exact-turn checks remain intact.

The refused regression passes: **1 passed**. `git diff --check` passes.

The retained admission has `physical_session_id` and `observed_turn_id`, but no generation field. Generation is present on the same retained claim and authorization; both must match the exact native invocation’s `launch_context.generation`. The native session ID is present in the trace header and must match the admission session. For this fresh binding, `launch_context.native_session.id` is null; the trace header supplies the session identity. No timestamp fallback remains.

I did not rerun the full focused suite: it exceeded the 30-second command window on the earlier attempt, so it would not complete within this run’s bound. The change is uncommitted on the refused commit.
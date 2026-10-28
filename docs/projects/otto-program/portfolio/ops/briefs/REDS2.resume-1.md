Decided by the Orchestrator at 2026-10-17T05:32Z: keep production behavior unchanged. In `tests/test_project_folder_scale.py`, exclude these two inherited live-bound proofs from `ProjectFolderScaleTests` by setting each name to `None` in the subclass, with one comment explaining that this subclass raises the request bound on purpose and the proofs still run at the live bound through `ProjectFolderProof` itself:

- `test_large_folder_uses_bounded_child_requests_and_preserves_exact_bytes`
- `test_single_document_over_live_request_bound_is_rejected_before_creation`

Verify both proofs still pass via `tests/test_otto_open_release.py`. Run `tests/test_project_folder_scale.py` alone twice, to completion. Do not change production bounds or weaken assertions. Preserve all existing REDS2 work and its resolved `manager_journey_service.py` merge when rebasing; resolve any rebase conflicts without losing either side's required behavior.

Do not touch files owned by running STAGESETUP (`src/otto/hostctl/cli.py`, `tests/test_hostctl_cli.py`, config/register, staging bootstrap and related tests). A6 has exited; its lab is being landed. Keep the change focused on the scale subclass and its comment.

Before landing, the manager will set the lab's `Check command:` to plain pytest on the task's own tests (no `otto-heavy` prefix), per the manager rules.

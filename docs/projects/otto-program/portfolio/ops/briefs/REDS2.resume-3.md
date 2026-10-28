Resume REDS2 after landing effect 265 was refused for four NEW test failures:
- `tests/test_completion_project_refresh.py::CompletionProjectRefreshTests::test_exact_refresh_finish_and_replay_preserve_review_and_debit`
- `tests/test_completion_project_refresh.py::CompletionProjectRefreshTests::test_pending_pin_refresh_appends_proof_then_exact_completion_and_replay`
- `tests/test_completion_project_refresh.py::CompletionProjectRefreshTests::test_private_owner_evidence_is_read_only_for_exact_assessment_and_manager_approves`
- `tests/test_shared_manager_client_routing.py::SharedManagerClientRouting::test_ordinary_mutations_require_current_native_binding`

Inspect the gate's paired candidate/BASE outputs and fix only REDS2-caused behavior. Preserve the 05:32Z scope decision and current task changes. Do not touch files owned by running tasks; currently none are running. The previous landing sweep classified these four as NEW, so address them before handoff. Run focused task-relevant checks, `git diff --check`, and report the resulting state. Leave commit to the launcher.

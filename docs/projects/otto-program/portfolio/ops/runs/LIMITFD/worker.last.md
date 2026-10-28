Implemented owner scoped `LimitService` reuse. `role_runtime()`, `manager_assessment()`, and `create_manager_assessment_pool()` now share one service per owner.

The 200 call regression failed on the baseline with **+400 descriptors** and passed after the fix. The requested test command passed (**2 passed**); `git diff --check` passed.

Changed files: `owner_bootstrap.py` and `test_completed_occurrence_readiness.py`. No extra files. The stage 2 `--fake` check was not run. No commit or push.
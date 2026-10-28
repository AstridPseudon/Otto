The reported check log ran at 00:08, before the launcher’s 00:17 commit (`e452c60`) containing the rebase capture fix. On the current clean lab branch, all three reported regressions pass; `test_reworkwire.py` is 8/8. No further code change was needed in this resume.

The exact focused command yielded 7 passed, 39 passed with 23 subtests, 8 passed, and 28 passed with one failure. That failure is `sandbox-exec: sandbox_apply: Operation not permitted` in the worker sandbox.

I did not land or commit. **A fresh outside-sandbox check on `e452c60` is still required before landing.**
Removed the elapsed-time cutoffs from stage‑2 admission, dispatch, and fake-worker kill waits. They now poll for evidence and stop if the staging owner exits. The stand-in socket client also waits for its reply without a timeout. The regression covers every `stage2_*` function with a wait loop and checks doctored deadlines.

The focused `Stage2OwnerBootstrapTests` passed: **15 passed, 12 subtests passed**. The full `tests/test_perch.py` run completed with **69 passed and 15 failed**; the failures came from sandbox `PermissionError` when tests tried to run `ps`. `bash -n` and `git diff --check` passed.

I did not run the stage‑2 `--fake` journey because it requires the outside-sandbox check. Only the three owned files were changed; no other files were needed.
# CLIARGS resume: finish the canon rebase conflict

The CLIARGS commit is currently being rebased onto canon/main 82b1976. The rebase stopped with one conflict in `tests/test_shared_manager_client_routing.py`; the two source files are staged. Resolve the test conflict while preserving both the CLIARGS end-to-end argument-forwarding coverage and the current canon assertions. Do not discard either side's intended behavior. Then run the task's requested check from `ops/briefs/CLIARGS.brief.md` and `git diff --check`, inspect `git status`, and report the resolution and test result. Leave commit/rebase completion to the launcher.

Do not touch files owned by running tasks: TESTPATCH, LANDPROOF, LABPIN, RECEIPTFENCE, REALSTAGE3. Do not touch production/, Stores, ~/.otto, ~/.codex, or files outside this lab. Do not stash or check out another commit. On Codex, leave the resolved work for the launcher; do not commit or push. Run the full check to completion with a long timeout.

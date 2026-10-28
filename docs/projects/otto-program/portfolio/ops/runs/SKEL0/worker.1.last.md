**SKEL0 is not complete.** HEAD remains `0a97263`; I did not commit. The lab has three uncommitted file changes.

I changed the stage 4 report assertion so a note cannot substitute for owner evidence: it now requires admission, task admission, dispatch, and the worker/check/landing/cleanup events. I added a seeded dispatch-evidence fault and tests showing the owner assertion passes with the complete event chain, fails when dispatch evidence is removed, and fails for direct fake worktree events. These are **synthetic assertion tests**, not proof of an owner-driven run.

Checks run:

- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch_stage1.py -k 'StageFour'` — **7 passed, 19 deselected**. Includes seeded owner-dispatch and conflict red/green assertions.
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch_stage1.py tests/test_perch_timeline.py` — **34 passed, 20 subtests passed**.
- `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py -k 'clean_run or each_kind_fails or missing_timeline_event or store_gap or failed_check or store_matches_stage or staging_at_rest_clean or lifecycle_that_did_not_run or report_has_every_section or fatal_error_is_not_exit_0 or init_args_expand'` — **11 passed, 10 deselected, 22 subtests passed**.
- `bash -n ops/bootstrap/perch.sh ops/bootstrap/staging.sh` — **passed**.
- Python compile for `perch_report.py`, `fake_worker.py`, and `test_perch_stage1.py` — **passed**.
- `git diff --check` — **passed**.

The earlier full check command, `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_stage1.py tests/test_perch_staging.py tests/test_perch_timeline.py`, reported **49 passed, 18 failed, 42 subtests passed**. The failures hit `PermissionError: Operation not permitted` launching `ps` in census, perch, and staging startup. I did not retry staging or other host operations.

No stage 4 perch report exists. The full fake stage 4 perch and the real Claude worker journey remain unrun; neither has been proven. The runner currently lands fake worktrees directly, while stage 4 without `--fake` is refused before a real journey can run. The existing owner fleet code also requires an admitted task with `otto.plan` repo/branch metadata and an activated, dispatch-capable owner project; the canary config does not supply that journey.

**Manager follow-up:** the tasklist is outside the permitted edit scope, so I did not file rows there. The existing `DISPATCH` and `COMPOSEFLEET` prerequisites need an orchestrator decision and completion before SKEL0 can prove owner admission and automatic dispatch. The manager should also record the missing owner-project/activation wiring as a breakage task. No breakage tasks were filed in this lab, and no real-run perch report should be represented as passing.
The fake-run regression came from a mode-value mismatch: `perch.sh` sets `FAKE=1`, but the stage 4 task guard compared it to `"true"`. That skipped both fake tasks, leaving no task timeline events; the conflict task never created a lab, so its cleanup event was absent too.

I updated the guard to test whether fake mode is set. The report now skips the owner-driven assertion in fake mode, because that harness does not exercise owner admission or dispatch. In real mode, the owner-event assertion remains required. The synthetic tests cover both behaviors.

Changed files: `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, and `tests/test_perch_stage1.py`. Canon’s stage 2 code remains intact; there are no conflict markers or unresolved paths, and the worktree has only these three modified files. I did not edit `tests/test_perch.py` or write Git metadata.

`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch_stage1.py -k 'StageFour'` — **7 passed, 19 deselected**. Shell syntax, Python compilation, and `git diff --check` also passed. I did not run tests that start staging owners, as requested; the landing gate should run those.

The owner-driven stage 4 journey and real Claude journey remain unproven. No commit was made.
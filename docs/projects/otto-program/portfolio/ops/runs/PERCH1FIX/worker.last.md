Implemented the stage 1 canary and Store-backed assertions in the four owned files. The canary now has three `otto.plan` tasks with A→B, and its edit changes A’s title and B’s size and adds C→B. The runner reads the saved project through owner-lane `show`, snapshots typed Store records and retained revisions, checks persisted edits, execution events, stage counts, and row growth.

**Focused stage 1 check:** 19 passed, 20 seeded-fault subtests passed. Each seeded fault made only its matching assertion fail. Shell syntax, Python compilation, and `git diff --check` passed.

The full requested suite was also run. It reported 41 passed and 16 failures: process census and stage 0 runner tests hit `PermissionError: Operation not permitted` when invoking `ps`; three staging tests timed out starting Otto. Those checks need an unrestricted sandbox at the landing gate.

I did not run `perch.sh 1` against staging because it would modify state outside the lab. That real staging pass remains unverified. No commit was created; the launcher commits the lab changes.

Replaced the response-only `tasks-are-typed-records` assertion with Store-backed typed-record and persisted-edit checks. Also replaced the `read <project_id>` read-back with owner-lane `show project`.

Changed files: [project.json](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1FIX/ops/bootstrap/canary/project.json), [perch.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1FIX/ops/bootstrap/perch.sh), [perch_report.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1FIX/ops/bootstrap/perch_report.py), [test_perch_stage1.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH1FIX/tests/test_perch_stage1.py).
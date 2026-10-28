The six gate failures shared one cause: stage-1 saves send `--actor owner`, which OPERATOR-ADMIT rejected because the configured owner principal has a different name. The owner lane now resolves that legacy save selector to its bound owner actor. The stored project still has the operator as creator and the configured owner as curator; host-lane use of `--actor owner` remains denied.

- `tests/test_perch_stage1.py`: **19 passed, 20 subtests passed**
- Brief’s exact focused check: **33 passed, 1 skipped**
- `git diff --check`: passed

Only [hostctl/cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPERATOR-ADMIT/src/otto/hostctl/cli.py) and [test_operator_admission.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPERATOR-ADMIT/tests/test_operator_admission.py) changed; no extra files or A6-owned files were touched. Changes are uncommitted for the launcher.
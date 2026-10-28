Implemented the status, admission, and scope changes:

- Owner status now pairs each retained hold ID with its project, role, settling command, and next action.
- Root-direction adoption checks obligations for the projects joined to that root. A hold in project A no longer blocks adoption for project B.
- `ottoctl project status` reports `readmission needed` and changed fields, such as `instructions`, when an admitted task’s content changes.
- The stage-2 no-launch assertion now requires that reason and changed field.

The cross-project regression failed against the starting implementation because the root-direction gate had no project scope. The targeted tests now pass: **36 passed, 17 subtests passed**. `git diff --check` is clean.

The requested full pytest command completed with **92 passed, 78 subtests passed**, and sandbox-related failures: `ps` execution is denied, which breaks the Perch census and dependent run tests. I did not separately run the stage-2 `--fake` check.

Additional files changed because they directly own required behavior or compatibility:

- [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/HOLDSTATUS/src/otto/hostctl/cli.py) computes changed fields for project status.
- [root_direction_client.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/HOLDSTATUS/src/otto/portfolio/root_direction_client.py) passes the root’s project scope to the gate.
- [perch_report.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/HOLDSTATUS/ops/bootstrap/perch_report.py) contains the stage-2 snapshot assertion.
- [test_root_direction_client.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/HOLDSTATUS/tests/test_root_direction_client.py) updates its host stub for the scoped call.

Changes are uncommitted for the launcher.
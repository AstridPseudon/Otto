Implemented the three fail-closed changes:

- Admission stamps without `reviewed_digest` no longer admit content.
- Missing operator identity no longer falls back to the caller or machine account. Project creation refuses when identity is absent; owner compositions used for non-creation paths can still omit it.
- `MacWriteScope` rejects relative exec allowances.

The three regressions failed on the `canon/main` base, then passed after the changes. The requested suite finished with **69 passed, 5 skipped, and 3 failures**. All three failures are manager-launch tests blocked by the sandbox’s `sandbox_apply: Operation not permitted` during real macOS fence preflight. The focused regressions passed, as did three targeted owner-fixture checks.

Additional files changed and why:

- [config.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/src/otto/hostctl/config.py): reject missing install-time operator identity.
- [test_hostctl_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_hostctl_cli.py), [test_hostctl_project_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_hostctl_project_service.py), [test_clean_close.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_clean_close.py), and [test_transcript_once.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_transcript_once.py): supply explicit operator identities to installation fixtures.
- [test_execution_application.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED/tests/test_execution_application.py): supply an operator identity to its owner fixture.

No commit or staging run was performed.
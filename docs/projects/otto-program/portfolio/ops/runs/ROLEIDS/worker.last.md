Implemented exact principal collision checks at installation load, host admission, manager registration and activation, and worker preparation. Same-kind host replay remains intact, and worker names remain unrestricted unless they exactly match a reserved principal.

**Checks**

- Requested suite: **61 passed, 21 skipped, 2 failed**. Both failures are existing admission dry-run checks blocked because `sandbox-exec` is present but this environment denies `sandbox_apply`.
- Focused collision checks: **5 passed, 1 skipped**, with 5 subtests passed. The activation collision check also passed after the final ordering adjustment.
- `git diff --check` passed.
- **Canon red run not performed:** the lab brief’s referenced `projects/program/tasklist.md` is absent, and the working rules prohibit checking out another commit. I left the lab on its current revision.

**Files changed**

- [config.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/config.py), [service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/service.py): validate distinct installation principals and reject collisions on new host admission.
- [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/cli.py), [register.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/register.py): reject reserved manager principals before registration or activation writes.
- [manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/portfolio/manager_journey_service.py): reject reserved worker principals before preparation.
- [test_hostctl_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/tests/test_hostctl_cli.py), [test_manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/tests/test_manager_journey_service.py): add collision entrance coverage.

`cli.py` and `test_manager_journey_service.py` are direct additions needed to cover the actual CLI and worker preparation boundaries. No commit or push was made.
Resolved the file conflict in the working tree. The round-1 `seed_historical_instruction_acceptance` helper and ROLEIDS worker-collision test are both present; I removed only the conflict markers. **No assertions were changed**—the collision test was added alongside the preserved helper.

I reviewed the full rebased diff. It covers:

- Pairwise owner, operator, and host principal validation at installation load in [config.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/config.py).
- Collision rejection on new host admission in [service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/service.py), while retaining same-kind replay.
- Manager principal validation before registration or activation writes in [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/cli.py) and [register.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/hostctl/register.py).
- Worker collision validation before preparation in [manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/src/otto/portfolio/manager_journey_service.py), preserving distinct nonreserved assignment-scoped names.
- Entrance coverage in [test_hostctl_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/tests/test_hostctl_cli.py) and [test_manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROLEIDS/tests/test_manager_journey_service.py).

The complete diff is **7 files, 141 insertions, 8 deletions**. `git diff --check` passed, and no protected Do not touch paths appear in the changed-file list.

The exact requested check completed: **83 passed, 1 skipped, 2 failed, 7 subtests passed**. Both failures are the admission dry-run tests: their `sandbox-exec` preflight is denied with `sandbox_apply: Operation not permitted`.

**Blocker:** Git still reports `tests/test_manager_journey_service.py` as unmerged (`UU`) because staging the resolved file failed: the Git index is outside the writable lab, and creating its `index.lock` was denied. The conflict markers are gone from the file, but the index could not be updated. I did not commit or push.
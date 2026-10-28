Implemented the status ceiling using `CapacityPolicy.total_turn_units` and added the default and configured policy regression. Default status now reports `(8, 6, 6)`; the configured case reports `(5, 4, 4)`. The test also checks those limits against `admits_turn`.

- **Canon red:** the new regression failed on both policies against the existing `canon/main` worktree, as expected.
- **Lab green:** the requested check passed: `6 passed, 2 subtests passed`.
- `git diff --check` passed.

Files changed: [capacity.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STATUSCAP/src/herzchen/fleet/capacity.py), [project_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STATUSCAP/src/otto/hostctl/project_service.py), [test_hostctl_project_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STATUSCAP/tests/test_hostctl_project_service.py).

No blockers.
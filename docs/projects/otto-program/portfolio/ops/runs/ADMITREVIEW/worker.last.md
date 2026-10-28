Implemented exact review revision resolution in [module.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ADMITREVIEW/src/herzchen/domains/work/module.py:536). Ordinary reviews must resolve through `get_revision` with an exact ref match. DAT reviews resolve through their immutable revision identity and verify the stored document and revision. Resolution happens before the already-admitted check; the original exact ref is stamped only after resolution.

Added regressions in [test_admit.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ADMITREVIEW/tests/test_admit.py:113) for refusing a missing pin without a stamp, admitting a retained ordinary revision after the head advances, and admitting a retained DAT revision after its document head advances.

- **Pre-implementation red:** the focused command failed on the missing-pin regression; 20 passed, 10 subtests passed.
- **Post-implementation green:** the same command passed; 21 passed, 10 subtests passed.
- `git diff --check` passed. No existing assertions changed; no D19 assertion decision was needed. No blockers.
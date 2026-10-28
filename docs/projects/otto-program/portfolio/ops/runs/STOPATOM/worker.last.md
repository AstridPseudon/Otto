Implemented atomic stop publication in [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STOPATOM/src/otto/hostctl/cli.py): `cmd_service_stop` now uses `lanes.atomic_json` to publish the timestamp and normalized closure together. The response shape is unchanged, and no caller signatures changed.

Added the publication and lifecycle regression in [test_compose.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STOPATOM/tests/test_compose.py). It checks that the owner keeps serving while publication is paused, then records the complete reason and expected return in draining and closed status.

**Checks:** The pre-change, canon-equivalent implementation failed the new regression; after the fix, the requested module passed: `20 passed in 49.17s`. `git diff --check` passed.

**Prework adjustment:** I kept the filesystem replacement observer active through the owner join. In the first post-fix run, the prework’s shorter observer window ended before draining and closed status replacements occurred, so it captured neither transition. The extended window made those assertions reliable.
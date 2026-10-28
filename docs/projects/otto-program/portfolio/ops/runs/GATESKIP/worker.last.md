**Incomplete; do not land this workspace yet.** The skip-only gate regression is implemented, but the required combined check still fails in the manager journey suite.

- **Canon red:** The new gate regression failed before the changes: a skip-only check landed, and a separate skip-only sweep also landed.
- **Gate green:** The regression passed after the plugin and landing-gate changes.
- **Final check:** With `OTTO_OWNER_SERVICE_TEST_FIXTURE` unset, the required command completed with **88 passed, 6 failed, 0 skipped**. The manager tests execute, but these six remain red: deferred intermediate finish, corrective task closeout, nested review during parent drain, retained worker journey, unknown operation profile, and unknown-send replay.
- **Changes:** Updated [otto_gate_exit.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/GATESKIP/ops/bootstrap/otto_gate_exit.py), [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/GATESKIP/ops/bootstrap/land.sh), both requested test files, and added [D19.md](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/GATESKIP/D19.md). No files were deleted. `git diff --check` is clean.
- **Commit:** No commit was created, as instructed. Current `HEAD` is `97f5f9702c9efbc6ccdc62c1820804590aea9b34`.

The remaining blocker is the in-repo product fixture’s manager-turn integration: several journeys still disagree with the maintained caller/replay behavior, and one owner-thread assertion sees two threads.
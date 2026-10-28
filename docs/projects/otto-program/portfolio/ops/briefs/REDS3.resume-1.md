# REDS3 resume-1

Remove every `MacWriteScope.preflight` patch you added (5: two in `tests/test_hostctl_cli.py`, three in `tests/test_hostctl_serve.py`), restoring those tests' original structure. A failure that only happens in your sandbox (`sandbox_apply: Operation not permitted`) isn't a red to fix: the gate runs those tests outside the sandbox. Keep your other changes (the manager-loop fake following admission and dependencies, the occurrence pin in `manager_journey_service.py`, the consumption test's import and fake, the correction-planning assertion). Don't rerun the two hostctl files in the sandbox.

Do not touch files owned by other running tasks. On Codex, leave changes for the launcher to commit; do not work around the read-only `.git`. Report what changed and the checks you could run. The landing gate will run the task check outside your sandbox.

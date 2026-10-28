I changed [custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/INTEG-PROCLIFE-PL1/src/herzchen/fleet/custody.py:221) so an unreadable **zombie** leader does not keep an empty group uncertain. A live leader with unreadable birth remains uncertain. Two new [regressions](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/INTEG-PROCLIFE-PL1/tests/test_fleet_custody.py:1341) cover latch cleanup before and after signalling; both pass. Only these two owned files changed, and `git diff --check` is clean.

The lab is already based on `canon/main` 8edc104. The requested rebase reported “up to date” but could not write its Git bookkeeping refs. The requested commit is likewise blocked: `git add` cannot create `.git/index.lock`, and I did not work around the read-only Git area.

Verification remains incomplete in this sandbox:

- Custody check: **30 passed, 8 failed** where `ps` or `sandbox-exec` is denied.
- `tests/test_runner.py`: **11 passed, 4 failed**; the reported latch test still cannot use the live census here.
- The targeted staging test timed out during `staging.sh up` after 300 seconds, before reaching the reported cleanup assertion. I did not run the full staging file after that timeout.

The launcher needs to commit these worktree changes and run the two reported tests and custody check outside the sandbox.
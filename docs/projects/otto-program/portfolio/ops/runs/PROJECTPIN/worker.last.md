Operating setup validation now accepts a newer project revision when trusted owner reads prove its setup content is unchanged. The same revision and content check applies to assignment and mandate pins; changed content is refused with the field name and `operating-setup activate` in the reason. The existing task content proof is preserved.

Additional files changed:

- [owner_readers.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROJECTPIN/src/otto/portfolio/owner_readers.py): supplies retained content proof for project, assignment, and mandate pins.
- [herzchen_binding.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROJECTPIN/src/otto/portfolio/herzchen_binding.py): permits an exact retained read of a granted project revision.
- [test_operating_setup_pin_content.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROJECTPIN/tests/test_operating_setup_pin_content.py): covers activation, C’s edit, A/B launches, and changed scope refusal.
- [test_fresh_worker_admission.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROJECTPIN/tests/test_fresh_worker_admission.py): covers assignment and mandate pins. Ordinary worker start and dispatch **do not advance either revision**.
- [test_manager_service_continuation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PROJECTPIN/tests/test_manager_service_continuation.py): updates the lifecycle-only project revision expectation.

Focused checks: **84 passed, 26 subtests passed**; `git diff --check` passed. No commit was made, as instructed. Lab base commit: `ac02366`; the launcher commits on exit.

**Stage-2 status:** I did not start a staging owner in this sandbox. The real-owner fake-provider regression passes, but the existing `perch.sh 2 --fake` scenario does not yet perform *admit C → edit C → admit A/B*. The landing gate needs to run that sequence outside this sandbox and verify A/B launch; the stage-2 regression remains unverified.
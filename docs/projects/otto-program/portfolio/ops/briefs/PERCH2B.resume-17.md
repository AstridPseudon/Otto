# PERCH2B resume-17: stage-2 scenario admission completes but dispatch does not run

The latest landing gate ran `bash ops/bootstrap/perch.sh 2 --fake` at `ops/perch/2/20261017T122031Z/`. The report says A, B and C each have an initial `pending` request and a retained `admitted` receipt. `store-matches-stage`, `stage2-review-document`, and `operator-presence-approved` pass. But `admit-and-dispatch-ran` fails with `scenario did not run against staging COMPOSEFLEET`; every downstream stage-2 assertion is skipped because operator task admission did not complete. Read the raw artifacts, scenario log and stage-2 call path to identify why the scenario reports admission incomplete despite those admitted retained receipts. Fix the concrete harness/call-site cause within PERCH2B's row outcome, and add/update a focused regression if appropriate. Do not add waits/retries or change unrelated owner behavior. Preserve A/B/C order and the existing pending protocol.

Use the latest report and evidence under `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T122031Z/`. The landing gate runs stage 2 outside the worker sandbox; do not try to run it here. Run focused tests only, plus `bash -n` for changed shell scripts and `git diff --check`. Report the cause, exact call sites/evidence checked, fix, checks, and anything unresolved.

**Do not touch:** files owned by another running worker (none known); `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**On Codex:** leave changes for the launcher to commit. Any sub-agent must be `spawn_agent` with `model: "gpt-6-luna"`. Long checks must run to completion; do not wait/poll.

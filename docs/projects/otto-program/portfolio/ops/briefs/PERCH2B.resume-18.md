# PERCH2B resume-18: stage-2 admissions pass but the owner pump never dispatches A

The latest stage-2 run is `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T122031Z/`. A, B and C have `dispatch: {state: admitted, reason: null}` after 180 seconds; review document and operator presence pass. `raw/stage2-owner-log-tail.txt` and the staging log (around line 9480) contain no dispatch error. The current resume-17 is already running with the previous investigation; after it exits, rebase and resume with this request.

Read the automatic dispatch path on current canon, including AUTODISPATCH/AUTODISPATCH2's pump, FDLEAK's fence on persistent prelaunch failures in `src/herzchen/fleet/dispatch.py`, `dispatch_held`, and whether the pump needs the stage manager started or a schedule due. Identify the exact condition holding A back and cite file:line plus run evidence. If the harness skips a step the product requires (starting the manager or making a schedule due), add it. If the product fails to dispatch an admitted, ready task, or silently fences it with `reason: null`, stop and report that with evidence; do not make an unrelated product change. Do not land PERCH2B until this question is answered.

Preserve PERCH2B's row outcome and scope. Do not add waits or retries. Check the task's own focused tests, `bash -n` for changed shell scripts, and `git diff --check`; do not run the staging scenario in the worker sandbox. Report the pump condition, exact code and staging evidence, any harness fix, checks, and unresolved points.

**Do not touch:** files owned by another running worker (none currently known); `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**On Codex:** leave changes for the launcher to commit. Any sub-agent must be `spawn_agent` with `model: "gpt-6-luna"`. Long checks must run to completion; do not wait/poll.

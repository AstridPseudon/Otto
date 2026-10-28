# Brief: PERCH2B fresh Sol handoff (xhard, 0.5 focused days)

**Outcome:** Complete the 12:25Z pump-path investigation for PERCH2B, using the existing lab and preserving its launcher-committed work. Establish with code and run evidence which condition gates automatic dispatch after A/B/C admission. Only if the staging harness omitted a required setup step, add that step and its focused regression; if the product silently fences or never dispatches an admitted ready task, report that with evidence and stop.

**Why it matters:** Stage 2 must prove owner dispatch on staging; stage 3 and the walking skeleton depend on that proof.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B`, branch `lab/PERCH2B`. Continue in this existing lab and preserve all its commits and changes. Do not create a replacement lab.

**Layer:** Otto product, staging and bootstrap tooling. New code belongs in the staging/bootstrap layer unless evidence identifies a product defect.

**Compact handoff (read these first):**
- Existing task brief: `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/.brief.md`.
- Previous worker report: `${TRANSFER_ROOT}/portfolio/ops/runs/PERCH2B/worker.17.last.md`.
- Latest stage-2 report: `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PERCH2B/ops/perch/2/20261017T122031Z/report.md`.
- Orchestrator question (12:25Z): A, B and C were admitted and have `dispatch: {state: admitted, reason: null}` after 180 seconds, but the owner never launches A and logs no dispatch error. Trace AUTODISPATCH/AUTODISPATCH2's pump; FDLEAK's persistent prelaunch-failure fence in `src/herzchen/fleet/dispatch.py`; `dispatch_held`; and whether the pump requires the stage manager to be started or a due schedule. Identify which condition holds A back with file:line and evidence from the run. If the harness skipped a required manager-start or due-schedule step, add it. If product behavior silently fences or fails to dispatch an admitted ready task, report that outcome and evidence without inventing a harness workaround.
- Orchestrator update (12:31Z): the thread reached 125M input tokens over 17 runs, so this must be a fresh Sol session, not a resume. The previous run's apparent 180-second dispatch timeout was caused by the fake launcher's substring match: A's owner brief included “Canary dispatch C”, so A could enter C's indefinite hold. Worker 17 fixed this by selecting C from the assigned task's owner brief and split admission and dispatch failure reporting. Preserve that work. Staging gate has not rerun it yet.

**Files you own:** `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_fake_claude.py`, `tests/test_perch.py`, plus any directly required staging/bootstrap caller or test. Do not touch files owned by another running worker (none currently). Do not edit product code unless the evidence demonstrates a product defect and you can cover it with a focused regression.

**Other files:** You may edit another file the outcome directly requires, except files under “Do not touch”; explain each in your report. Do not stop to ask for a file.

**Do not touch:** `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** Preserve the stage-2 setup and operator admission path. Worker 17's uncommitted-at-report-time changes are being committed by the launcher on exit; inspect the current lab diff before editing and build on it. Never revert the exact-task fake worker selection or the separate admission/dispatch error reporting.

**Your check:** Add/adjust focused regression coverage for any harness change. The landing gate will run `bash ops/bootstrap/perch.sh 2 --fake` against staging; the worker sandbox cannot run this staging check. Do not synthesize green observations or weaken assertions. Report code paths and line references, run evidence, and anything incomplete.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** An admitted, ready canary task either dispatches through the real owner pump under the required staging setup, or the report identifies the exact product fence/failure with evidence.

**Working rules:** Never run `git stash`, check out another commit, or use a clone of the live Store/install. Never wait with a monitor, sleep loop or background job; run checks in the foreground. Keep staging isolated under its existing staging root. Give long checks a long timeout. If a test fails with `sandbox_apply: Operation not permitted`, report it for the landing gate.

**On Codex:** You cannot commit; leave work in the lab for the launcher to commit. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD invariant:** Preserve the owner boundary: the canary must not stop the owner or edit owner files. The plausible mistake is to change product dispatch or admission behavior before proving which dispatch prerequisite is absent.

**When done:** Leave changes for the launcher to commit. Report the commit, focused check results, stage-2 report path, evidence for the pump gate, and anything incomplete. Do not land; the manager will coordinate the landing after this investigation is answered.

# Brief: DISTURB (xhard, 1.0 focused days)

**Outcome:** Add the ordinary stage-2 disturbances that caused the defects, as steps evaluated by the invariants: restart the owner during a worker turn (custody, settlement, holds after restart); refused landing (work retained, fence settled, next task runs); two landings requested back to back; activate a second project while the first has work in flight. Include the remaining stage-2 coverage-map disturbances (failed launch and operator denial). Each disturbance must be an actual product-path function in `perch.sh` with its own evidence capture, and stage 2 `--fake` must run every disturbance with all six invariants holding after each step. Do not use sleeps; wait on product-observable state. Add doctored-defect regressions so the named invariant fails when a disturbance is broken.

**Why it matters:** These journeys show that ordinary interruptions preserve the product's recorded custody and settlement guarantees.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISTURB`, on branch `lab/DISTURB`, from current `canon/main`. Work only here.

**Layer:** Otto product. The stage scenario lives in the Otto bootstrap harness.

**Files you own:** `ops/bootstrap/perch.sh`, `tests/test_perch.py`.

**Other files:** You may edit another file only when the outcome directly requires it, except files under Do not touch; explain each added path in your report.

**Do not touch:** Files owned by active tasks: `src/otto/hostctl/cli.py`, `src/otto/hostctl/config.py`, `src/otto/hostctl/supervision.py`, `tests/test_hostctl_cli.py`, `tests/test_compose.py`, `tests/test_hostctl_project_service.py` (BOOTCFG); `src/otto/portfolio/intake.py`, `src/otto/portfolio/herzchen_binding.py`, `src/otto/portfolio/project_folder.py`, `tests/test_project_folder_scale.py`, `tests/test_portfolio_shared_documents.py` (XFERMAP). Also do not touch `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** Stage-2 scenario and fault/evidence paths in `ops/bootstrap/perch.sh`; the stage-2 journeys and invariant checks in `tests/test_perch.py`. Preserve the existing evidence-driven invariant structure and use the product's real observable state.

**Your check:** Add disturbance journeys and a defect-seeded regression for every disturbance, covering all six invariants after each step. Run the task's focused test file to completion; do not run the full suite or a stage run in the sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`

**Regression at the level the friction appears:** Run stage 2 `--fake` through restart, refusal, queued landings, and overlapping project activation; observe effects from captured owner evidence. Each seeded defect must fail its named invariant.

**Invariant:** Each disturbance exercises the real product path, and its effect is observed through recorded evidence. **Plausible mistake:** Simulating the disturbance by writing expected state directly or waiting on a timer, so the invariant checks the harness instead of the owner.

**Deletion budget:** Replace any existing stage-2 omission or harness-only shortcut that serves the same disturbance-coverage purpose; identify it in your report.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Never wait or poll; use observable product state, not timers. Long tests must run to completion with a long timeout. Do not weaken tests to pass in the worker sandbox. Tests that need `ps`, nested sandboxing, or a staging owner must be listed for outside verification; never run a staging owner in the worker sandbox.

**On Codex:** You cannot commit because `.git` is read-only. Leave work in the lab for the launcher to commit. Any sub-agent you start must use `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: lead, cheaper model executes.** Delegate almost all execution to Luna sub-agents with `spawn_agent` and `model: "gpt-6-luna"`; keep the design, invariant review, and final report for yourself. Sub-briefs must name exact files, functions, constraints, command, and expected report. Run them in parallel only when their files do not overlap. Never commit or push.

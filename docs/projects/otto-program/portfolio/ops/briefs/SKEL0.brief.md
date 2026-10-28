# Brief: SKEL0 (normal, 0.5 focused days)

**Outcome:** Complete the early walking skeleton (stage 4 of PLAN.md §16) on the staging Otto (D17), never on a clone of the live Store or the live install. Have the canary project exercise the full path through Otto itself: admit → automatic dispatch → lab → `check` → `done` → land → lab deleted. Prove the happy path and a landing conflict first with the fake harness, then with a real Claude worker. Record the stage 4 perch report and file every breakage as a task before later edition 1 work builds on it.

**Why it matters:** This is the first end-to-end proof that the staging Otto can run its own admitted work through landing and cleanup. Later edition 1 work depends on the breakages being exposed and filed here.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SKEL0`, on branch `lab/SKEL0`, from `canon/main` at `fe17d495ea7ff7f686286e84b4d7bdecb30e5cd7`. Work only here.

**Layer:** Otto product, staging and bootstrap tooling.

**Files you own:**
- `ops/bootstrap/perch.sh`
- `ops/bootstrap/perch_report.py`
- `ops/bootstrap/canary/project.json`
- `ops/bootstrap/canary/fake_worker.py`
- `ops/bootstrap/staging.sh`
- `tests/test_perch.py`
- `tests/test_perch_stage1.py`
- `tests/test_perch_staging.py`
- `tests/test_perch_timeline.py`

**Other files:** You may edit another file only when the stage 4 outcome directly requires it, except files under “Do not touch”. Explain every such file in your report. Keep product/landing changes to the minimum needed to exercise the path; do not weaken a gate to make the scenario pass.

**Do not touch:**
- REDS2's `tests/test_events_final_corrections.py`, `tests/test_project_folder_scale.py`, `tests/test_hostctl_serve.py`, `src/otto/portfolio/tests/test_worker_occurrences.py`, `tests/test_supervisor_direction_client.py`, `tests/test_hostctl_cli.py`, `tests/test_current_manager_selector.py`, `tests/test_help_completion_regression.py`, `tests/test_manager_correction_planning.py`, `tests/test_manager_journey_command.py`, `tests/test_manager_reentrant_ipc.py`, `tests/test_manager_service_continuation.py`, `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_client.py`, and directly exercised production files in REDS2's scope;
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5, or anything outside this lab.

**Build on what exists:** Extend the stage runner, report CLI, canary project, fake worker and staging Otto. Follow the existing stage 0–2 scenarios and Store/census evidence; preserve those stages. Use the task row in `projects/program/tasklist.md` as the acceptance contract.

**Your check.** Add focused assertions for stage 4's full owner-driven canary path, happy path, landing conflict and lab deletion. Show each new assertion fail under its matching seeded fault, then pass. Run fake-harness checks first; the acceptance proof must also run on staging with a real Claude worker. The landing gate runs staging on the merged commit.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_stage1.py tests/test_perch_staging.py tests/test_perch_timeline.py`

**Regression at the level the friction appears:** The stage 4 perch must catch a break anywhere from admission through dispatch, worker `check`/`done`, landing, conflict recovery or lab deletion. Report the stage 4 run location and file each discovered breakage as a task.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl` (including `--help`), or use a clone of the live Store/install. Never wait with a monitor, sleep loop or background job; run checks in the foreground. Keep staging isolated under its existing staging root. The landing gate runs the real staging perch.
- **On Codex (Luna):** You can't commit; leave work in the lab for the launcher to commit. Give long checks a long timeout and let them finish. If a test fails with `sandbox_apply: Operation not permitted`, report it for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave changes for the launcher to commit. Report the commit, focused check results, seeded-fault red/green evidence, fake and real stage 4 proof, the perch report path, filed breakages, and anything incomplete.

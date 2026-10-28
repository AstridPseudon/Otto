# Brief: HOLDSTATUS (normal, 0.5 focused days)

**Outcome:** Make every stage-2 hold actionable in status, scope the root-direction gate to the held project's obligations, and report `readmission needed` with changed fields when an admitted task's content changes. The stage-2 no-launch snapshot must name that reason.

**Why it matters:** STAGE2B Opus re-review findings 3 and 5 show that operators can wait forever on holds or edited admitted work, and unrelated project holds can block root-direction changes.

**Your lab:** Launcher creates this from current `canon/main`; work only there.

**Layer:** Otto product and proof harness. Product status and admission behavior belong in Otto; the stage-2 snapshot verifies operator-facing behavior.

**Files you own:** `src/otto/hostctl/project_service.py`, `src/otto/portfolio/execution_host.py`, `ops/bootstrap/perch.sh`, `tests/test_hostctl_project_service.py`, `tests/test_capacity_holds.py`, `tests/test_perch.py`, and directly required tests.

**Other files:** Edit another file only when the outcome directly requires it; list each with the reason in your report.

**Do not touch:** Files owned by any worker running now; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on:** `ProjectService._status` and its serialized holds in `src/otto/hostctl/project_service.py`; `ExecutionHost.prepare_root_direction_adoption` in `src/otto/portfolio/execution_host.py`; existing stage-2 no-launch evidence in `tests/test_perch.py` and `ops/bootstrap/perch.sh`.

**Your check:** Add or extend real-owner tests proving a killed worker's hold names its settling command, a hold in project A does not block root-direction change in project B, and edited admitted content reports `readmission needed` with changed fields. Update the stage-2 no-launch snapshot assertion to name that reason. Demonstrate regressions fail on canon first; run focused unit tests. Stage 2 `--fake` is an outside-sandbox check; do not run it in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_project_service.py tests/test_capacity_holds.py tests/test_perch.py`

**Regression at the level the friction appears:** Real-owner holds, cross-project root-direction adoption, and edited-admission status; stage-2 no-launch snapshot identifies readmission need.

**Invariant:** Every retained hold has an actionable settling step, and one project's hold cannot block another project's root-direction change.

**Plausible mistake to avoid:** Reporting a hold without its next action or applying the held project's gate globally.

**Working rules:** Follow the template's Codex rules. Leave changes uncommitted for the launcher; run tests to completion with a long timeout. Do not run staging-owner tests inside the worker sandbox. Stage 2 `--fake` is run outside the sandbox.

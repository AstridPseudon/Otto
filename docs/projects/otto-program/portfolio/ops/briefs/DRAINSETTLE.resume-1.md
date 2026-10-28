# DRAINSETTLE resume 1

The landing gate refused the lab on D14: the brief says `Herzchen fleet execution draining`, but the implementation adds 33 lines under `src/otto` and none under `src/herzchen`. The complete landing record is `${TRANSFER_ROOT}/portfolio/ops/runs/DRAINSETTLE/land.log`.

Continue in the existing lab and same session. Preserve the task outcome and the existing regression coverage. Move the reusable fleet drain-settlement mechanism into `src/herzchen/fleet/`; keep only Otto-specific owner wiring, names, policies, and callbacks in `src/otto`. If the design cannot be separated without moving Otto vocabulary into Herzchen, explain the boundary and make the narrowest valid placement correction. Extend `tests/test_herzchen_boundary.py` if needed, and ensure the DRAINSETTLE regression still proves a queued request receives one held response, preserves its prepared request for explicit recovery, and does not start effects during drain. Do not weaken assertions.

The focused check is the original `.brief.md` command, plus `tests/test_herzchen_boundary.py` if changed. Run each task-owned test file. Report the placement and boundary, focused check results, and any further files changed.

Do not touch active PERCH2C files: `ops/bootstrap/perch_report.py`, `tests/test_perch.py`, `ops/bootstrap/canary/project.json`, or its directly required focused fixtures. Do not touch active ACTIVATEWHILE files: `src/otto/hostctl/project_service.py`, `src/otto/portfolio/project_services.py`, `tests/test_act_activation.py`, `tests/test_bounded_project_host.py`, or directly required owner-routing files it needs. Respect all other exclusions in the original `.brief.md`.

Continue to follow the original XHARD, invariant, plausible-mistake, regression, and working-rule instructions in the lab's `.brief.md`. Do not commit or push; leave the commit to the launcher. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

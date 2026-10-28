# D19 decision: LANDASSESS, tests/test_fleet_custody.py, tests/test_hostctl_cli.py, tests/test_manager_assessment_ipc.py, tests/test_perch.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- `tests/test_fleet_custody.py`: the landing adapter used to declare its own `check-accepted` scope (`declare-scope`, a `fleet-check-…` id) and then freeze the input. Now activation has already declared the task's required scope from the run's policy, so the landing's only request is `freeze-input`. That is the decision recorded in the row ("the run's policy is the one source … landing never declares a second scope"). The test also gains a metadata-only task revision that must still be accepted.
- `tests/test_hostctl_cli.py`, `tests/test_manager_assessment_ipc.py`, `tests/test_perch.py`: additions (policy-derived activation scope, content binding across a metadata revision, the fake's refusal text); no existing expectation removed.

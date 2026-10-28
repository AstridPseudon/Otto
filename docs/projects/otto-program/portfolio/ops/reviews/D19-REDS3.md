# D19 decision: REDS3, tests/test_manager_correction_planning.py, tests/test_hostctl_serve.py, src/otto/portfolio/tests/test_manager_consumption.py, tests/test_hostctl_cli.py (the orchestrator, 17 Oct 2026)

**Decision: LAND**, once the five `MacWriteScope.preflight` patches are removed (the 08:10Z hold). No Opus call was made.

- `tests/test_manager_correction_planning.py`: `assertFalse(requires_native_caller('review-task'))` becomes `assertTrue`. Canon's native-caller set includes `review-task` (`src/otto/portfolio/manager_journey_client.py`, `requires_native_caller`), which REDS2 kept; the test was a canon red asserting the older routing.
- `tests/test_hostctl_serve.py` (manager-loop test, a canon red): the fake manager now admits exact task revisions, declares the fixture's assessment policy, reviews T1 and yields for owner settlement before T2 is dispatched, so the manager's resume after T2 is turn 4, not turn 3 (`manager-turn-4.txt`). That follows canon's admission and dependency rules (only admitted, ready tasks start; T2 depends on T1); the test still asserts the manager is resumed after T2.
- `src/otto/portfolio/tests/test_manager_consumption.py`: the absolute import and the fake's portfolio and workspace contract are setup, not expectations; named here so the decision covers the file.
- `tests/test_hostctl_cli.py`: no expectation changes once the preflight patches are removed; named for the same reason.
- **Not covered:** the preflight patches themselves. They made sandbox-only failures pass and are to be removed, not decided.

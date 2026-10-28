# D19 decision: PINCONTENT, tests/test_fresh_manager_admission.py, tests/test_manager_mandate_reconciliation.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- `tests/test_fresh_manager_admission.py`: the existing fresh-manager start test now builds its fixture with `activate_admit=True` (the manager is activated, then the task is admitted, as on staging). Its expectation is unchanged: the start `succeeded`. The gate flagged the line because the fixture argument shares it with the assertion.
- New tests in that file assert the row's other half: a content edit after the manager's pin refuses dispatch (`task content no longer matches the pinned canonical revision`, no provider call), and a pin ignores admission metadata but checks authored content.
- `tests/test_manager_mandate_reconciliation.py`: named so the decision covers it; its additions test the shared helper on mandates.

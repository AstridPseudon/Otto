**Removed:** `run_due_occurrence`, `continue_admitted_occurrence`, `run_scheduled_callback`, `invoke_assignment`, `invoke_manager`, `invoke_orchestrator`, `assign_and_start`, `PortfolioLifecycleIntegration`, `ReleaseOperations`, and `validate_configuration`. `LifecycleIntegrationError` and the `MO02B_SLOT3_REQUEST_KEY` constant were also removed because they only supported deleted APIs.

**Grep audit:** `git grep -n -w` found no matches for any deleted name across `src`, `tests`, and `ops`. Each name had matches in the lab’s `HEAD` baseline; the lab is now clear. The initial audit found no remaining production callers beyond the definitions and exports.

**Checks:**

- Requested focused command: **93 passed, 16 subtests passed**.
- Expanded run of modified test modules: **270 passed, 8 failed, 103 subtests passed**. Failures were in broader owner/process tests; their causes are not established.
- `git diff --check` passed. `run_turn` and `run_continuation` were left unchanged.
- The first expanded run needed `--import-mode=importlib` to collect package tests with relative imports.

**Files changed:** Product changes are in `src/otto/agents/{__init__.py,gateway.py,orchestrator_route.py,owner_runtime.py}`, `src/otto/attention.py`, `src/otto/engineering/{__init__.py,release_records.py}`, and `src/otto/portfolio/{__init__.py,execution.py}`; `src/otto/portfolio/lifecycle.py` was deleted. Tests now use a prepare-then-start helper in `tests/execution_helpers.py` and the affected execution, manager, and portfolio test modules. Two tests directly tied to the deleted lifecycle integration were removed from `tests/test_host_bridge_transitions.py` and `tests/test_project_advisor_pairing.py`.

No existing assertion was changed. The only assertion-bearing tests removed were those directly exercising `PortfolioLifecycleIntegration`; this is the D19-related deletion. No commit or push was made.
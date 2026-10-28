# Brief: OWNERCOMPLETION (normal, 0.25 focused days)

**Outcome:** Find every caller of `ExecutionHost.admit_execution` and other `OwnerCompletion` producers that treats the value as a mapping. Unwrap each through `after_owner` so a manager turn start while a worker turn is admitted answers without `AttributeError: 'OwnerCompletion' object has no attribute 'get'`. Add a real-owner unit regression for the failing path and verify grep finds no remaining mapping-style use of an `OwnerCompletion`.

**Why it matters:** A stage-2 manager start failed while the owner admitted a worker turn. The shared owner path must handle deferred completion values consistently.

**Your lab:** The launcher creates the OWNERCOMPLETION lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. This fixes Otto's manager and execution-owner wiring.

**Files you own:** `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_service.py`, and focused tests for the manager turn start and execution-host admission path.

**Other files:** You may edit any other file directly needed to fix a caller or add the real-owner regression, except the files listed under Do not touch. Explain each additional file in your report.

**Do not touch:**
- `tests/test_manager_service_continuation.py` (`PROJECTPIN` landing is in progress);
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `src/otto/portfolio/execution_host.py` imports `OwnerCompletion, after_owner` and has mapping-wrapper examples near lines 1447 and 1602; `src/otto/portfolio/manager_journey_service.py` handles completion values near lines 1461, 1955 and 1988. Use `after_owner` at those boundaries and inspect every `admit_execution` caller, including `src/otto/portfolio/execution.py:1226` and `src/otto/portfolio/orchestrator_client.py`.

**Your check:** Add a real-owner regression that exercises manager turn start while a worker turn is admitted and proves there is no AttributeError. Run the test files changed or added; do not run staging-owner tests in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_execution_host_manager_turn_queue.py tests/test_manager_journey_service.py`

**Regression at the level the friction appears:** A manager turn start during an admitted worker turn returns a valid completion response without treating `OwnerCompletion` as a mapping.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; the launcher commits on exit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Never run staging-owner tests in the worker sandbox.

**When done:** Report the commit, focused checks, all remaining `OwnerCompletion` callers inspected, and the grep result. Stop and report if the brief contradicts the code.

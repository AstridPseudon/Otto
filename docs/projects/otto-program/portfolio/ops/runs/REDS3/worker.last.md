All eight requested files passed **twice, individually**, using the specified pytest command. I left the changes uncommitted for the launcher. HEAD is still `a9d73607dc875c69972f6a710de38814c547f761`.

### Before and after

| File | Current-canon baseline | After |
|---|---|---|
| [test_current_manager_selector.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_current_manager_selector.py) | Green: 7 passed, 10 subtests | Green both passes |
| [test_help_completion_regression.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_help_completion_regression.py) | Green: 7 passed, 5 subtests | Green both passes |
| [test_manager_correction_planning.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_manager_correction_planning.py) | One stale `review-task` routing failure | Green both passes; assertion updated to `True` with your D19 approval |
| [test_manager_journey_command.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_manager_journey_command.py) | Green: 23 passed, 7 subtests | Green both passes |
| [test_manager_service_continuation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_manager_service_continuation.py) | Green: 45 passed, 5 subtests | Green both passes |
| [test_hostctl_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_hostctl_cli.py) | Two failures from nested `sandbox-exec` being denied | Green both passes: 16 passed, 2 subtests |
| [test_hostctl_serve.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/tests/test_hostctl_serve.py) | Three failures: nested sandbox denials and stale manager-loop fake behavior | Green both passes: 14 passed, 4 skipped, 2 subtests |
| [test_manager_consumption.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/src/otto/portfolio/tests/test_manager_consumption.py) | Failed collection via direct file path | Collects and passes both times: 9 passed, 14 subtests |

### Fixes and landing traces

- The correction-planning expectation now follows native-caller routing from REDS2 (`a9d7360`); this assertion change was D19-approved.
- The manager-consumption test uses an absolute import so direct-file pytest collection works. Its fake now supplies the portfolio needed by the consumption helper and uses the workspace contract introduced by `53b40dd` for the child, then restores the fixture root for the resumed manager. The test itself originated in `fb27f74`.
- The manager-loop fake now admits exact task revisions and declares fixture assessment policy, then reviews T1 and yields for owner settlement before dispatching dependent T2. This reflects the admission and dependency behavior exercised by canon (`f94b201`). The resume assertion still checks that the manager returns after T2; the added review turn moves that return to turn 4.
- In [manager_journey_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS3/src/otto/portfolio/manager_journey_service.py), the worker-result callback now prefers the exact authenticated manager occurrence retained with the worker. The callback previously selected the mutable current head, despite the occurrence pin added in `89cb2be6`; the affected synchronization path traces to `b85a7359`.
- The host CLI and serve fakes bypass OS scope preflight/wrapping only in tests that cover owner admission, launcher qualification, or manager routing. Nested sandbox execution is denied in this environment; the affected integration tests date to `52cf6a5`. Assertions remain intact, and the escalation fake stays active through the asynchronous callback.

The only additional source file changed was `src/otto/portfolio/manager_journey_service.py`, because the manager callback’s occurrence selection required a product fix. `git diff --check` passed.

I left `tests/test_project_folder_scale.py` untouched as instructed. Its apparent limit tension is the 200-document roundtrip using a 256 MiB owner transport override alongside statements about historical folder limits and per-operation bounds; the orchestrator should decide whether that distinction is intentional.
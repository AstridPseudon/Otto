# D19 request: COMPLETEPIN test expectation changes

Changed existing test file: `tests/test_completion_project_refresh.py`.

The COMPLETEPIN design removes the `finish-project-pin` journal proof and its supervision-transfer ancestry walk. The former tests at lines 89-149 asserted those proof records and rejected unrelated project revisions. Those expectations conflict with the requested outcome: an accepted task can finish after another task or project plan content changes, provided the accepted task revision and its assessment policy remain valid.

The replacement cases use real owner writes. An unrelated project title edit now expects completion. An edit to the accepted task's `instructions` expects a refusal naming `task.instructions` and fresh review commands. A trusted assessment policy `purpose` change expects the corresponding `assessment_policy.purpose` refusal. The stale manager-generation refusal remains, as does successful same-root refresh and replay coverage. Tests that patched readers and journals to manufacture ancestry failures were removed with that mechanism.

Red on canon: the new PA01/PA06 test and all three replacement cases failed as intended. Green in the lab: the focused COMPLETEPIN files passed, 35 tests and 10 subtests. The changed test assertions need the orchestrator's D19 LAND or SEND BACK decision before landing.

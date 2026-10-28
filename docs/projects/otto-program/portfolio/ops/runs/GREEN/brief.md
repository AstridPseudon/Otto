# Brief: GREEN (normal, 1.0 focused days)

Title: Make the line green: fix the failures that pre-date the program

**Outcome:** every test file in the list below passes when run on its own. Landings are then judged against green, not against a baseline of red.

**Why it matters:** the program's landings compare against `canon/main`. Right now 10 test files fail there before any program work, so every landing has to be checked against a stored baseline. Once this lands, a new failure is simply a failure. PLAN.md §4 (the hostctl and portfolio suites must stay green).

**Your lab:** `~/Developer/otto-claude-host/labs/GREEN`, on branch `lab/GREEN`, from `canon/main` at `16825ca`. Work only here.

**Known failures on canon/main** (verified by the manager at `e13c927`; check them again yourself):
- `tests/test_hostctl_portfolio_apply.py`: 6 failures;
- `tests/test_hostctl_serve.py`, `tests/test_advisor_lifecycle.py`, `tests/test_project_advisor_pairing.py`, `tests/test_d03_status_reads.py`;
- `tests/test_usage_retained_native.py`: `KeyError: 'assessment_policy'` at `src/otto/portfolio/manager_journey_command.py:262`. `ed6a060` changed it to `self.state["assessment_policy"]`, and the fixture doesn't supply it;
- `tests/test_stopped_writer_conflict_custody.py`: 12 failures, `SimpleNamespace` has no `.get` at `src/otto/agents/manager_capture_reconciliation.py:235`.

Note: the manager ran the whole set in one pytest and got cross-test interference (for example `test_capacity_holds.py` and `test_herzchen_boundary.py` pass on their own, 12/12). **Run each file on its own.** A file that fails only when run with others is an isolation bug: fix it, and say so in your report.

**Files you own:** the sources and tests behind the failures above: the hostctl and portfolio modules, `manager_journey_command.py`, `manager_capture_reconciliation.py`, and the tests listed. Fix the code or the test. For each failure, say which you changed and why. Do not change an assertion just to make it pass, unless the assertion encodes the bug (say so in the report).

**Do not touch:**
- `execution_host.py` (HOLD, POOL and ACT are working in it). If a failure lives there, stop and report it instead;
- `heavy.py`, the capacity pool, `_eligible` (POOL);
- `production/`;
- any Store, `~/.otto` or `~/.codex`, and the running Otto service;
- `ottoctl` (do not run it, and never pass it `--help`);
- Codex's projects, vision and Native5;
- anything outside this lab.

**Your check.** Each of the 29 files below passes when run on its own, through otto-heavy. Run them in a loop, one pytest per file:
```
for f in tests/test_portfolio_status.py tests/test_d03_status_reads.py tests/test_hostctl_portfolio_apply.py tests/test_hostctl_serve.py tests/test_hostctl_sync.py tests/test_advisor_lifecycle.py tests/test_project_advisor_pairing.py tests/test_root_direction_client.py tests/test_root_direction_synchronization.py tests/test_retention_dependency_resolver.py tests/test_usage_accounting.py tests/test_usage_capture.py tests/test_usage_claude_streams.py tests/test_usage_contract.py tests/test_usage_late.py tests/test_usage_retained_native.py tests/test_recovery_timing.py tests/test_stopped_writer_conflict_custody.py tests/test_capacity_holds.py tests/test_herzchen_boundary.py tests/test_execution_host_manager_turn_queue.py tests/test_execution_operations.py tests/test_execution_application.py tests/test_worker_custody.py tests/test_status_owner_custody.py tests/test_adapter_conformance.py tests/test_host_neutral_defaults.py tests/test_codex_host_reader.py tests/test_host_bridge_transitions.py; do ~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "GREEN $f" -- env PYTHONPATH=src:tests /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$f" || exit 1; done
```
Note: `tests/test_execution_host_manager_turn_queue.py`, `tests/test_execution_operations.py` and `tests/test_execution_application.py` exercise `execution_host.py`. Run them, but a failure there is for the report, not for a fix (see "Do not touch").

**Regression at the level the friction appears:** n/a: a fix task. The regression is the existing suites themselves.

**Deletion budget:** a fix that deletes code must say what it replaced. Name anything you remove.

**When done:** commit to `lab/GREEN` (only the files you own; never `.brief.md`, `.worker.json` or `.worker.err`) and don't push. Report:
1. the commit;
2. for each of the 29 files, pass or fail, on the final commit;
3. for each fix, the file, what changed, and whether you changed code or a test;
4. any file still failing, with the failing test ids and the first error line;
5. any isolation problem you found.

Keep the report short. Stop and report if the brief contradicts the code.

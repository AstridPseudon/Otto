# Brief: MANUALDISPATCH (normal, 0.5 focused days)

**Outcome:** Every worker start through `run-worker`, `reroute`, `retry`, `start-retained-child`, and ask continuation records exactly one `work.assignment.dispatched`; replay adds none. Delete `successor_entry.py` and `successor_runner.py` after confirming no caller in `src`, `tests` or `ops`.

**Your lab:** `lab/MANUALDISPATCH`, on branch `lab/MANUALDISPATCH`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Otto product. Read and reuse the `WorkAssignments.dispatch` path added by AUTODISPATCHREC; keep dispatch identity and event semantics there.

**Files you own:** `src/otto/portfolio/execution.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/successor_entry.py`, `src/otto/portfolio/successor_runner.py`, and focused tests for the five start paths and successor deletion.

**Other files:** Edit any additional callers or fixtures directly required by the outcome, except running-task files below. List each with its reason.

**Do not touch:** `src/otto/portfolio/perch.sh` and `src/otto/portfolio/execution_host.py` (LABCAPTURE and KILLFENCE); `production/`; any Store, `~/.otto` or `~/.codex`; anything outside this lab.

**Your check:** For each of the five launch paths, test the real owner records exactly one dispatch and replay adds none. Verify `grep -rn successor_ src tests ops` is empty. Run regressions red on canon and green after the fix. Stage-2 `--fake` is an orchestrator run; do not run it in this worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_execution_application.py tests/test_manager_journey_service.py tests/test_fleet_dispatch.py`

**Deletion budget:** Remove the unused successor relaunch mechanism as named in the row.

**Working rules:** Follow the Codex worker rules in the template: no commit or push, no staging Otto in the worker sandbox, long test timeout, report any extra files. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

# Brief: KILLFENCE (xhard, 0.75 focused days)

**Outcome:** A killed worker's manager has one recovery action that settles its unknown attempt and clears its fence; the fence blocks only its own project so a second project can activate.

**Your lab:** `lab/KILLFENCE`, branch `lab/KILLFENCE`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Otto product, owner execution and manager recovery.

**Files you own:** `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/project_services.py` only if needed to scope the fence, `tests/test_capacity_holds.py`, `tests/test_execution_host_manager_turn_queue.py`, and the narrow stage-2 owner assertion only if required.

**Other files:** Edit another direct caller or fixture only when required and report each. Keep changes to killed-worker recovery, fence release and project scope. `perch.sh`, `perch_report.py`, `claude_cli.py` and worker process census belong to ORPHANWORKER; do not alter those concerns. `landing.py`, `labs.py`, and artifact capture belong to LABCAPTURE.

**Do not touch:** The files or changes owned by concurrently launched LABCAPTURE, ORPHANWORKER, and COMPLETECITE; `production/`; any Store, `~/.otto` or `~/.codex`; Codex project configuration; anything outside this lab.

**Build on what exists:** `Execution.release_capacity_failed_worker`, current owner recovery/manager command wiring, and `_capacity_holds`; inspect their current line numbers in the lab. The row notes the release method currently has no caller.

**Your check:** On canon, first show a real-owner test where a killed worker leaves the fence and blocks a second project; then show recovery settles the unknown attempt, clears the fence, and permits the second project. Add a test that a fence affects only its own project. Run the focused tests.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_capacity_holds.py tests/test_execution_host_manager_turn_queue.py`

**Regression at the level the friction appears:** Kill → manager recovery → second project activation.

**Invariant:** An unknown attempt is settled by its manager, never silently, and its fence covers only its project.
**Plausible mistake:** Clearing the fence on process exit, so the unknown attempt looks settled and can be replayed.
**Deletion budget:** Wire `release_capacity_failed_worker` or replace the unused release mechanism with one recovery path; avoid duplicate fence-clearing paths.

**Orchestrator-run acceptance:** Do not start a staging Otto in your sandbox. Report that stage 2 `--fake` with its post-kill assertion requires the orchestrator run.

**Codex rules:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: use a long timeout or keep reading its session until it exits; never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD:** Lead the design and invariant review; delegate execution to Luna sub-agents using `spawn_agent` with `model: "gpt-6-luna"`. Review the diff and test tail yourself. Report each sub-agent and any corrections. Never run staging-owner tests in your sandbox.

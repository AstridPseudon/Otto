# Brief: DEADLAUNCH (normal, 0.5 focused days)

**Outcome:** Delete the unused launch and release entry points named in the task row, their exports and tests. Delete `validate_configuration` if removing its only caller leaves it unused. Keep Herzchen `run_turn` and `run_continuation`; REWORKWIRE uses them.

**Why it matters:** These duplicate routes bypass bounded owner custody and retain release/capability defects. The acceptance check is that every deleted name has no caller in `src`, `tests` or `ops`.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. Remove unused routes and exports while retaining the Herzchen continuation contract.

**Files you own:** `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py`, and their tests/exports directly referencing the deleted names.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report.

**Do not touch:**
- `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py` and per-call owner facade sites (SESSIONFD);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `src/herzchen/domains/work/module.py`, `tests/test_admit.py` (ADMITREVIEW);
- `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/tests/test_reviewed_activation.py`, `src/herzchen/contracts/model.py`, `tests/test_authenticated_actor_decode.py` (FAILCLOSED2);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/DEADLAUNCH.brief.md`. Before deleting each named entry point, use `git grep` to verify no production or non-test caller remains beyond its obsolete export and associated tests. Remove only the unused routes, exports, tests and `validate_configuration` if it becomes unused. Preserve Herzchen `run_turn` and `run_continuation` unchanged.

**Your check:** Run the focused files you changed and report the `git grep -n -w` result for every deleted name across `src`, `tests` and `ops`; show canon red and lab green where a regression is appropriate. Do not run staging/perch in the worker sandbox; the landing gate handles it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_execution_application.py tests/test_execution_operations.py tests/test_command_ports_lifecycle.py tests/test_otto_open_release.py`

**Regression at the level the friction appears:** No deleted launch or release name remains referenced in `src`, `tests` or `ops`, and kept continuation routes remain intact.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests to pass in the worker sandbox. Do not run tests that start a staging owner in the worker sandbox.

**When done:** Report the checks, removed names, files changed and blockers. Preserve existing assertions; list any changed assertion as `file:line` and explain it for D19.

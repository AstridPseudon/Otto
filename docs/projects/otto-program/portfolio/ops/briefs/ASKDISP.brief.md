# Brief: ASKDISP (normal, 0.25 focused days)

**Outcome:** An answered worker continuation records exactly one dispatch. Delete the answer path's explicit dispatch call and let the shared start boundary own the event and replay key.

**Why it matters:** The answer path and worker start currently record duplicate dispatch events for one successful continuation. The shared start must own dispatch identity so replay adds no second event.

**Your lab:** The launcher creates the ASKDISP lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. Keep dispatch behavior in the maintained execution path.

**Files you own:** `src/otto/portfolio/execution.py` and `tests/test_ask_integration.py`.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report.

**Do not touch:** `ops/bootstrap/land.sh`, `ops/bootstrap/otto_gate_exit.py`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP and TOOLING26); `ops/bootstrap/perch_report.py`, `tests/test_perch.py`, `ops/bootstrap/canary/project.json` (PERCH2C); `src/otto/portfolio/execution_host.py` (DRAINSETTLE). Also do not touch `production/`, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `src/otto/portfolio/execution.py:1255–1263` handles the optional request key; `:1346` dispatches worker starts; `:2043–2048` records dispatch from the answer path. Reuse `WorkAssignments.dispatch` semantics from `src/herzchen/domains/work/assignments.py:857–868`.

**Your check:** Add `test_answered_worker_continuation_dispatches_once_and_replay_is_inert` to `tests/test_ask_integration.py`, following `ops/prework/ASKDISP.md`. It must exercise the real ask, answer, continuation, store, and provider fixture; assert one provider call and exactly one new `work.assignment.dispatched` event, then prove replay adds neither. Do not weaken existing assertions. The design notes that answer authorization permits non-worker roles while the shared start dispatches workers only; preserve current behavior for those roles and report if the row's scope requires a decision.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_ask_integration.py`

**Working rules:** Do not commit or push; the launcher commits on exit. Run the canon regression first, keep tests running to completion, and report both red and green results. Never stash, switch commits, run `ottoctl`, or start a staging owner. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

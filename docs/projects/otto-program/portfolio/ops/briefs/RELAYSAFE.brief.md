# Brief: RELAYSAFE (normal, 0.5 focused days)

**Outcome:** Malformed, unsafe, or oversized manager replies produce a finite diagnostic for the original request, preserve the response and handle, and do not stop later owner relay polls.

**Why it matters:** A malformed or large reply must not terminate the owner's relay poll or cause the command to repeat.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; shared bounded file reading belongs in Herzchen only if another product can use it.

**Files you own:** `src/otto/hostctl/lanes.py`, `src/otto/portfolio/client_lanes.py`, `src/otto/hostctl/service.py`, focused relay tests in `tests/test_owner_lane.py`.

**Other files:** You may edit other files directly required by the outcome, except files under Do not touch. Explain additions.

**Do not touch:**
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and focused real-owner Codex journey tests (CODEXOWNER);
- `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py`, and directly referencing tests/exports (DEADLAUNCH);
- `tests/test_operator_admission.py`, `tests/test_execution_host_manager_turn_queue.py`, `tests/test_embedded_host_heartbeat.py` (UNTIME2);
- `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py` (LANDPROOF);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/RELAYSAFE.md` first and report departures. Use the bounded private-file reader, validate the top-level object, and contain each relay's failures. Preserve the original response and request handle; use `summary_availability.state: "detail-required"` when returning a bounded diagnostic. Do not infer manager effects or repeat the command.

**Your check:** Add the real-poll regression for an array, unsafe private file, and oversized reply; run focused relay tests.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py`

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests in the worker sandbox.

**When done:** Report canon red and lab green runs, files changed, and blockers.

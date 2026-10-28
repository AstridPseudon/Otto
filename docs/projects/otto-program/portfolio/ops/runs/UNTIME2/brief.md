# Brief: UNTIME2 (normal, 0.5 focused days)

**Outcome:** Replace the three timing-dependent assertions identified in `ops/prework/UNTIME2.md` with waits for observable state. Preserve every business expectation; only a hang should fail.

**Why it matters:** These tests report failures or pass broken behavior when the owner is merely slow. State-based waits make the queue, heartbeat, and admission behavior deterministic under load.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto fleet tests; this task hardens tests and does not change product behavior.

**Files you own:** `tests/test_operator_admission.py`, `tests/test_execution_host_manager_turn_queue.py`, `tests/test_embedded_host_heartbeat.py`.

**Other files:** Do not edit other files unless the outcome directly requires one; explain additions in your report.

**Do not touch:**
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and focused real-owner Codex journey tests (CODEXOWNER);
- `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py`, and directly referencing tests/exports (DEADLAUNCH);
- `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/tests/test_reviewed_activation.py`, `src/herzchen/contracts/model.py`, `tests/test_authenticated_actor_decode.py` (FAILCLOSED2);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- production/, Stores, ~/.otto, ~/.codex, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/UNTIME2.md` first. Follow its state-based approach and report any departure. Rebase the first test file after OWNERCOMPLETION's additions. Do not add product polling hooks. The prework identifies two expectation changes needing D19 review: the queue test's one-time lock probe becomes a completed callback while queued, and the heartbeat test removes the `_status` wrapper's direct every-call assertion. List each changed assertion by file:line and explain it in your report; the landing remains held until D19 decides.

**Your check:** Run the three test files after the changes; demonstrate the admission regression against bypassed deferral and retain the other business assertions. Do not use timing sleeps as a synchronization substitute.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_operator_admission.py tests/test_execution_host_manager_turn_queue.py tests/test_embedded_host_heartbeat.py`

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests to pass in the worker sandbox.

**When done:** Report the canon and lab runs, files changed, changed assertions for D19, and blockers.

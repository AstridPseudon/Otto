# Brief: LANDPROOF (xhard, 0.75 focused days)

**Outcome:** Completion records prove that the exact accepted commit reached its configured line, and interrupted line advancement can be reconciled without rerunning assessment or the provider.

**Why it matters:** Accepted work must be on the configured line before ordinary manager completion can mark the code task done.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet; owner-specific repository and line authority remains Otto wiring.

**Files you own:** `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py`.

**Other files:** Edit other files directly required by the outcome, except files under Do not touch; explain each addition.

**Do not touch:**
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, or focused real-owner Codex journey tests (CODEXOWNER);
- `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py`, and directly referencing tests/exports (DEADLAUNCH);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/LANDPROOF.md` first and report departures. Establish the real-owner accepted-but-unlanded regression first. Preserve acceptance before merge; retain a versioned intent, verify the exact configured line advance, and require owner-written proof before returning landed. Recovery must reconcile the exact intent without rerunning checks, providers, or acceptance. Preserve assessment-failure refusal.

**Your check:** Demonstrate the regression red on canon and green in the lab; run changed tests and focused landing/completion coverage. Do not run staging/perch in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Invariant:** An accepted code task completes only after its exact accepted commit is proven on its configured line.

**Plausible mistake:** Moving acceptance after merge or treating the pre-merge intent as proof of landing.

**Surfaces:** Completed work is absent from the line, or unaccepted work is merged.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. XHARD: lead the design and review; delegate execution to Luna sub-agents as specified in the template. Never weaken tests in the worker sandbox.

**When done:** Report canon red and lab green runs, files changed, invariant review, sub-agents and blockers.

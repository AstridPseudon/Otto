# Brief: FAILCLOSED2 (normal, 0.25 focused days)

**Outcome:** Ambiguous plan pins and actor records fail closed.

**Why it matters:** Conflicting review or policy aliases must hold activation, and actor records must affirm authentication with the literal boolean `true`.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen model for strict actor decoding; Otto product for reviewed activation alias resolution.

**Files you own:** `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/tests/test_reviewed_activation.py`, `src/herzchen/contracts/model.py`, and new `tests/test_authenticated_actor_decode.py`.

**Other files:** Edit any other file the outcome directly requires, except files under Do not touch. Explain additions in your report.

**Do not touch:**
- `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py` and per-call owner facade sites (SESSIONFD);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `src/otto/hostctl/product_service.py`, `tests/test_fleet_custody.py` (DONESETTLE and MCPPATH);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/FAILCLOSED2.md` first and follow its implementation order. Test review aliases and adopted-policy aliases together: conflicting pins must yield `ready: false`, `state: "held"`, and blockers naming both aliases and values; equal legacy aliases still pass. Treat malformed supplied aliases as invalid rather than falling through. Preserve stale-pin behavior for a single wrong pin. Decode `AuthenticatedActor.authenticated` only when it is exactly `True`; require the field in `from_dict` and close the tagged-wire direct-constructor path too. Add missing, `"false"`, `1`, and literal-True cases. Keep activation effects gated by readiness.

**Your check:** Demonstrate canon red then lab green for conflicting review and policy pins and actor decoding. Run both focused test files after the change.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider src/otto/portfolio/tests/test_reviewed_activation.py tests/test_authenticated_actor_decode.py`

**Regression at the level the friction appears:** Conflicting aliases hold readiness before activation effects; consistent aliases remain ready; malformed or missing actor authentication is rejected.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken a test to pass in the worker sandbox. Do not run tests that start a staging owner in the worker sandbox.

**When done:** Report canon red and lab green runs, files changed, and blockers. Preserve existing assertions; list any changed assertion as file:line and explain it for D19.

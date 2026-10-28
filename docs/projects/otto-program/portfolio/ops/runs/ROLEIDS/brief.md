# Brief: ROLEIDS (normal, 0.5 focused days)

**Outcome:** Reject owner, operator, and host principal collisions at installation load, host admission, manager activation, and worker preparation before writing assignments; preserve distinct assignment-scoped worker names.

**Why it matters:** Reserved installation actors must not be impersonated by an agent assignment.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; shared validation belongs in Herzchen only if another product can use it.

**Files you own:** `src/otto/hostctl/config.py`, `src/otto/hostctl/service.py`, `src/otto/hostctl/register.py`, `src/otto/portfolio/manager_journey_service.py`, `tests/test_hostctl_cli.py`, plus focused entrance tests you add.

**Other files:** You may edit other files directly required by the outcome, except files under Do not touch. Explain additions.

**Do not touch:**
- `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and focused real-owner Codex journey tests (CODEXOWNER);
- `src/otto/agents/gateway.py`, `src/otto/agents/orchestrator_route.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/lifecycle.py`, `src/otto/engineering/release_records.py`, and directly referencing tests/exports (DEADLAUNCH);
- `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/tests/test_reviewed_activation.py`, `src/herzchen/contracts/model.py`, `tests/test_authenticated_actor_decode.py` (FAILCLOSED2);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Follow the row in `projects/program/tasklist.md`. Validate exact principal collisions before identity, assignment, task, or schedule writes. Preserve same-kind host replay and legitimate assignment-scoped names.

**Your check:** Add failing entrance tests for the reserved collisions and run changed test files plus focused admission/activation coverage.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_cli.py tests/test_operator_admission.py tests/test_manager_journey_service.py`

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests in the worker sandbox.

**When done:** Report canon red and lab green runs, files changed, and blockers.

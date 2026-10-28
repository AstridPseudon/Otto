# Brief: CODEXOWNER (xhard, 1.0 focused days)

**Outcome:** Make a Codex worker run through the real owner like a Claude worker. Select the owner's adapter from the admitted host kind, then qualify the Codex lab, token-bound MCP grant, sandbox and result capture in one journey.

**Why it matters:** Codex currently composes through the Claude adapter and fails before its worker runs. SKEL and MANY need cold Codex journeys.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto fleet product; new host-neutral worker behavior belongs in Herzchen only if another product can use it, with Otto retaining its wiring.

**Files you own:** `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and the focused real-owner Codex journey tests you add or update.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additions in your report.

**Do not touch:**
- `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py` and per-call owner facade sites (SESSIONFD);
- `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py` (GATESKIP);
- `src/herzchen/domains/work/module.py`, `tests/test_admit.py` (ADMITREVIEW);
- `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/tests/test_reviewed_activation.py`, `src/herzchen/contracts/model.py`, `tests/test_authenticated_actor_decode.py` (FAILCLOSED2);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/CODEXOWNER.brief.md`. Preserve the invariant: every host's worker uses its token-bound grant and workspace fence. The real owner with a fake Codex stream must call `task`, `check` and `done`, land the result and leave no lab. Include proof that the Codex worker cannot write outside its lab and that the grant remains bound to its token. Avoid changing existing assertions without a written D19 decision.

**Your check:** Demonstrate the owner journey failing on canon and passing in the lab. Run changed tests and focused Codex owner/capture coverage. Do not run staging/perch in the worker sandbox; the landing gate handles it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_serve.py tests/test_codex_artifact_capture.py tests/test_codex_host_reader.py`

**Invariant:** Every host's worker runs with its token-bound grant and its workspace fence.

**Plausible mistake:** Switching adapters while dropping the MCP grant or lab write scope.

**Surfaces:** A Codex worker writes outside its lab, or cannot land (SKEL, MANY).

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. On Codex, any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests to pass in the worker sandbox. Do not run tests that start a staging owner in the worker sandbox.

**When done:** Report canon red and lab green runs, files changed, the invariant review, sub-agents and blockers. Preserve existing assertions; list any changed assertion as `file:line` and explain it for D19.

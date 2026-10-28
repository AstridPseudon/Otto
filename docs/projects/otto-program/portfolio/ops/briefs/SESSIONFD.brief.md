# Brief: SESSIONFD (xhard, 0.75 focused days)

**Outcome:** No descriptor, thread or command-temp-dir growth per owner request. A HostSession closes every command facade and transport thread its bootstrap created; per-call owner sites reuse a facade or close what they create.
**Why it matters:** Repeated owner status polling leaks sockets and threads and threatens stage runs.
**Your lab:** Launcher creates this from current `canon/main`; work only there.
**Layer:** Herzchen command services and Otto owner wiring.
**Files you own:** `src/herzchen/command_ports.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/otto/hostctl/owner.py`, `src/otto/hostctl/cli.py`, `src/otto/hostctl/serve.py`, `src/otto/portfolio/reviewed_activation.py`, and directly required tests. `CLIARGS` owns `src/otto/portfolio/manager_journey_client.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/hostctl/manager_client.py`, and its tests; do not edit those.
**Other files:** Any directly required file except Do not touch; report each.
**Do not touch:** CLIARGS-owned files above; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.
**Build on:** `HostSession.__enter__/__exit__`, `PortfolioOwnerBootstrap.close`, `close_consumer_facade`, and LIMITFD's `role_runtime` reuse pattern. Read `${TRANSFER_ROOT}/portfolio/ops/prework/SESSIONFD.md` before editing.
**Your check:** Add coverage for 200 calls through resident owner status, manager status, document reads, `manager_assessment()` and reviewed-activation pool reads; descriptor/thread/temp-dir growth stays within +3. Run focused test files; do not weaken assertions.
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_cli.py`
**XHARD invariant:** A request's command services end with the request, and no request borrows another principal's services. Avoid caching one bootstrap across HostSessions.
**Working rules:** Follow the Codex XHARD rules in the manager brief template; no stash, commit, push or `ottoctl`; leave changes for launcher.

# Brief: FILEAUTH (xhard, 0.75 focused days)

**Outcome:** Managers cannot submit another project's owner-retained commands; authenticated ingress remains available for manager commands and owner-only retained starts/callbacks continue to work.

**Your lab:** launcher lab from canon/main; work only there.

**Layer:** Otto product manager ingress and execution authority.

**Files you own:** `src/otto/hostctl/serve.py`, `src/otto/hostctl/manager_client.py`, `src/otto/hostctl/cli.py`, `src/otto/portfolio/execution_host.py`, `tests/test_bounded_project_host.py`.

**Other files:** Direct callers, fixtures, and focused tests required by this outcome are allowed. Explain additions.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, and anything outside your lab. Avoid files owned by DEADLAUNCH (`src/otto/agents/gateway.py`, `orchestrator_route.py`, `owner_runtime.py`, `src/otto/portfolio/execution.py`, `lifecycle.py`, release records and directly referencing tests); other current tasks' files as applicable.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/FILEAUTH.md` first. Follow its real-fence test, remove manager write access to the shared compatibility lane, route command-status through authenticated ingress, and preserve owner-only retained recovery. Report departures.

**Your check:** Add the failing cross-project retained-start regression from the design first. Run it red on canon and green in the lab, then changed files and focused manager ingress/execution checks. Do not weaken tests.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bounded_project_host.py tests/test_hostctl_serve.py tests/test_execution_host_manager_turn_queue.py`

**Invariant:** Retained execution authority belongs to the owner and exact project, not possession of another project's schedule tuple. **Plausible mistake:** Rejecting every file start and breaking legitimate owner callbacks or restart recovery.

**Working rules:** Never stash, check out another commit, run `ottoctl`, or commit/push. Leave work for launcher commit. Long tests run to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

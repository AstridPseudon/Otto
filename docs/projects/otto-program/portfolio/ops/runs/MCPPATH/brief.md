# Brief: MCPPATH (normal, 0.25 focused days)

**Outcome:** The worker's MCP server always runs Otto's own code, even when a lab shadows `herzchen` or a standard-library module.

**Why it matters:** The server holds the worker token and must not load attacker-controlled code from the lab working directory.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet server launch behavior; keep Otto-specific wiring in Otto.

**Files you own:** `src/otto/hostctl/product_service.py`, `tests/test_tools.py`.

**Other files:** Edit only files the outcome directly requires; explain additions in your report.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or files outside your lab. Keep changes scoped to server invocation.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/MCPPATH.md` first and follow its exact scenario and invariant.

**Your check:** Add the real `OwnerFleetRegistry.grant_for_due` regression from the design. A lab containing a `herzchen` package and a standard-library shadow must still start Otto's installed stdio server and answer `task`; patch no product methods.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_tools.py`

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report canon red and lab green runs, files changed, and blockers. Do not weaken assertions.

# Brief: DONESETTLE (normal, 0.25 focused days)

**Outcome:** A landed `done` revokes its token before any other tool call with that token runs.

**Why it matters:** Parallel tool calls must not use a task capability after landing.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet; settlement ordering belongs at the shared owner/facade boundary.

**Files you own:** `src/otto/hostctl/product_service.py`, `tests/test_fleet_custody.py`.

**Other files:** Edit only files the outcome directly requires; explain additions in your report.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or files outside your lab. Running task work may overlap at wave edges; keep changes scoped to this outcome.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/DONESETTLE.md` first and follow its ordered steps and invariant.

**Your check:** Write the real-facade/owner-pump regression from the design; prove it fails on canon and passes in the lab. Settlement must finish before the owner operation signals its waiter, and queued calls on settled records must be refused.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Deletion budget:** Reuse the existing active-record gate; do not add another gate.

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report canon red and lab green runs, behavior changed, files changed, and blockers. Do not weaken assertions.

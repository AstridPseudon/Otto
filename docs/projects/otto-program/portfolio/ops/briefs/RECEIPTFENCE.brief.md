# Brief: RECEIPTFENCE (xhard, 0.5 focused days)

**Outcome:** A failed terminal receipt write retries publication of the same receipt and never reruns the request handler. Read `${TRANSFER_ROOT}/portfolio/ops/prework/RECEIPTFENCE.md` first; report where implementation departs from it.

**Why it matters:** A transient disk-write failure can otherwise make a repeated command effect after the owner scans the request again.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet file-IPC receipt handling and its owner behavior.

**Files you own:** `src/otto/portfolio/execution_host.py`, `tests/test_receipt_fence.py`; only edit these additional paths if directly required: `src/otto/portfolio/manager_journey_client.py`, related focused tests.

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch. Explain additional files in your report. The orchestrator authorized edge overlaps in this wave; landing rebases each lab.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab. Active wave work overlaps `src/otto/portfolio/execution_host.py` (SESSIONFD, FAILEDFENCE, PINALL), `src/otto/agents/claude_adapter.py` (FAILEDFENCE, REWORKWIRE), and `src/otto/portfolio/worker_custody.py` (FAILEDFENCE); coordinate by limiting edits to this row's receipt path and tests.

**Design:** Follow the implementation order in `${TRANSFER_ROOT}/portfolio/ops/prework/RECEIPTFENCE.md`. A changed expectation in `tests/test_manager_reentrant_ipc.py:143` needs the orchestrator's written D19 decision; do not change that assertion until the decision exists. Keep the queued restart replay assertion at line 216.

**Your check:** Add the real atomic-rename failure regression first, show it fails on canon, then passes. Cover the same-host retry and owner restart without redispatch. Do not change existing expectations without D19.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_receipt_fence.py`

**Invariant:** A request handler runs once; only its receipt is retried. Avoid clearing the active token and rerunning a command whose effect may already have happened. Delete or replace the duplicate dispatch/receipt mechanism named in the design.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, red and green checks, deletions, additional files changed, and any blocker. Stop and report if the brief contradicts canon or the outcome is unclear.

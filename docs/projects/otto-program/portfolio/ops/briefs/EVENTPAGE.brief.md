# Brief: EVENTPAGE (xhard, 0.75 focused days)

**Outcome:** Narrow history reads do not materialize unrelated event bodies. Add scoped, cursor-paged selectors using existing event structures; migrate task discovery, backlinks, attention and responsibility deltas; preserve historical visibility and ordering, including unlink/resolution events.

**Why it matters:** Broad history reads hydrate unrelated event bodies and discard historical distinctions when reduced to current identities.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen model (PLAN.md D14, §11). New code goes in `src/herzchen/kernel/store.py`; event storage semantics are shared by products. Keep Otto-specific wiring in Otto. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:** `src/herzchen/kernel/store.py`, `src/herzchen/content/packets.py`, `src/herzchen/domains/work/timeline.py`, `tests/test_eventpage.py`, and directly required caller tests.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additions in your report.

**Do not touch:**
- `src/otto/agents/claude_adapter.py` and `tests/test_landing.py` (CAPTUREEDIT);
- `src/otto/portfolio/execution.py`, `execution_host.py`, `manager_journey_client.py`, `manager_journey_service.py`, and `tests/test_capacity_holds.py` (FAILEDFENCE);
- `ops/bootstrap/land.sh` (LANDPROOF), hostctl stop publication and focused tests (STOPATOM), bootstrap landing files (BOOTLAND), authenticated file access (FILEAUTH);
- `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside your lab.

**Design:** Follow `${TRANSFER_ROOT}/portfolio/ops/prework/EVENTPAGE.md`. Add bounded `page_events` and `page_event_streams` selectors using existing metadata/indexes, with scope-bound keyset cursors and append-position watermarks. Migrate backlink, attention and task-discovery reads while retaining their existing history, visibility and order semantics. Keep the exact-stream timeline gap reader.

**Your check:** Write the hydration-count regression first and prove it fails on unchanged canon. Preserve existing assertions. Run the changed test files and focused callers; report all results and any sandbox-only failures.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_eventpage.py tests/test_perch_timeline.py tests/test_execution_application.py`

**Invariant:** Paging preserves historical links, visibility and cursor deltas exactly.

**Plausible mistake to avoid:** Selecting only current records or dropping unlink/resolution events while narrowing the query.

**Working rules:** Follow `${TRANSFER_ROOT}/portfolio/ops/brief-template.md`. Do not commit or push; the launcher commits on exit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD:** Lead the design and review; delegate almost all implementation to Luna sub-agents via `spawn_agent` with `model: "gpt-6-luna"`. Check each result against the invariant. If a sub-agent fails twice on the same step, sharpen the brief or split the step. In the report, list each sub-agent and any correction.

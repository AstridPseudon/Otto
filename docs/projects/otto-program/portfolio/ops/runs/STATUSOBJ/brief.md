# Brief: STATUSOBJ (normal, 0.25 focused days)

**Outcome:** Damaged private status records return a sanitized unavailable result with a specific schema reason instead of raising during interpretation; valid live records still report running.

**Why it matters:** Status reads are part of manager control and must fail closed on malformed on-disk state without exposing corrupted values as trusted status.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product; status schema and reporting are Otto's owner-control wiring.

**Files you own:** `tests/test_embedded_host_heartbeat.py`, `src/otto/hostctl/service.py`, `tests/test_hostctl_ownersafe.py`.

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch. Explain each addition in your report.

**Do not touch:**
- GATESKIP files: `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py`;
- CODEXOWNER files: `src/otto/hostctl/serve.py`, `src/otto/hostctl/adapters.py`, and its focused real-owner Codex journey tests;
- LANDPROOF files: `tests/test_fleet_custody.py`, `src/herzchen/fleet/labs.py`, `src/herzchen/fleet/landing.py`, `src/otto/hostctl/fleet_landing.py`, `src/otto/hostctl/owner.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/work/assignments.py`;
- SAVEPATH files: `src/otto/portfolio/cli.py`, `tests/test_otto_open_release.py`;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or files outside your lab.

**Build on what exists:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/STATUSOBJ.md` first and report departures. Validate the schema fields used by status interpretation before probing the PID or computing heartbeat freshness. Preserve valid live/stale/draining/closed classifications; return `{ "outcome": "unavailable", "reason": "invalid status schema: <field> ...", "provider_called": False }` for invalid fields without copying damaged values. Compute `busy` only from validated `in_flight` lists and `manager_turn_active`; closed records may omit `in_flight`.

**Your check:** Write the prework regression `EmbeddedHeartbeatTests.test_read_status_rejects_damaged_schema_and_accepts_live_status` first, then run the focused test files. Include private fixtures with malformed holder, in-flight state, heartbeat interval and heartbeat type, plus a valid live status. Keep tests meaningful; don't patch product methods.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_embedded_host_heartbeat.py tests/test_hostctl_ownersafe.py`

**Callers, including production:** If changing a signature, constructor argument, or default, find and update every caller, including `install/controller/`.

**Existing tests:** Do not change an existing test's assertions without a written D19 decision. Never weaken a test to pass in the worker sandbox.

**Regression at the level the friction appears:** Corrupt private status input returns unavailable, while a valid live status remains running.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. On Codex, do not commit; the launcher commits when you exit. Give long test commands a long timeout and let them finish. If a check is blocked only by sandbox permissions, report it for the landing gate.

**On Codex:** Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

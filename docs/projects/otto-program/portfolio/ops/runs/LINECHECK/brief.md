# Brief: LINECHECK (normal, 0.25 focused days)

**Outcome:** Refuse an unusable configured line checkout before starting worker preparation, including when reusing an existing lab; retain the final landing preflight.

**Why it matters:** A worker must not spend a turn on a lab whose configured line is checked out elsewhere or dirty.

**Your lab:** The launcher creates the lab from current `canon/main` and copies this brief. Work only there.

**Layer:** Herzchen fleet for the shared checkout preflight; Otto product calls it during worker preparation.

**Files you own:** `src/herzchen/fleet/landing.py`, `src/otto/hostctl/product_service.py`, `tests/test_fleet_custody.py`, and directly required focused tests.

**Do not touch:**
- CAPTUREEDIT: `src/otto/agents/claude_adapter.py`, `tests/test_landing.py`.
- EVENTPAGE: `src/herzchen/kernel/store.py`, `src/herzchen/content/packets.py`, `src/herzchen/domains/work/timeline.py`, its focused tests.
- BOOTLAND: bootstrap landing files.
- FAILEDFENCE: `src/otto/portfolio/execution.py`, `execution_host.py`, `manager_journey_client.py`, `manager_journey_service.py`, `tests/test_capacity_holds.py`.
- production/, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside the lab.

**Design:** Follow `ops/prework/LINECHECK.md`. Extract the configured-branch, HEAD-at-tip, and clean-status preflight from `LandingService._assert_line_clean` in `src/herzchen/fleet/landing.py` into a shared callable. Use it at all existing landing checks and from `src/otto/hostctl/product_service.py` under the pair lock before either creating or reusing a lab. Keep the final landing check.

**Your check:** Add the described regression in `tests/test_fleet_custody.py`: a valid configured branch that is not checked out refuses before lab creation; a dirty line refuses when reusing a lab; a clean configured line succeeds. Preserve existing assertions. Run the changed test files and focused callers; report sandbox-only failures.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py tests/test_landing.py`

**Working rules:** Follow `ops/brief-template.md`. Do not commit or push; the launcher commits on exit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Never weaken tests in the worker sandbox.

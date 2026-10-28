# Brief: TOOLING26 (normal, 0.25 focused days)

**Outcome:** The landing gate reads a D19 verdict only from its explicit Decision line. A SEND BACK decision must not be mistaken for LAND because the heading contains a task name such as BOOTLAND, and a file without an explicit verdict is refused with its path.

**Your lab:** The launcher creates the TOOLING26 lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product. The change belongs to the program landing gate.

**Files you own:** `ops/bootstrap/land.sh` and focused tests in `tests/test_bootstrap_gate.py`.

**Do not touch:** `tests/test_act_activation.py` (ACTIVATEWHILE), `tests/test_manager_journey_service.py` (GATESKIP), `src/herzchen/fleet/hosts/contract.py`, `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/tools/facade.py`, `src/otto/agents/claude_adapter.py`, owner continuation callers, or the test files named by REWORKWIRE's resume; also do not touch `production/`, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Your check:** Add cases beside the gate tests proving that a SEND BACK verdict in a heading containing LAND is refused, an explicit LAND verdict is accepted, and a missing Decision line is refused with its file named. Keep the focused gate suite green.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Working rules:** Do not run staging-owner tests in the worker sandbox. Never stash, switch commits, or run ottoctl. Do not commit or push; the launcher commits on exit. Keep tests running to completion and report results. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

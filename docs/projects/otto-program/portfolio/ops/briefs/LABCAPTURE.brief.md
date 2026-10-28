# Brief: LABCAPTURE (xhard, 1.0 focused days)

**Outcome:** A landed worker's turn settles from its captured result, and its lab is removed only after that capture. Failed removal is retried and landed leftovers are swept at owner start. Delete the fake cleanup hooks so stage 2 observes the real owner lab lifecycle.

**Your lab:** `lab/LABCAPTURE`, branch `lab/LABCAPTURE`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Herzchen fleet. New code belongs in the fleet/owner lifecycle; keep Otto staging wiring limited to deleting the named test-only cleanup hooks.

**Files you own:** `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/labs.py`, `src/otto/agents/claude_adapter.py`, the corresponding real-owner regression tests (`tests/test_landing.py`, `tests/test_fleet_custody.py`, `tests/test_external_owner_execution.py`), and `ops/bootstrap/perch_stage2_owner.py` / `ops/bootstrap/perch.sh` only to remove `defer_fake_lab_cleanup` and `stage2_cleanup_owner_labs`.

**Other files:** Edit another caller or fixture only when directly required; report each. Keep the change limited to post-turn artifact capture/removal and the named fake-cleanup deletion. `execution_host.py` and its capacity behavior belong to KILLFENCE; do not change that concern. `perch_report.py` and process census behavior belong to ORPHANWORKER; do not change that concern.

**Do not touch:** The files or changes owned by concurrently launched KILLFENCE, ORPHANWORKER, and COMPLETECITE; `production/`; any Store, `~/.otto` or `~/.codex`; Codex project configuration; anything outside this lab.

**Build on what exists:** `src/herzchen/fleet/landing.py` (`LandingService`), `src/herzchen/fleet/labs.py` (`LabFleet.remove` / `sweep`), and `src/otto/agents/claude_adapter.py` (`capture_artifacts`). Inspect current line numbers in this lab.

**Your check:** Add a real-owner fake-Claude-stream regression (Write then `done`) proving completion and capture before lab deletion; failed removal retry; landed leftover sweep at owner start. On `canon/main` the regression must fail first, then pass. Also prove `grep -n LabFleet ops/bootstrap/perch_stage2_owner.py` is empty.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_landing.py tests/test_fleet_custody.py tests/test_external_owner_execution.py`

**Regression at the level the friction appears:** Real owner turn settlement after landing and artifact capture.

**Invariant:** A landed worker's turn settles from its captured result, and its lab is removed only after that capture.
**Plausible mistake:** Capturing from the landed commit, or skipping capture when the lab is gone, so a missing artifact settles completed.
**Deletion budget:** Delete `defer_fake_lab_cleanup` and `stage2_cleanup_owner_labs`; one real post-settlement cleanup path replaces the staging workaround.

**Orchestrator-run acceptance:** Do not start a staging Otto in your sandbox. Report that stage 2 `--fake` with `labs-left-behind` reading `canon.otto-labs` requires the orchestrator run.

**Codex rules:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: use a long timeout or keep reading its session until it exits; never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD:** Lead the design and invariant review; delegate execution to Luna sub-agents using `spawn_agent` with `model: "gpt-6-luna"`. Review the diff and test tail yourself. Report each sub-agent and any corrections. Never run staging-owner tests in your sandbox.

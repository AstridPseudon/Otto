# Brief: ORPHANWORKER (normal, 0.5 focused days)

**Outcome:** Forced owner stop and owner startup terminate every live worker process group recorded in `capacity-process-groups.json` only when the recorded process birth time still matches. Perch fails at start when any worker or `perch-fake-claude` process from any staging root is alive, and at down confirms every recorded worker group is gone.

**Your lab:** `lab/ORPHANWORKER`, branch `lab/ORPHANWORKER`, from `canon/main` at `5b4a7709ec6e89aba8f8d1f8fe3876f55ee728cf`. Work only here.

**Layer:** Otto product process custody and staging verification.

**Files you own:** `src/otto/agents/claude_cli.py`, `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, and focused process-custody/staging tests (`tests/test_worker_custody.py`, `tests/test_perch.py`).

**Other files:** Edit another direct caller or fixture only when required and report each. Keep changes to process-group records, forced-stop/startup cleanup and the cross-root census. `execution_host.py` kill/recovery and capacity fences belong to KILLFENCE; do not change those. Artifact capture/removal belongs to LABCAPTURE.

**Do not touch:** The files or changes owned by concurrently launched LABCAPTURE, KILLFENCE, and COMPLETECITE; `production/`; any Store, `~/.otto` or `~/.codex`; Codex project configuration; anything outside this lab.

**Build on what exists:** Owner process termination in `src/otto/agents/claude_cli.py`, recorded process groups, and `leaks()` in `ops/bootstrap/perch_report.py`; inspect current line numbers in the lab.

**Your check:** Add a forced-stop test proving the fake worker is gone; a stale PID whose birth time differs is left alone. On canon show the new regressions fail, then pass. Stage 2 `--fake` with global start/down assertions is an orchestrator run; do not run it in your sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_worker_custody.py tests/test_perch.py`

**Regression at the level the friction appears:** Forced owner stop followed by a cross-root live-process census.

**Codex rules:** You can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end: use a long timeout or keep reading its session until it exits; never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

Never run a test that starts a staging owner in the worker sandbox (`tests/test_staging_startup.py`, `tests/test_perch_staging.py`, or staging cases of `tests/test_perch.py`); the landing gate runs those. Do not weaken process tests or stub `ps`.

# Brief: TOOLING16 (normal, 0.1 focused days), done by the orchestrator

**Title:** Codex spend takes a task's last run file, as claude does

**Outcome:** A resumed Codex session's `turn.completed` reports the thread's running total (16 Oct: ASK's runs read 47.1M, 53.4M, 55.5M input; COMPOSEFLEET's 13.2M, 46.6M, 59.8M). `workers.py spend` summed them, which overstated the usage. It now takes the last file per task for Codex, as it does for claude.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

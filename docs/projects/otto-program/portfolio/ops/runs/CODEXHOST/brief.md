# Brief: CODEXHOST (normal, 0.25 focused days), done by the orchestrator

**Title:** Workers run on Codex (Luna, Sol) with run-task.sh --host codex

**Outcome:** The user moved the program to Codex models on 16 Oct 2026 (Luna instead of Haiku, Sol instead of Sonnet). `run-task.sh --host codex` starts a worker with `codex exec` in its lab: normal is gpt-6-luna (high), xhard is gpt-6-sol (xhigh), with Codex's workspace-write sandbox and otto-heavy's state writable. Codex names the session (`thread.started`), which goes in workers.json; `--resume` uses `codex exec resume`. Codex keeps `.git` read-only in its sandbox (probed 16 Oct: `Unable to update HEAD: Operation not permitted`), so the launcher commits what the worker leaves when it exits, even after the watchdog's TERM. The default host is `$OTTO_WORKER_HOST`, else `$OPS_DIR/worker-host`, else claude. `workers.py spend` takes the last claude run file (a resumed session's total is cumulative) and sums codex tokens.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

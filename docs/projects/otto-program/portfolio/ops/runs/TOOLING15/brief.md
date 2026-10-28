# Brief: TOOLING15 (normal, 0.1 focused days), done by the orchestrator

**Title:** The launcher finishes a stopped rebase with the worker's resolution

**Outcome:** A landing whose rebase conflicts leaves the lab mid-rebase, with conflict markers in the files. A Codex worker can resolve the markers but can't run git (its sandbox keeps `.git` read-only), so RETIRE's conflict (16 Oct) needed the orchestrator. `commit_worker_changes` now detects a rebase in progress. If markers remain, it leaves the rebase stopped and says so. Otherwise it stages the resolution and runs `git rebase --continue`, instead of making a new commit.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

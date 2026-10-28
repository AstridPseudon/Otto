# Brief: TOOLING11 (normal, 0.25 focused days), done by the orchestrator

**Title:** Launcher commits in real labs, holds no caller pipe; the sweep counts the check's run

**Outcome:** (1) `commit_worker_changes` commits in labs that ignore `.brief.md`: it no longer names ignored files in `git add` (16 Oct: LAND's draft went uncommitted, "run-task.sh: commit failed"). (2) The Codex worker's subshell holds no stdio of the caller (it hung the manager loop until the worker ended). (3) The gate's sweep counts the passing check's run of a test file the check names whole (no `-k` or `::`), so it runs that file once more instead of twice: three runs of the same file became two.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

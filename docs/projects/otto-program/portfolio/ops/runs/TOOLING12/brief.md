# Brief: TOOLING12 (normal, 0.1 focused days), done by the orchestrator

**Title:** Codex workers can run socket tests (sandbox network access on)

**Outcome:** Codex's workspace-write sandbox refuses AF_UNIX bind and connect unless `sandbox_workspace_write.network_access` is on (probed 16 Oct with `codex sandbox`: refused without it, works with it). Most Otto tests start an owner on a Unix socket, so SAVEFIX couldn't run its tests. `run-task.sh` turns network access on for Codex workers; `.git` stays read-only.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

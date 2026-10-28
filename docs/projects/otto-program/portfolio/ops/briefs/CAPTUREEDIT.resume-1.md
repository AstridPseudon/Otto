# CAPTUREEDIT resume 1 (xhard)

**Outcome:** Fix the new landing-gate failure in `tests/test_hostctl_serve.py::ManagerLoopTests::test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results`. The gate reproduced it 3/3 on the CAPTUREEDIT candidate and 0/3 on BASE. Read `${TRANSFER_ROOT}/portfolio/ops/runs/CAPTUREEDIT/land.log` and the pair-1 lab outputs under `${TRANSFER_ROOT}/portfolio/ops/runs/CAPTUREEDIT/.gate/` for evidence. The timeout reports missing `run-worker-2.json` and `manager-turn-4.txt` after 185 seconds.

Preserve CAPTUREEDIT's authorized artifact-capture invariant and fix the actual manager dispatch/resume cause. Do not weaken, skip, delete, or alter existing assertions. Do not treat `tests/test_tools.py::test_owner_failure_is_generic` as new; the gate reproduced that failure on BASE too.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CAPTUREEDIT`, branch `lab/CAPTUREEDIT`; the manager rebases it onto current canon before resuming. Work only in this lab.

**Do not touch:** files owned by running workers: LANDPROOF (`ops/bootstrap/land.sh`), STOPATOM (hostctl stop publication and focused tests), BOOTLAND (bootstrap landing), FILEAUTH (authenticated file access), and ROLEIDS (hostctl identity/admission and manager journey). Also do not touch production, Stores, `~/.otto`, `~/.codex`, or anything outside this lab.

**Your check:** Run the CAPTUREEDIT task tests and the failing manager test file to completion. The manager test file can take several minutes; keep the command running until it exits. Report the cause, exact changed files, and results. Do not run staging-owner tests in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_landing.py tests/test_hostctl_serve.py`

**Invariant:** A landed worker's result is exactly the bytes its own authorized tool calls produced.

**Plausible mistake to avoid:** Capturing the whole lab diff or landed tree, which could include bytes the worker never produced.

**Working rules:** Follow the Codex rules in `${TRANSFER_ROOT}/portfolio/ops/brief-template.md`: no commits or pushes; the launcher commits on exit. Long tests must run to completion. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

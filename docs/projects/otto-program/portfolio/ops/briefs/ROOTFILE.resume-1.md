# Resume: ROOTFILE (normal)

**Outcome:** Fix the landing refusal exposed by effect 944, then leave the ROOTFILE lab ready for a new landing.

**Failure:** The landing's own check failed at `tests/test_bootstrap_gate.py::LandGate::test_src_and_tests_additions_remain_eligible_to_land`. See `${TRANSFER_ROOT}/portfolio/ops/runs/ROOTFILE/.gate/check.txt` and `${TRANSFER_ROOT}/portfolio/ops/runs/ROOTFILE/land.out`. The intended behavior is that labs adding only `src/` and `tests/` paths remain eligible to land.

**Scope:** Work in the ROOTFILE lab. Keep the task outcome and top-level-file protection intact. Do not touch PINALL-owned files while PINALL runs, `src/herzchen/fleet/custody.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, or `tests/test_claude_manager_admission.py`. Do not touch production/, Stores, ~/.otto, ~/.codex, Codex project configuration, or anything outside this lab.

**Check:** Run `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py` to completion and report the result and `git diff --check`. Leave changes uncommitted for the launcher.

**Working rules:** Follow `ops/brief-template.md`'s Codex rules; never wait or poll. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

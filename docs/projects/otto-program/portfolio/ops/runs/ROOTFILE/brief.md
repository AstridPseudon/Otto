# Brief: ROOTFILE (normal, 0.25 focused days)

**Outcome:** Remove the stray `D19.md` from canon and prevent a landing from adding any unapproved top-level file. Add a gate regression that sees the named refusal for a lab adding a top-level file, while a lab with only `src/` and `tests/` additions still lands.

**Why it matters:** The landing gate must keep worker notes and other accidental files out of the repository root.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROOTFILE`, on branch `lab/ROOTFILE`, from `canon/main`. Work only there.

**Layer:** Otto product (landing gate and its tests; no Herzchen product code).

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, and deletion of root `D19.md`.

**Other files:** You may also edit any other file the outcome directly requires, except Do not touch. List each one and the reason in your report.

**Do not touch:** PINALL-owned files while PINALL runs; `src/herzchen/fleet/custody.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, `tests/test_claude_manager_admission.py`; `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** `ops/bootstrap/land.sh` rebases and checks a lab before merge; add the top-level diff refusal to those early checks. `tests/test_bootstrap_gate.py` has a temporary-repository harness and `lab()` helper for constructing committed labs.

**Your check:** Add focused gate tests for (1) a root-level file being named in the refusal and (2) only `src/` and `tests/` paths remaining eligible; run the test file.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** A landing attempt that adds a top-level file is refused before the full sweep and identifies that path.

**Working rules:** Follow the Codex normal rules in the manager brief template. D19 notes and reports go in `ops/runs/ROOTFILE/`, never in the lab. Leave changes uncommitted for the launcher. Give long test commands a long timeout and let them finish.

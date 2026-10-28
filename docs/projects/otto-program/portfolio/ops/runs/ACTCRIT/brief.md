# Brief: ACTCRIT (normal, 1.25 focused days)

**Outcome:** Product activation declares each task's required assessment scope from the registered run's criteria, idempotently, through the product assessment module. `project status` reports each task's retained dispatch state (admitted, launched, landed, or failed with its reason) from product records. Add product and regression coverage for both behaviors.

**Why it matters:** Stage 2 must observe product behavior as shipped. A real project must carry its required scope after activation, and operators need to see the dispatch state without harness-only owner patches.

**Your lab:** `~/Developer/otto-claude-host/labs/ACTCRIT`, on branch `lab/ACTCRIT`, from `canon/main` at `84164d4bc3196d822c8416de801e588622cc9dd5`. Work only here.

**Layer:** Otto product. New code belongs in the product's `src/` modules; tests belong in `tests/` or the relevant product test package.

**Files you own:** `src/`, `tests/` (product code and tests only; do not edit ops/bootstrap).

**Other files:** You may edit other product source or test files required by this outcome, but keep changes within `src/` and `tests/` for this product step.

**Do not touch:**
- `ops/bootstrap/` until PERCH2B lands; its harness patch removal is a later resume step.
- `production/`, Store data, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.
- Files owned by running tasks: PERCH2B owns its task files under `ops/bootstrap/`.

**Build on what exists:** Use the existing activation and assessment paths, including `src/otto/portfolio/reviewed_activation.py`, `src/otto/portfolio/assessment.py`, `src/herzchen/domains/assessment/module.py`, and existing activation coverage in `tests/test_act_activation.py`. Find and extend the product-backed `project status` path and its tests rather than adding a second source of dispatch state.

**Your check.** Add regression tests showing activation declares required scopes from registered run criteria and replay does not duplicate declarations; show `project status` reports dispatch state and failure reason using product records. Run the changed test files. Never weaken a test to pass in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_hostctl_cli.py`

**Regression at the level the friction appears:** a registered project's tasks carry required scope after activation; replay is idempotent; status exposes product dispatch state without a harness patch.

**Working rules:** Never weaken a test to pass in the worker sandbox. Follow the Codex working rules in the brief template; leave the commit for the launcher.

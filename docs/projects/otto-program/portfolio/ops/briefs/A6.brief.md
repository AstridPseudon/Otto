# Brief: A6 (normal, 1.0 focused days)

**Outcome:** Delete the document sync mirror: `src/otto/hostctl/sync.py` and the `sync-docs` command, its baselines, apply's document sync, and `src/otto/portfolio/shared_documents.py`'s manifest copy and caller in `src/otto/hostctl/portfolio.py`. Refuse to register a folder that is already registered. Keep Vision's document reads working.

**Why it matters:** There should be one source of truth for project documents, without a parallel sync mechanism or manifest mirror.

**Your lab:** `labs/A6`, on branch `lab/A6`, from `canon/main` at `4145f22`. Work only here.

**Layer:** Otto product. New code stays in `src/otto/hostctl/` and `src/otto/portfolio/`; do not add Herzchen code. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/hostctl/sync.py`
- `src/otto/hostctl/portfolio.py`
- `src/otto/portfolio/shared_documents.py`
- `tests/test_hostctl_sync.py`
- `tests/test_hostctl_portfolio_apply.py`
- `tests/test_portfolio_shared_documents.py`
- `tests/test_hostctl_portfolio.py`
- `tests/test_owner_vision_installation.py`

**Other files:** You may edit any other file directly required by the outcome, except files under Do not touch. List each in your report with the reason.

**Do not touch:**
- AUTODISPATCH landing files: `src/otto/hostctl/product_service.py`, `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_service.py`, `src/herzchen/fleet/dispatch.py`, `tests/test_fleet_dispatch.py`, `tests/test_execution_host_manager_turn_queue.py`, `tests/test_manager_journey_service.py`.
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** The portfolio command and caller are in `src/otto/hostctl/portfolio.py` (parser at line 47; `sync-docs` handling around lines 147-151); apply's document sync is in the same module. The manifest copy lives in `src/otto/portfolio/shared_documents.py`. Preserve the existing Vision document read path and the current registered-root behavior where it does not depend on the mirror.

**Your check.** Make the task's tests green, including the refusal when registering a duplicate folder and Vision document reads. Keep existing assertions honest; do not retain sync-specific behavior to satisfy old tests. Regression tests must fail on `canon/main` first and show both runs. Run changed or added test files.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_sync.py tests/test_hostctl_portfolio_apply.py tests/test_portfolio_shared_documents.py tests/test_hostctl_portfolio.py tests/test_owner_vision_installation.py tests/test_herzchen_boundary.py`

**Regression at the level the friction appears:** Registering a folder already registered is refused, while Vision can still read documents.

**Deletion budget:** Remove the sync mirror and its baselines/manifest copy as part of this task; report every removed mechanism.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl` (including `--help`). Never wait or use background jobs you then wait on; run tests in the foreground. Don't change existing test assertions just to make them pass. A long test runs to completion (use a long timeout). **On Codex (Luna):** leave changes for the launcher to commit; do not push. Any sub-agent you start must use `spawn_agent` with `model: "gpt-6-luna"`. If blocked, decide within the brief or report the question.

**When done:** Leave changes for the launcher to commit and report the commit, check results, deletion and anything incomplete.

# Brief: PINCONTENT (xhard, 1.0 focused day)

**Outcome:** A task pin holds across metadata-only revisions, as admission does, while any content change still breaks the pin. Use `admission.content_digest` and one shared helper for every mandate or route that pins a task revision and checks it against the current revision. Remove PERCH2B's manager-mandate rebind from `ops/bootstrap/perch_stage2_owner.py` after the product behavior is implemented.

**Why it matters:** Admission adds a metadata revision. A manager activated before admission currently pins the earlier revision and dispatch refuses, so every project activated before its tasks are admitted is affected.

**Your lab:** `~/Developer/otto-claude-host/labs/PINCONTENT`, on branch `lab/PINCONTENT`, from `canon/main`. Work only here.

**Layer:** Herzchen model. New code belongs in `src/herzchen/`.

**Files you own:** `src/herzchen/domains/work/module.py`; related route/mandate modules under `src/herzchen/` that compare pinned task refs; focused regression tests in `tests/`.

**Other files:** You may edit other source and test files the outcome directly requires. You may also remove the temporary rebind from `ops/bootstrap/perch_stage2_owner.py` once your product behavior is proven; explain this change in your report.

**Do not touch:**
- PERCH2B's files while its resume runs, especially `ops/bootstrap/` and `tests/test_perch.py`;
- ACTCRIT's `src/` and `tests/` while its landing runs;
- `production/`, Store data, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `WorkModule.admit` in `src/herzchen/domains/work/module.py` uses `admission.content_digest` when it records the admitted revision. Find and consolidate the pin comparisons used by mandates and owner dispatch rather than adding a separate exception at each call site.

**Your check:** Test activate → admit → dispatch; a content edit after the pin still refuses; forged metadata cannot make different content match. Extend the existing manager-mandate and fresh-manager admission coverage.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_mandate_reconciliation.py tests/test_fresh_manager_admission.py tests/test_fleet_dispatch.py`

**Regression at the level the friction appears:** activate, then admit, then dispatch succeeds; a later content change is refused.

**Invariant:** A pin protects task content, not its metadata; any content change breaks it.

**Plausible mistake to avoid:** Comparing revision ids loosely, or treating every metadata namespace as non-content when one of them carries content.

**Deletion budget:** Replace the per-revision pin check with one shared content-aware helper; remove the PERCH2B manager-mandate rebind after this behavior works.

Follow the XHARD and Codex working rules in `ops/brief-template.md`: Sol leads and delegates execution to Luna `spawn_agent` sub-agents; never weaken tests to pass in the worker sandbox. The staging check needs an external landing gate, so report that rather than running `perch.sh` in the sandbox.

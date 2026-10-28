# Brief: TOOLING23 (normal, 0.5 focused days)

**Outcome:** Each landing runs its check and sweep with its own short private temporary root in `TMPDIR`. The orphan census refuses only a new orphan whose home is under that landing's root; owners under another session's temp root are ignored. Staging tests use that `TMPDIR` for their roots so socket paths stay short.

**Why it matters:** A landing must only be refused for a service owner its own check or sweep left running. An unrelated investigation or worker must not block it.

**Your lab:** `lab/TOOLING23`, on branch `lab/TOOLING23`, from `canon/main` at `359a9c05e8955649f0c970ae6fbabf6e35e6b649`. Work only here.

**Layer:** Otto product. Gate code is in `ops/bootstrap/land.sh`.

**Files you own:** `ops/bootstrap/land.sh` (private temp root, TMPDIR propagation and root-scoped orphan census), `tests/test_bootstrap_gate.py` (gate regressions for own-root refusal and unrelated-root ignore), `tests/test_staging_startup.py` and `tests/test_perch_staging.py` (use the short inherited TMPDIR for staging roots).

**Other files:** You may also edit any other file the outcome directly requires, except files under “Do not touch”; list each in your report with the reason. Do not stop to ask for a file.

**Do not touch:**
- Files owned by any task running now: none.
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** In canon `ops/bootstrap/land.sh`, `temp_owners` around lines 171–199 currently checks `$TMPDIR`, `/tmp`, and `/private/tmp`; the before/after census is around lines 387–390. `tests/test_bootstrap_gate.py` around lines 147–175 covers pre-existing owners, live owners with a parent, and new orphan refusal. `tests/test_staging_startup.py` around line 71 and `tests/test_perch_staging.py` around line 24 currently choose `/tmp` directly; keep their roots short while honoring inherited `TMPDIR`.

**Your check:** Add gate coverage proving an orphan in this landing's root is named/refused and an owner under another root is ignored. Regression tests must fail on `canon/main` first, then pass in the lab. Run the focused gate test file. Do not run staging-owner tests in the worker sandbox: `tests/test_staging_startup.py` and `tests/test_perch_staging.py` need process inspection and writes outside the lab; the landing gate runs them outside the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** A landing refuses an orphan it created under its own root, while ignoring an orphan under another concurrent session's temp root.

**On Codex:** You can't commit; leave work in the lab for `run-task.sh` to commit. Long test runs must run to completion with a long timeout. A sandbox-only `sandbox_apply: Operation not permitted` failure should be listed for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

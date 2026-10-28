# Brief: PARITYFIX (normal, 0.5 focused days)

**Outcome:** Pack parity evidence survives checkout relocation and unrelated loader edits. Run identical fixture content under two roots with correctly rooted independent provenance; both pass. A comment-only loader change preserves parity. Forced setup and assertion failures leave no source-checkout files or nested repository, while tampered pack bytes still refuse.

**Why it matters:** Portable provenance evidence must describe the immutable pack bytes rather than a particular checkout path or mutable loader implementation.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PARITYFIX`, on branch `lab/PARITYFIX`, from `canon/main`. Work only here.

**Layer:** Herzchen model. New or changed code belongs in the existing provenance fixture and evidence lifecycle test; do not change production admission behavior.

**Files you own:**
- `tests/test_evidence_lifecycle.py`
- `tests/fixtures/managed_source_provenance/record_astrid_provenance.py`
- `tests/fixtures/managed_source_provenance/recorded_source.json`

**Other files:** Do not edit unless the outcome directly requires them; list any such paths and why in your report.

**Do not touch:**
- Active landing FAILEDFENCE: `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_client.py`, `src/otto/portfolio/manager_journey_service.py`, `tests/test_capacity_holds.py`.
- Active worker OPPRE: `src/herzchen/domains/work/orchestration.py`, `src/otto/portfolio/herzchen_binding.py`, `src/otto/portfolio/owner_bootstrap.py`.
- `production/`, any Store, `~/.otto`, `~/.codex`, or anything outside this lab.

**Build on what exists:** `_prepare_recorded_provenance_checkout` in `tests/test_evidence_lifecycle.py`; the recording utility and `recorded_source.json`; `authoring.py`'s rooted inventory admission and hashing. Preserve Git and resource-byte admission checks.

**Your check:** Run the changed test file. Regression tests must fail on canon/main first and pass after the change. Keep materialization and assertions inside temporary-checkout cleanup. Do not run staging tests in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_lifecycle.py`

**Regression at the level the friction appears:** Two-root provenance parity, comment-only loader edit, cleanup after forced setup/assertion failure, and refusal of tampered pack bytes.

**Deletion budget:** Replace the existing root-bound parity setup with portable recorded vectors and temporary checkouts; do not add a parallel provenance mechanism.

**Working rules:** Follow the Codex rules in `ops/brief-template.md`: do not commit or push, and leave the lab ready for the launcher to commit. Long tests must run to completion. Do not weaken tests to pass in the sandbox. Do not stop to ask for a file when the outcome itself remains clear.

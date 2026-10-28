# Brief: LANDEVIDENCE (xhard, 0.5 focused days)

**Outcome:** Landing passes the exact evidence refs from the check that passed on the rebased commit into the assessment freeze-input, so the assessment accepts only work backed by that check's retained evidence.

**Why it matters:** Stage 2 now reaches freeze-input after the assessment fixes, but the owner refuses because the landing supplies no evidence refs. The check's existing receipt/evidence must flow into acceptance without inventing a reference.

**Your lab:** `lab/LANDEVIDENCE`, on branch `lab/LANDEVIDENCE`, from `canon/main` at `ccc075affd1dd725765f82d26c49bf19176a2530`. Work only here.

**Layer:** Otto product. Keep the wiring in Otto's landing adapter and reuse the existing runner and evidence records.

**Files you own:**
- `src/otto/hostctl/fleet_landing.py` — assessment input currently sends `evidence_refs: []`; pass exact refs from the verified runner check result.
- `src/herzchen/fleet/landing.py` — authoritative check result is produced and passed into the assessment context.
- `src/herzchen/fleet/runner/store.py` — sealed runner result lookup and receipt identity, if required to resolve the exact retained evidence.
- `src/herzchen/evidence/commands.py` — existing evidence recording/resolution path; use it if the check has no evidence record.
- `tests/test_fleet_custody.py`, `tests/test_landing.py`, `tests/test_evidence_wiring.py` — focused regression coverage for exact check evidence through freeze-input and acceptance.

**Other files:** You may edit any additional file directly required by this outcome, except files under Do not touch. List each one with its reason in your report. Do not add a synthetic evidence ref or treat the commit/candidate as evidence unless the existing evidence path defines it as such.

**Do not touch:** No other task is running. Do not touch `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Reuse `LandingService._prepare` and `_accept_and_advance` in `src/herzchen/fleet/landing.py`, its authoritative `result_lookup`, the sealed result in `src/herzchen/fleet/runner/store.py`, and the existing evidence path in `src/herzchen/evidence/commands.py`. In `src/otto/hostctl/fleet_landing.py`, feed only the evidence refs tied to the exact passing, rebased commit and runner result into `freeze-input`.

**Your check.** Exercise `done` through the real landing assessment adapter: the exact passing check evidence is frozen and accepted; failed checks, a different commit's result, or absent/unresolvable evidence cannot be accepted. The orchestrator will rerun stage 2 against the landed change. Do not run staging-owner tests in the worker sandbox; the landing gate runs them.

**Check command:** `rc=0; for f in tests/test_fleet_custody.py tests/test_landing.py tests/test_evidence_wiring.py; do /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$f" || rc=1; done; exit $rc`

**Regression at the level the friction appears:** Activate, admit, dispatch, and call `done` after the exact rebased-commit check passes; verify the resulting frozen input cites that check's retained evidence and acceptance succeeds. A failed check or mismatched/absent evidence must refuse.

**XHARD only:**
- **Invariant:** An accepted task's assessment cites the exact evidence of the check that passed on the committed lab.
- **Plausible mistake to avoid:** Passing a placeholder, the lab commit, or a result from another check as evidence.

**Deletion budget:** Extend the existing check-result/evidence path; do not add a parallel receipt or acceptance mechanism.

**Working rules:** Follow `ops/brief-template.md` Codex rules verbatim. XHARD: lead and delegate execution to Luna `spawn_agent` sub-agents; review each result against the invariant and report each sub-agent's work. Do not weaken existing assertions. Leave work uncommitted for the launcher; do not push. Run checks to completion.

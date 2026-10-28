# Brief: AUTODISPATCHREC (xhard, 0.75 focused days)

**Outcome:** Every automatically launched task is dispatched through `WorkAssignments.dispatch`, so its dispatch stream contains exactly one `work.assignment.dispatched` event before its worker starts. A replayed pump tick adds no dispatch, and an unadmitted revision is refused by the work domain's admission gate. Stage 2 `--fake` passes `stage2-store-snapshots`.

**Why it matters:** An automatic launch currently bypasses the work domain's dispatch gate and audit record. Launches must be admitted and recorded through the same domain API that governs manual dispatch.

**Your lab:** `lab/AUTODISPATCHREC`, on branch `lab/AUTODISPATCHREC`, from current `canon/main`. Work only here.

**Layer:** Otto product. New code goes in `src/otto/`.

**Files you own:**
- `src/otto/portfolio/product_service.py`
- `src/otto/portfolio/manager_journey_service.py`
- `tests/test_fleet_dispatch.py`

**Other files:** You may edit other files the outcome directly requires, except those under Do not touch. List each in your report with the reason. In particular, the domain API is `src/herzchen/domains/work/assignments.py`; change it only if the product cannot use its existing `WorkAssignments.dispatch` contract.

**Do not touch:**
- The files of tasks running now: STAGE2C landing owns `ops/bootstrap/perch_report.py`, `ops/bootstrap/perch.sh`, and `tests/test_perch.py`.
- `production/`.
- Any Store, `~/.otto` or `~/.codex`.
- Codex's projects, vision and Native5.
- Anything outside this lab.

**Build on what exists:** Route the automatic launcher through `WorkAssignments.dispatch` in `src/herzchen/domains/work/assignments.py` (around lines 795-817), and reuse the automatic pump/launch path in `src/otto/portfolio/product_service.py` and `src/otto/portfolio/manager_journey_service.py`. Dispatch is idempotent by logical request key and applies `_admitted_scope` to new dispatches.

**Your check:** Add real-owner regression coverage for one recorded dispatch per automatic launch, idempotent replay, and refusal of an unadmitted revision. Demonstrate the new regression failing on canon before the fix, then passing. The stage-2 `--fake` journey starts a staging owner and cannot run in the worker sandbox; the landing gate runs it outside.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_dispatch.py`

**Regression at the level the friction appears:** Stage 2 `--fake` reports the automatic launches in Store snapshots, with exactly one dispatch per assignment.

**XHARD invariant:** Every launch is a dispatch the Store records, admitted by the work domain's own gate.

**Plausible mistake to avoid:** Writing a dispatch event beside the launch instead of going through `dispatch()`, leaving the gate bypassed.

**Working rules:** Follow `ops/brief-template.md`, including Codex rules and long-test guidance. On Codex, do not commit; the launcher commits when you exit. Never run `ottoctl`, staging or owner-starting tests in the worker sandbox; never weaken tests to pass there; never wait or poll.

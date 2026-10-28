# Plan: how the Otto program runs

The decisions, layering and rationale live in the shared document `portfolio/PLAN.md`; agent UX is in `portfolio/AGENT-UX.md`. The tasks, with routes, deps and checks, are in this project's tasklist.md.

**How the work runs:** the full instructions are in the shared `portfolio/RUNBOOK.md`. In short:
- **Bootstrap (until CUTOVER, PLAN.md D6):**
  - Each task is one `claude -p` session in a lab: Haiku for normal tasks, a Sonnet lead with Haiku sub-agents for XHARD.
  - At most 2 run at once. Checks run through `otto-heavy`.
- **Landing (D19):**
  - the task's check on the rebased commit;
  - every changed module's test files, run alone and twice;
  - the staging Otto restarted on the merged commit (D17);
  - an Opus decision if existing tests' expectations changed.
- **Validation (D20, PLAN.md §16):** nine stages on the staging Otto, each a live run of the canary project and the observation perch, examined by a fresh Opus reviewer with Haiku helpers.
- **The Opus budget:** 15 calls in all.
- **CUTOVER:**
  1. Save every upcoming project into a new Otto on local disk, and verify each save.
  2. Switch the clients over.
  3. Delete the old Store.

  After that, Otto dispatches natively, and the manager is woken for judgment.

**Order:** SKEL0's chain first (STAGE and PERCH early); then by longest remaining path (RUNBOOK §8).

**Size:** about 34 focused days for edition 1, which is about 17 hours of continuous running on 2 workers, as measured. Stage runs, reviews and go points come on top.

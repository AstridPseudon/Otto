## Verdict: rebase and finish

`proj/slim` has useful, reviewed reductions, but its own tasklist marks the core manager-replacement route, the agent UX pass, dependent docs work, and the deletion budget as blocked. It is not ready to land as a completed “one way to do each thing” project.

### Done

The branch is `2df7571` (`Record final Astra re-review and gate checks`), based on merge base `163925e`; the comparison canon is `a70b3f2`. The branch log records 63 commits ahead of that base, with **57 files changed, 1,974 insertions and 2,391 deletions**. Its own audit measures **1,656 top-level portfolio lines deleted and 346 added**, for 1,310 net lines removed from the 47,920-line baseline. That is short of the 11,980-line target by 10,670 lines. [Branch tasklist](../otto/projects/slim/.project/tasklist.md:3) and [review record](../otto/projects/slim/.project/PROJECT.md:191)

Notable completed work:

- Retired the proof-only Events and observability modules and their wrappers: 535 source lines deleted. Commits `9fdc4be`, `cd4d611`.
- Routed more reads through `otto show` and removed root `overview`, `tasks`, and `task` routes. The `events` compatibility route remains. Commit `a49a5ab`.
- Added bounded `otto status --friction`. Commit `24eeda2`.
- Removed dormant packet/resume modules and exports (`553` lines), a test-only advisor host module and its test (`305` lines), the inert `otto-gateway` entrypoint and `src/otto/cli.py`, and an unreachable installed `admit` route. Commits `a7feacf`, `3053409`, `f935261`, `9b4a1eb`.
- Added `--request-key` aliases while retaining `--request-id` for transport handles. Commit `32e069e`.

The project records focused passes including `tests/test_slim_ledger.py` (1), `tests/test_cli_read_routes.py` (3), `tests/test_status_friction.py` (3), and `tests/test_manager_replacement_unit.py` (5). Several owner-backed checks—including `tests/test_owner_manager_replacement.py`, `tests/test_otto_show_status.py`, and parts of the manager journey and admission suites—are explicitly recorded as **gate-only**, not passed locally. The final review says the ledger and docs checks passed and `git diff --check` was clean; I did not rerun tests. [Review record](../otto/projects/slim/.project/PROJECT.md:197)

### Half done

- **One instruction path:** SL1 preserves adopted direction revisions into a replacement brief and removes `advisor_context.py`, but it does not consolidate the full direction/advisor surface. **Inference:** this is a partial move toward the target’s small compulsory instruction core; the target also calls for replay-tested briefs and a live canary. [Tasklist](../otto/projects/slim/.project/tasklist.md:13), [target](../retro/07-first-principles-review.md:57)
- **One replace:** SL2 adds generation fencing and failed-acquisition handling, but its own status says the live owner route is blocked pending PROGRAM/orchestrator wiring. [Tasklist](../otto/projects/slim/.project/tasklist.md:14)
- **One status:** SL3 converges several reads under `show`, but retains `events`; no projection modules were removed because their data and authorization scopes differ. **Inference:** it reduces command duplication, but does not establish one underlying status source. [Tasklist](../otto/projects/slim/.project/PROJECT.md:63)
- **Fewer surfaces:** several dead or misleading entrypoints were removed. However SL6 and SL7’s cold-agent journey and role-guide pass remain blocked, and SL5 explicitly keeps Vision and Native5 until CUTOVER. [Tasklist](../otto/projects/slim/.project/tasklist.md:16-19)

### Canon compatibility and line counts

Current canon has **98 top-level Python modules / 47,813 lines** in `src/otto/portfolio`; slim has **93 / 46,610**. These counts are from the two refs, counting top-level `*.py` files. Slim is therefore 1,203 lines smaller than current canon. Its reported 1,310-line saving uses the older `163925e` baseline, not current canon.

Canon has 132 commits beyond the merge base while slim has 63. Both sides changed five paths since that base: `src/otto/hostctl/cli.py`, `src/otto/portfolio/__init__.py`, `src/otto/portfolio/cli.py`, `tests/test_admit.py`, and `tests/test_manager_journey_service.py`. **Inference:** that is substantial rebase and regression risk. I could not verify textual merge conflicts: the read-only environment rejected `git merge-tree` when it tried to create a temporary file.

The target end state calls for managers to dispatch, checked turn exits, a liveness monitor, receipt-backed status, one launch boundary, one wake-capable message interface, and capable workers—not just fewer portfolio lines. Slim advances instruction, replacement, and status consolidation in part, but does not complete those wider target mechanisms. [Revised end state](../retro/07-first-principles-review.md:41-57)

**Recommendation:** rebase onto current canon, resolve and review the overlapping paths, then finish or explicitly rescope the blocked acceptance criteria. The ledger documents a measured deletion-budget shortfall, so landing as a completed slimming project would overstate what is done.
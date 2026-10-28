# Brief: LANDASSESS (xhard, 1.0 focused days)

**Outcome:** A worker's `done` lands after its check passes and the assessment accepts it.

**Why it matters:** Stage 2's fake worker passes its check, but landing refuses `done` for three separate assessment-binding reasons. Fix the complete path so a dispatched task can finish under the run's acceptance policy.

**Your lab:** `lab/LANDASSESS`, on branch `lab/LANDASSESS`, from `canon/main` at `ccc075affd1dd725765f82d26c49bf19176a2530`. Work only here.

**Layer:** Otto product. Keep assessment policy and landing wiring in existing Otto product modules; use Herzchen's existing content matching where needed.

**Files you own:**
- `src/otto/hostctl/fleet_landing.py` — assessment calls currently use the root owner; use the project view's owner (`view.server.owner`, built in `product_service.py` around 1175).
- `src/otto/hostctl/product_service.py` — project owner/view composition (around 1094, 1175).
- `src/otto/portfolio/manager_assessment_command.py` — required-scope and task-ref comparisons (around 85, 90-96, 117, 122, 291).
- `src/otto/portfolio/owner_bootstrap.py` — project grant boundary (around 1004-1006).
- `ops/bootstrap/perch_fake_claude.py` — failed result events should expose the reply text (`result: str(exc)[:2000]`).
- Tests directly covering these paths; add focused regression tests where needed.

**Other files:** You may edit any additional file directly required by this outcome, except files under Do not touch. List each with its reason in your report. The investigator's throwaway diff is at `/private/tmp/claude-501/-Users-hannahomalley/b7b4b79f-1b09-4eac-81c2-b56066d5593f/scratchpad/st7.diff`; inspect it as evidence, not as a patch to apply blindly.

**Do not touch:** No other tasks are running. Do not touch `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Reuse `task_content_matches` for task-ref binding. Use the project view owner for landing assessment. Derive activation's required scope from the run's policy: `check-accepted` means no review required, `allow_no_review`, protocol `check-accepted`; landing must not declare another scope.

**Your check:** Test activation, admission, dispatch, and `done` acceptance; a task content edit after activation must still refuse; a review-required policy must still require review. Add regression coverage for failed fake-worker result text. Do not run staging-owner tests in the worker sandbox; the landing gate runs them.

**Check command:** `rc=0; for f in tests/test_fleet_custody.py tests/test_act_activation.py tests/test_manager_assessment_ipc.py tests/test_landing.py; do /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$f" || rc=1; done; exit $rc`

**Regression at the level the friction appears:** Under the staging Otto, activate with `check-accepted`, admit and dispatch the canary, then complete `done` after its passing check; assessment accepts it. Changed task content still refuses, and review-required policy still requires review.

**XHARD only:**
- **Invariant:** One policy decides task acceptance, and its binding protects content, not revision ids.
- **Plausible mistake to avoid:** Comparing ids alone at `manager_assessment_command.py:291`, or letting landing add a second scope beside activation.

**Deletion budget:** Reuse the existing content-match and project-view owner mechanisms; do not add a second acceptance policy.

**Working rules:** Follow `ops/brief-template.md` Codex rules verbatim. XHARD: lead and delegate execution to Luna `spawn_agent` sub-agents; review each result against the invariant and report each sub-agent's work. Do not weaken existing assertions. Leave work uncommitted for the launcher; do not push. Run checks to completion.

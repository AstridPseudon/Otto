# Brief: POLICYPIN (xhard, 0.75 focused days)

**Outcome:** The local assessment policy binds project and task by identity and content, so metadata-only revisions after activation remain valid while changed task content still refuses. The tools facade returns the underlying error code and message.

**Why it matters:** Stage 2's fake worker completed, but landing failed because activation pinned an earlier exact project/task revision. Admission and later writes create newer revisions; the facade hid the reason as `owner_unavailable`.

**Your lab:** `lab/POLICYPIN`, on branch `lab/POLICYPIN`, from `canon/main`. Work only here.

**Layer:** Otto product. Keep the policy and facade behavior in the existing Otto product modules.

**Files you own:**
- `src/otto/portfolio/local_assessment_policy.py` — `validate_binding` currently compares exact project/task refs (around line 112).
- `src/otto/hostctl/fleet_landing.py` — converts policy binding failures to `LandingError` (around line 186).
- `src/herzchen/fleet/tools/facade.py` — currently returns only `type(exc).__name__` from the error detail (around line 219).
- `tests/test_fleet_custody.py`
- `tests/test_evidence_status_owner_facade.py`

**Other files:** You may edit other files directly required by this outcome, except those under Do not touch; list each with its reason in your report.

**Do not touch:** No other tasks are running. Do not touch `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Use `LocalAssessmentPolicy.validate_binding` and its existing `reader.get_identity(ResourceRef(authority, kind, id))` lookup. For task content semantics, inspect and reuse `admission.task_content_matches` in `src/otto/hostctl/product_service.py` (around line 369) or the corresponding owner reader use in `src/otto/portfolio/owner_readers.py` (around line 98). Preserve criterion binding checks. The current gate is in `src/otto/hostctl/fleet_landing.py`; the facade is `src/herzchen/fleet/tools/facade.py`.

**Your check:** Cover project/task metadata-only revision acceptance, task content change refusal, and facade error code/message. Run focused tests in `tests/test_fleet_custody.py` and `tests/test_evidence_status_owner_facade.py`, plus any test you add. Do not run staging-owner tests in the worker sandbox; the landing gate runs them.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py tests/test_evidence_status_owner_facade.py`

**Regression at the level the friction appears:** Activation, admission, dispatch, then `done` accepts; editing task content after activation still refuses; facade reports the actual reason.

**XHARD only:**
- **Invariant:** A binding protects content; revisions that change only metadata keep it.
- **Plausible mistake to avoid:** Comparing ids alone, allowing changed task content to bind.

**Deletion budget:** Reuse the existing task-content matching mechanism rather than adding a second policy for task content.

**Working rules:** Follow `ops/brief-template.md` Codex rules verbatim. XHARD: you lead; use Luna `spawn_agent` sub-agents for execution, review each result against the invariant, and report what each did. Do not weaken existing assertions. Leave work uncommitted for the launcher; do not push. Run checks to completion.

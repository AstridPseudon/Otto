# Brief: EVREAD (xhard, 0.75 focused days)

**Outcome:** A manager can approve completion while reading owner-maintained private evidence through the assessment path. Evidence read authority comes from the owner's grant for that evidence; approval remains attributed to the manager, and the manager gains no general owner read authority.

**Why it matters:** Completion review must preserve the boundary between permission to inspect evidence and authority to approve it.

**Your lab:** `labs/EVREAD`, on branch `lab/EVREAD`, from current `canon/main`. Work only here.

**Layer:** Herzchen model. Evidence read authorization is a reusable authority rule; Otto supplies the manager and owner policy identities.

**Files you own:**
- `src/herzchen/domains/assessment/module.py`
- `src/herzchen/content/reads.py`
- `src/otto/portfolio/assessment.py`
- `tests/test_completion_project_refresh.py`
- `tests/test_local_assessment_composition.py`

**Do not touch:**
- other tasks' files;
- `production/`;
- any Store, `~/.otto` or `~/.codex`;
- anything outside this lab.

**Build on what exists:** Preserve the assessment API and content read authorization model. Separate the evidence-read principal/grant from the approver identity; keep the approval record attributed to the manager and ensure the grant is limited to the requested owner-maintained evidence.

**Your check:** Reproduce the affected completion evidence-read failure on canon, then make the focused tests pass without widening manager reads or changing approval attribution:

`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completion_project_refresh.py tests/test_local_assessment_composition.py`

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completion_project_refresh.py tests/test_local_assessment_composition.py`

**Regression at the level the friction appears:** A manager reads one private owner-maintained source through assessment and approves completion as the manager; a direct manager read remains refused.

**XHARD only:**
- invariant: Reading evidence never grants approval authority, and approving never widens read authority.
- plausible mistake to avoid: Run the whole approval as the owner, causing the approval to be recorded as the owner.

**Deletion budget:** Reuse the existing assessment and content read path; replace any coupling that forces evidence reads and approval to share one actor.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Never wait or start a background job you then wait on. Long tests must run to completion using a long timeout. Report any `sandbox_apply: Operation not permitted` test for the landing gate. On Codex, leave changes for the launcher to commit. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report the red and green evidence, the authority boundary preserved, and anything unfinished. Stop and ask if the brief contradicts the code.

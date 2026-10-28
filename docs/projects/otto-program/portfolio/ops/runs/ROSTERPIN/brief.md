# Brief: ROSTERPIN (xhard, 0.5 focused days)

**Outcome:** Adding an unrelated task preserves an otherwise unchanged operating setup. Remove the general task roster from setup-content comparison while retaining exact revisions for adopted content, individual task admission, and setup acceptance-task validation.

**Why it matters:** Activating task A and adding unrelated task D through the real project-sheet path must still let admitted A start, while changed instructions, mandate, acceptance policy, or an unadmitted D cannot inherit authority.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product.

**Files you own:** `src/otto/portfolio/owner_readers.py`, `tests/test_operating_setup_pin_content.py`.

**Other files:** You may also add `tests/test_rosterpin.py` as specified by `${TRANSFER_ROOT}/portfolio/ops/prework/ROSTERPIN.md` and edit any other file directly required by this outcome, except files under Do not touch. Explain each addition in your report.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab. Running tasks own: BOOTLAND (`ops/bootstrap/land.sh`, `ops/bootstrap/otto-lab.sh`, `tests/test_bootstrap_gate.py`); CITECAN (`src/herzchen/domains/work/assignments.py`, `src/otto/portfolio/attention_binding.py`, `src/otto/portfolio/tests/test_operating_setup.py`, `tests/test_manager_journey_command.py`); LABPIN (`src/otto/hostctl/product_service.py`, `src/otto/hostctl/fleet_landing.py`, `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/labs.py`, `tests/test_fleet_custody.py`); FAILEDFENCE landing is still sweeping. EVENTPAGE has exited; its committed lab is waiting to land.

**Build on what exists:** Follow `${TRANSFER_ROOT}/portfolio/ops/prework/ROSTERPIN.md`. Remove the `tasks` field from `_PROJECT_SETUP_FIELDS` and its roster normalization in `src/otto/portfolio/owner_readers.py`; preserve exact historical revision checks for remaining fields. Reuse existing task, mandate, assignment and project content pins in `src/otto/portfolio/operating_brief.py`, plus `ProjectSheet.apply` and batch retention.

**Your check.** First add the real-path regression: activate A, add unrelated D through the project sheet, start admitted A and verify it reaches the provider; verify D stays unadmitted and cannot launch. Add focused refusals for changed A instructions, adopted mandate, and acceptance policy. Keep existing exact `acceptance_tasks` validation and do not change existing test expectations. Run focused tests; the landing gate runs imported callers outside the sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_rosterpin.py tests/test_operating_setup_pin_content.py`

**Regression at the level the friction appears:** Activate A, add unrelated D through the real project-sheet path, and start A through owner execution; A reaches the provider. Changed adopted content and unadmitted D still refuse before another provider call.

**XHARD:**
- Invariant: A roster change cannot weaken the content and authority adopted for an existing task.
- Plausible mistake: Ignoring task or policy changes along with roster membership.
- Surfaces: Planning blocks every launch, or changed work inherits old authorization.

**Deletion budget:** Remove the identity-only roster comparison block and its `tasks` entry. Add no replacement roster mechanism.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Lead the design and review; delegate almost all execution to Luna sub-agents.

**When done:** Leave work for the launcher and report the commit, focused checks, changed files, deletions and any blocker. Stop and report if the brief contradicts canon or the outcome is unclear.

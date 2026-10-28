# Brief: ACTIVATEWHILE (xhard, 0.75 focused days)

**Outcome:** A second project activates while the first project has live or queued work, without changing the first project’s in-flight routing. Read ${TRANSFER_ROOT}/portfolio/ops/prework/ACTIVATEWHILE.md first; report any departure.

**Why it matters:** A busy project currently blocks activation of unrelated projects, contrary to the stage 5 workflow.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto project activation and routing.

**Files you own:** src/otto/hostctl/project_service.py, src/otto/portfolio/project_services.py and directly required owner routing code.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report. Follow the task row and implementation design for scope. The orchestrator allows edge overlaps; the landing gate rebases each lab.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/ACTIVATEWHILE.md` before editing. Explain in your report any place you depart from it.

**Your check:** Add regression coverage at the level described in the design and run the focused files: tests/test_act_activation.py tests/test_bounded_project_host.py. Regressions must fail on canon first; do not weaken existing assertions. Report red and green runs, what you removed, and any blocker.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_bounded_project_host.py`

**XHARD:** Preserve the invariant and avoid the plausible mistake stated in the task row and design. Delete or replace the old mechanism serving the same purpose.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, focused checks, deletions, and additional files changed. Stop and report if the brief contradicts canon or the outcome is unclear.

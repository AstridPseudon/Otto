# Brief: FAILEDFENCE (xhard, 0.75 focused days)

**Outcome:** A manager settles a gone failed worker without replay, clears only its project fence, and allows a different worker. Read ${TRANSFER_ROOT}/portfolio/ops/prework/FAILEDFENCE.md first. It records that TRIAGE decision 1 and the worker-turn value are absent from canon: do not invent them; report the blocker/departure clearly and proceed on independently specified fixes.

**Why it matters:** A failed worker result can keep a project-wide capacity hold forever, preventing later work in that project.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet and Otto capacity recovery.

**Files you own:** src/otto/portfolio/execution_host.py, src/otto/portfolio/worker_custody.py, src/otto/agents/claude_adapter.py and directly required status/command callers.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report. Follow the task row and implementation design for scope. The orchestrator allows edge overlaps; the landing gate rebases each lab.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/FAILEDFENCE.md` before editing. Explain in your report any place you depart from it.

**Your check:** Add regression coverage at the level described in the design and run the focused files: tests/test_capacity_holds.py. Regressions must fail on canon first; do not weaken existing assertions. Report red and green runs, what you removed, and any blocker.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_capacity_holds.py`

**XHARD:** Preserve the invariant and avoid the plausible mistake stated in the task row and design. Delete or replace the old mechanism serving the same purpose.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, focused checks, deletions, and additional files changed. Stop and report if the brief contradicts canon or the outcome is unclear.

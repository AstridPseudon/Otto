# Brief: DRAINSETTLE (xhard, 0.5 focused days)

**Outcome:** Draining answers each queued request that never started exactly once as held, keeps it recoverable after restart, releases admission, and lets close return. Read ${TRANSFER_ROOT}/portfolio/ops/prework/DRAINSETTLE.md first; report any departure.

**Why it matters:** A queued request can wait forever during graceful drain, preventing the owner from closing.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet execution draining.

**Files you own:** src/otto/portfolio/execution_host.py and directly required retained-request recovery code.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report. Follow the task row and implementation design for scope. The orchestrator allows edge overlaps; the landing gate rebases each lab.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/DRAINSETTLE.md` before editing. Explain in your report any place you depart from it.

**Your check:** Add regression coverage at the level described in the design and run the focused files: tests/test_admitted_transport_drain.py tests/test_bounded_project_host.py. Regressions must fail on canon first; do not weaken existing assertions. Report red and green runs, what you removed, and any blocker.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_admitted_transport_drain.py tests/test_bounded_project_host.py`

**XHARD:** Preserve the invariant and avoid the plausible mistake stated in the task row and design. Delete or replace the old mechanism serving the same purpose.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, focused checks, deletions, and additional files changed. Stop and report if the brief contradicts canon or the outcome is unclear.

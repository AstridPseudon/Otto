# Brief: REWORKWIRE (xhard, 1.0 focused days)

**Outcome:** A settled failed or refused landing resumes the same worker session in its kept lab with its refusal log, while unknown effects never resume. Read ${TRANSFER_ROOT}/portfolio/ops/prework/REWORKWIRE.md first; report any departure.

**Why it matters:** A refused landing can strand its worker instead of letting the same worker repair the conflict.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet worker continuation and Otto owner wiring.

**Files you own:** src/herzchen/fleet/hosts/contract.py, src/herzchen/fleet/landing.py, src/herzchen/fleet/tools/facade.py, src/otto/agents/claude_adapter.py and the owner continuation callers required by the design.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additional files in your report. Follow the task row and implementation design for scope. The orchestrator allows edge overlaps; the landing gate rebases each lab.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/REWORKWIRE.md` before editing. Explain in your report any place you depart from it.

**Your check:** Add regression coverage at the level described in the design and run the focused files: tests/test_evidence_status_owner_facade.py tests/test_host_contract.py tests/test_reworkwire.py tests/test_tools.py. Regressions must fail on canon first; do not weaken existing assertions. Report red and green runs, what you removed, and any blocker.

**Check command:** `rc=0; for f in tests/test_evidence_status_owner_facade.py tests/test_host_contract.py tests/test_reworkwire.py tests/test_tools.py; do /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider "$f" || rc=1; done; exit $rc`

**XHARD:** Preserve the invariant and avoid the plausible mistake stated in the task row and design. Delete or replace the old mechanism serving the same purpose.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, focused checks, deletions, and additional files changed. Stop and report if the brief contradicts canon or the outcome is unclear.

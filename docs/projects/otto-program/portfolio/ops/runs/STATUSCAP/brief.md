# Brief: STATUSCAP (normal, 0.25 focused days)

**Outcome:** Status reports the turn limits the policy actually admits.

**Why it matters:** The displayed total must match the policy's combined worker and manager admission ceiling.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product for status wiring; the combined turn ceiling is a shared fleet capacity policy.

**Files you own:** `src/herzchen/fleet/capacity.py`, `src/otto/hostctl/project_service.py`, `tests/test_hostctl_project_service.py`.

**Other files:** Edit only files the outcome directly requires; explain additions in your report.

**Do not touch:** `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or files outside your lab. Keep changes scoped to the status ceiling.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/STATUSCAP.md` first and follow its build order.

**Your check:** Add the default and configured-policy status regression from the design. Demonstrate the default total is 8, with worker and manager limits 6, and configured limits match `admits_turn`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_project_service.py`

**Working rules:** Never stash, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Report canon red and lab green runs, files changed, and blockers. Preserve existing assertions.

# Brief: INVARIANTS (xhard, 1.0 focused days)

**Outcome:** Stage journeys evaluate all six §17.2 invariants from recorded evidence after every step; missing or false evidence fails with the breaking step named.
**Why it matters:** Existing scenario checks can pass by construction and miss defects in the owner evidence.
**Your lab:** Launcher creates this from current `canon/main`; work only there.
**Layer:** Otto proof harness.
**Files you own:** `ops/bootstrap/perch_report.py`, `ops/bootstrap/perch.sh`, `tests/test_perch.py`, and directly required stage-2 tests. REALSTAGE3 has exited; verify current canon and avoid files owned by any worker running now.
**Other files:** Edit any directly required file except Do not touch; explain each in report.
**Do not touch:** Files owned by workers running now: PINALL owns `src/herzchen/fleet/custody.py`, `src/otto/agents/claude_adapter.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/owner_runtime.py`, `src/otto/portfolio/execution.py`, `src/otto/portfolio/execution_host.py`, `tests/test_capacity_holds.py`, `tests/test_capacity_pool.py`, `tests/test_claude_manager_admission.py`; CMDTMPDIR owns `src/herzchen/command_ports.py`, `tests/test_tools.py`; plus `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.
**Build on:** Existing stage-2 evidence and assertions in `ops/bootstrap/perch_report.py` and `ops/bootstrap/perch.sh`; use the observations enumerated in the task row and `PLAN.md` §17.2.
**Your check:** For each invariant, test valid and doctored evidence (including missing evidence). Stage 2 `--fake` must report all six after every step. Do not add one assertion per bug.
**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py`
**XHARD invariant:** An invariant fails when its claim is false or its evidence is missing. Avoid passing when evidence is absent or empty.
**Working rules:** Follow the Codex XHARD rules in the manager brief template; leave changes uncommitted for launcher.

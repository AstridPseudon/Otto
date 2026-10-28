# Brief: GATESKIP (normal, 0.5 focused days)

**Outcome:** The manager journey suite runs in the gate, and a file whose tests only skip does not count as green.

**Why it matters:** The gate must validate product behavior and reject missing test coverage rather than silently accepting it.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Otto product for the manager journey composition; the skip-only gate behavior belongs in the landing gate.

**Files you own:** `ops/bootstrap/otto_gate_exit.py`, `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`, `tests/test_manager_journey_service.py`.

**Other files:** Edit any other file the outcome directly requires. Explain additional files in your report.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or files outside your lab. Avoid unrelated changes to files being edited by SESSIONFD, REWORKWIRE, PINALL, TESTPATCH, and DIAG-STAGE2R1.

**Design:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/GATESKIP.md` first. Follow its implementation order and invariant; report any departure. The product fixture should use the maintained owner composition and a fake model through the adapter seam; do not retain a fixture-based skip.

**Your check:** First prove the skip-only check and skip-only sweep regressions fail on canon, then pass. Run the manager journey suite with `OTTO_OWNER_SERVICE_TEST_FIXTURE` unset and show that its tests execute rather than skip. Keep the existing assertions unless product-backed evidence requires a change; changed assertions require a written D19 decision. Do not weaken coverage to make the sandbox pass.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py tests/test_manager_journey_service.py`

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report commit, red and green checks, deletions, additional files changed, and any blocker. Stop and report if the brief contradicts canon or the outcome is unclear.

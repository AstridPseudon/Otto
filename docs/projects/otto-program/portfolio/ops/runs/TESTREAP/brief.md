# Brief: TESTREAP (normal, 0.25 focused days)

**Outcome:** Tests that start waiter/helper processes always clean them up, including when an assertion fails or the parent test exits. Ensure waiters also exit if their parent disappears. Check `tests/test_runner.py` and other test files that start file-gated helper processes; add regression coverage that deliberately fails and confirms no helper remains.

**Why it matters:** Orphaned helper processes can outlive failed or interrupted tests, accumulating outside the test runner and leaving deleted temporary working directories behind.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen fleet tests; no product implementation change expected.

**Files you own:** `tests/test_runner.py`.

**Other files:** You may edit another test file only if the same file-gated waiter pattern exists there and the regression needs to cover it. Explain each extra file in your report.

**Do not touch:** `src/otto/portfolio/execution.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/manager_journey_client.py` (FAILEDFENCE landing in progress); `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab.

**Build on what exists:** Reuse the `harness` fixture and the existing file-gated helper scripts in `tests/test_runner.py`; keep the process cleanup tied to test teardown and verify child processes are gone by pid.

**Your check:** Add a regression that causes a test-side failure after spawning the harness waiters, then confirms teardown leaves none alive. Run the complete runner test file twice in separate processes. Do not weaken existing assertions.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_runner.py`

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, both focused check runs, and whether any other helper-process tests needed changes.

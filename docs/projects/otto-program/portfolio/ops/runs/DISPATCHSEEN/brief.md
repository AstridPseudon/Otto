# Brief: DISPATCHSEEN (normal, 0.5 focused days)

**Outcome:** Make an early child exit or broken pipe visible in the launch outcome, owner log, and `project status`. Preserve `unknown` as unknown and include the child's exit status and stderr tail as its reason. A launched task must project as launched.

**Why it matters:** An admitted task that never launches looks active forever and can hide a launch failure. The operator needs enough evidence to diagnose it without turning an uncertain launch into a retryable failure.

**Your lab:** `lab/DISPATCHSEEN`, on branch `lab/DISPATCHSEEN`, from `canon/main`. Work only here.

**Layer:** Otto product. Keep launch reporting and status projection in Otto's product wiring.

**Files you own:** The relevant launch path in `src/otto/agents/claude_adapter.py` and `src/otto/agents/claude_cli.py`, automatic dispatch outcome/logging, and the `project status` projection. Add or update focused regression tests for each outcome.

**Other files:** You may also edit any other file the outcome directly requires, except files under “Do not touch”; list each in your report with the reason. Do not stop to ask for a file.

**Do not touch:**
- Files owned by any tasks running now.
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** Follow the launch and status paths named in the task row: `src/otto/agents/claude_adapter.py` around 489–493, `src/otto/agents/claude_cli.py` around 354, automatic dispatch failure recording, and the `project status` projection. Verify current line numbers in canon before editing.

**Your check:** Add focused coverage for a child that exits before reading stdin, a successfully launched task, and the `unknown` status projection with its reason. Show regression tests failing on `canon/main` and passing in the lab. Run only the test files you changed or added.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_claude_manager_admission.py`

**On Codex:** You can't commit; leave work in the lab for `run-task.sh` to commit. Long test runs must run to completion with a long timeout. A test failing with `sandbox_apply: Operation not permitted` needs a sandbox of its own; list it in your report for the landing gate. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

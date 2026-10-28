# Resume LABPIN (xhard): D19 restore

Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-LABPIN.md.sendback` and implement its entire Restore section in the LABPIN lab. Replace the five ten-second waits with unconditional `b_landed.wait()`, `start_writer.wait()`, `thread.join()`, `acquired.wait()`, and `thread.join()` respectively. Remove the timeout failure branch, deadline assertion, and now-redundant post-join liveness assertions. Preserve `release.set()` in `finally`, worker-error checks, and every occurrence, custody, HEAD, content, recovery, dirty-work, and retained-ref assertion.

The original brief and check command still govern. Run the brief's full check to completion, then `git diff --check`; report changed files and results. Leave changes for the launcher to commit. Do not touch files in other task labs, especially the running LANDBATCH lab.


**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

# Resume RECEIPTFENCE: resolve the round-2 rebase and D19 restore

Resolve the rebase conflicts in the RECEIPTFENCE lab. Follow `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-RECEIPTFENCE.md.sendback`'s Restore exactly: preserve canon's bounded-host assertions unchanged; replace only the manager test's `:143` absence assertion with checks for `dispatch_claimed=True`, `request_state="processing"`, `terminal=False`, the exact request ID and response path, and `retry=False`; retain the other protections. Do not publish `unknown` for the bounded-host case. Prepare the concrete assertion diff and its D19 inventory; a fresh Astra D19 is needed after the corrected worker report.

The original brief and focused check still govern. Keep changes within the task's receipt path and focused tests; preserve the Herzchen/Otto boundary. Run the focused check and `git diff --check`, then report changed files/results. Work only in the RECEIPTFENCE lab; do not edit other task labs. Leave changes for the launcher to commit.

**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/<TASK>` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.

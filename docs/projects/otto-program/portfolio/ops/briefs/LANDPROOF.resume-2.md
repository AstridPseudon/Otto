# Resume LANDPROOF: resolve the round-2 rebase and D19 restore

Resolve the rebase conflicts in the LANDPROOF lab, then implement every item in `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-LANDPROOF.md.sendback`'s Restore section. In `test_done_refuses_failed_mismatched_or_unresolvable_check_evidence`, retain `pytest.raises(LandingError)` and, inside the fixture context afterward, restore both assertions for every parameter: the task line's main ref still equals `case.base`, and `AssessmentModule(case.f.store, actor=case.f.actor).list_decisions(parent_obligation=case.task_ref)` is empty. Keep the production proof writer unpatched in the test; preserve the task outcome and all existing protections.

The original brief and required check still govern. Run the full check to completion and `git diff --check`, then report changed files/results. Work only in the LANDPROOF lab; do not edit other task labs. Leave changes for the launcher to commit.

**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/<TASK>` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.

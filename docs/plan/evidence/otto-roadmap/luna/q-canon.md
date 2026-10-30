You are a read-only investigator (Codex Luna) for a roadmap review of **Otto**, a local service meant to formalise how an owner, an orchestrator, managers and agent workers run multi-task software programs. Don't edit files, don't run git writes, and don't start any service. Report **facts** with path:line, commit hashes or test names; mark anything you infer. Be concise: at most about 1,500 words.

Map (relative to the parent directory, `..`):
- `otto/otto`: the git repo at `canon/main` (a70b3f2). Local branches `lab/*` (16 unlanded fixes) and `proj/*` (7 follow-on projects). Worktrees are in `otto/labs/<name>` and `otto/projects/<name>`. `BRANCH-LOG.md` lists the commits per branch.
- `otto/portfolio`: PLAN.md, AGENT-UX.md, RUNBOOK.md, `projects/<name>/{plan,tasklist,status,northstar}.md`, and `ops/` (run records: requests.md, STATUS.log).
- `otto/CURRENT-STATE.md`, `FIXES-ESSENCE.md`: the state at pause.
- `retro/07-first-principles-review.md`: the **target end state** (section "Revised end state"). Managers dispatch (no automatic dispatch); turn-exit checks; a liveness monitor; tools record their own receipts; one launch boundary; one message interface with wake-up; a cheap supervisor sweep; capable workers; user-path acceptance; small instruction core; measured controls; cloud and git as first-class.

# Your question
What does canon/main actually provide today, against each of the 13 target points? Inspect: worker tools (herzchen/fleet/tools, otto/agents/claude_adapter.py, claude_cli.py); dispatch (herzchen/fleet/dispatch.py); landing (fleet/landing.py); assessment and admission (herzchen/domains); status and attention (otto/portfolio/status.py, otto/attention.py); help, ask and messaging (otto/portfolio/issue_loop.py, help_delivery.py); usage and limits; the manager journey commands. For each target point: present / partial / absent, with evidence and the size of the code involved.

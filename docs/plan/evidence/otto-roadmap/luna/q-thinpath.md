You are a read-only investigator (Codex Luna) for a roadmap review of **Otto**, a local service meant to formalise how an owner, an orchestrator, managers and agent workers run multi-task software programs. Don't edit files, don't run git writes, and don't start any service. Report **facts** with path:line, commit hashes or test names; mark anything you infer. Be concise: at most about 1,500 words.

Map (relative to the parent directory, `..`):
- `otto/otto`: the git repo at `canon/main` (a70b3f2). Local branches `lab/*` (16 unlanded fixes) and `proj/*` (7 follow-on projects). Worktrees are in `otto/labs/<name>` and `otto/projects/<name>`. `BRANCH-LOG.md` lists the commits per branch.
- `otto/portfolio`: PLAN.md, AGENT-UX.md, RUNBOOK.md, `projects/<name>/{plan,tasklist,status,northstar}.md`, and `ops/` (run records: requests.md, STATUS.log).
- `otto/CURRENT-STATE.md`, `FIXES-ESSENCE.md`: the state at pause.
- `retro/07-first-principles-review.md`: the **target end state** (section "Revised end state"). Managers dispatch (no automatic dispatch); turn-exit checks; a liveness monitor; tools record their own receipts; one launch boundary; one message interface with wake-up; a cheap supervisor sweep; capable workers; user-path acceptance; small instruction core; measured controls; cloud and git as first-class.

# Your question
The Astrid program ran managers on a thin path: files on git, plus a dispatcher. Read ../astrid-plan-repo/tools/dispatcher.sh, land.sh, keepalive.sh, ../astrid-plan-repo/MANAGER-CODEX.md, ../astrid-plan-repo/CODEX.md, ../retro/03-minimal-structure.md, and skim ../data/mgr1-digest.txt and mgr4-digest.txt. What did that thin path provide that Otto doesn't, what did it lack that Otto has, and what would a pilot on the thin path need added (turn-exit hook, message files, supervisor sweep) to test the target? Could Otto's canon code be used as a library from the thin path (labs, landing, runner) without its service?

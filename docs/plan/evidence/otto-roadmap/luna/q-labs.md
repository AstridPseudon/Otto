You are a read-only investigator (Codex Luna) for a roadmap review of **Otto**, a local service meant to formalise how an owner, an orchestrator, managers and agent workers run multi-task software programs. Don't edit files, don't run git writes, and don't start any service. Report **facts** with path:line, commit hashes or test names; mark anything you infer. Be concise: at most about 1,500 words.

Map (relative to the parent directory, `..`):
- `otto/otto`: the git repo at `canon/main` (a70b3f2). Local branches `lab/*` (16 unlanded fixes) and `proj/*` (7 follow-on projects). Worktrees are in `otto/labs/<name>` and `otto/projects/<name>`. `BRANCH-LOG.md` lists the commits per branch.
- `otto/portfolio`: PLAN.md, AGENT-UX.md, RUNBOOK.md, `projects/<name>/{plan,tasklist,status,northstar}.md`, and `ops/` (run records: requests.md, STATUS.log).
- `otto/CURRENT-STATE.md`, `FIXES-ESSENCE.md`: the state at pause.
- `retro/07-first-principles-review.md`: the **target end state** (section "Revised end state"). Managers dispatch (no automatic dispatch); turn-exit checks; a liveness monitor; tools record their own receipts; one launch boundary; one message interface with wake-up; a cheap supervisor sweep; capable workers; user-path acceptance; small instruction core; measured controls; cloud and git as first-class.

# Your question
For each of the 16 lab branches (lab/BOOTCFG, BOOTLAND, CLIARGS, DISTURB, INTEG-PROCLIFE-PL3, LABPIN, LANDBATCH, LANDPROOF, OBSOWNER, PROOFDOC, REALSTAGE3, ROLEIDS, ROOTFILE, STAGE2CLIENT, TESTPATCH, XFERMAP): what does it change (git diff a70b3f2...lab/X --stat plus key hunks), what problem does it fix (portfolio/ops/requests.md and integ/ notes), what's its state (culprit or regression notes), and does it serve the target? Give one row per branch: change | fixes | state | verdict (land / rewrite / drop) | reason.

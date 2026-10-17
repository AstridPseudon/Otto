# Manager brief: PROCLIFE — Otto process scopes

Run the refreshed tasklist in dependency order, one worktree per task, at most two workers at once. Require a failing-first regression for each implementation. Review each diff, run its focused checks, and ask Astra to review every xhard diff. Preserve the existing process-owner boundaries and do not weaken tests.

The current run is blocked at PL1 by D19: an Opus decision is required before changing the existing `setsid` escapee test's expectation. Keep that test unchanged until the orchestrator decides. Record sandbox-exec, ps, Unix-socket, and staging-dependent checks as `needs the gate`; do not start an Otto owner or staging run here. See `.project/PROJECT.md` for the decision, review, and worktree inventory.

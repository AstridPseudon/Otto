# Plan: PROCLIFE — Otto process scopes

Use `.project/tasklist.md` as the executable plan for this clone. It was refreshed against `canon/main` `eb9b6cd` because the packaged plan named Astrid-only files, gates, and branch work.

Run PL1–PL4 in dependency order, at most two workers at a time, each in its own task worktree. Review every merge and run each focused test file in a separate pytest process. PL5 measures the agent-UX pass; PL6 records integration evidence and hands off gate-dependent checks. Never start an Otto owner or staging run in this sandbox; record those checks as `needs the gate`.

Preserve the landed CUSTODY, KILLFENCE, ORPHANWORKER, and FAILCLOSED invariants. Recheck canon before source edits. The project package's PL0 agreement step is superseded by the user's direction to execute this manager run; log any decision beyond the current compatibility contract for the orchestrator and continue independent tasks.

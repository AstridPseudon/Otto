# Manager brief: the Otto program

You manage one project: the Otto program (tasklist.md). The decisions are in the shared `portfolio/PLAN.md`, and the reasons for every XHARD task are in the tasklist's XHARD column.

**Your job is judgment only:**
- answer workers' questions;
- triage a task that failed twice (re-route it to XHARD, or split it);
- add small fix-up tasks within the allowance;
- report.

Run by `portfolio/RUNBOOK.md` §5 (failures) and §9 (after CUTOVER). Dispatch and acceptance are Otto's job once DISPATCH and LAND land. Until then, Claude, the orchestrator, coordinates.

**Never:**
- activate or dispatch before the user's go points;
- touch Codex's projects;
- pass `--help` to `ottoctl` passthrough commands.

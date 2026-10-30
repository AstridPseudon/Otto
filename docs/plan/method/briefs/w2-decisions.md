# Your task: lens "Rulings and decision-making"
Find every decision the orchestrator made on a manager's escalation or its own initiative (rulings such as "build the route, it is in scope", "pin stays put", "main decides", "stop patching piecemeal", accept/reject review findings, scope cuts, splitting/merging tasks), and every decision the owner made. For each: the question, options considered, the decision, the reasoning style (principle invoked), time to decide, and whether it held or was reversed later. Identify recurring decision heuristics (e.g. smallest scope that closes the class; defer to owner only for X). Also: which decisions should have gone to the owner but didn't, or vice versa. Output a decision-heuristics list usable by a future orchestrator.
## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.

# Your task: lens "Model tiering, difficulty and cost"
Reconstruct how model choice evolved: the owner's tier rubric (Normal/Hard/Super-hard; Luna/Terra/Sol; Haiku/Sonnet/Opus), escalation rules ("haiku xhigh then sonnet after one failure"), Opus restrictions, Codex vs Claude. Find mis-assignments and their consequences, how difficulty was judged, and the cost data (`/home/user/repo/astrid-install/COST-LOG.md`, cost mentions). Propose a concrete, simple difficulty-scoring rubric (inputs a task list could carry) grounded in which tasks actually turned out hard (FIX rounds, escalations, reviews).

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


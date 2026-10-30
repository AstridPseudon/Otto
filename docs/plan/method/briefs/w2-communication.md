# Your task: lens "Communication with the owner and deliverables"
How did the orchestrator communicate: status answers, digests, zips/packs, paste-ready messages for other managers, AskUserQuestion usage, escalations, "owner asleep" autonomy, decision lists for the owner. What did the owner ask for repeatedly ("where are we", "what is open", "what does this require from me")? What formats landed well vs needed rework? Derive a communication protocol: what to report, when, in what shape, and which decisions must go to the owner vs be made autonomously.

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


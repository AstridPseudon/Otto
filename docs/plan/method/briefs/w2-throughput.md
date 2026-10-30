# Your task: lens "Throughput, timing and idle time"
Use timestamps in the transcripts, the plan-repo git log (`data/plan-repo-gitlog.txt`, commit times), queue files and the cost log to reconstruct: tasks landed per hour per phase, gaps where nothing progressed (and why: manager idle, waiting on owner, waiting on long tests, blocked by permissions, context exhaustion/handoff), time from owner instruction to effect, the critical path of the program, and where parallelism was used or missed. Quantify the biggest time sinks. Derive cadence and parallelism rules (e.g. how many workers, when to check in faster, when a stall is real).
## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.

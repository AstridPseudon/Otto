# Your task: lens "Other programs and earlier process attempts"
Source: `data/other-branches-process-docs.txt` (process documents from other branches of the plan repo: handoff guides, manager/orchestrator briefs, plans from earlier or parallel programs, e.g. a timeline refactor program with child managers, a handoff guide), plus mentions of other sessions in the transcripts. Compare those processes with this program: what was the same, what differed, what each learned. Identify practices that recur across programs (strong signal of a stable primitive) and ones unique to one program.
## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.

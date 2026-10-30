# Your task: lens "Worker briefs and task runs"
**Do only this lens. Ignore the `briefs/` folder and any other task descriptions you find in the workspace; they belong to other analysts.**
Primary source: the task run folders under `/home/user/repo/astrid-install/runs/<task-id>/` (index with sizes in `data/run-folders-index.txt`; each usually has brief.md, final.md, maybe dispatch.json, review files, -F fix and -review folders). Sample widely (at least 25 folders across UPD, COH, GATE, INS, ASTRA, REBASE, review and -F folders) and read brief.md and final.md. Analyse: brief length and structure, what a good brief contained (Done when, scope, tests, file pointers), how often tasks needed re-dispatch or FIX rounds (look for -F, -review-2, ruling folders), which brief features correlate with first-time success vs rework, how workers reported (final.md shape), and how reviews were briefed. Derive a worker brief template and a result template that are as short as possible.
## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.

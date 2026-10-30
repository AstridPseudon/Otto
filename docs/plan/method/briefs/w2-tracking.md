# Your task: lens "Tracking, logging and records"
Inventory every tracking/logging artifact used (QUEUE.md task tables with status columns, STATUS.md, COST-LOG, DIGEST, evidence/, runs/<task>/ folders with brief.md/final.md/dispatch.json/land.request etc., ESCALATE/READY/APPROVED marker files, REBASE-COMPLETE markers, snapshots/MANIFEST, release notes, bigger-issues lists, pre-existing failure lists, commit message conventions). For each: purpose, who wrote/read it, did it work, was it stale or duplicated. Look at the plan repo directly. Propose the minimal set of records a platform needs and their schema (fields).

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


# Your task: lens "Tooling, environment and friction"
Catalogue infrastructure and friction: dispatcher.sh file protocol (worktree.request, dispatch.json, land.request, ci.request), Codex vs Claude workers, sandbox limits, permission/classifier denials (data exfiltration, self-modification) and how they were handled, auth/secret issues, context compaction and session restarts, lost work (e.g. patches lost when a folder was removed), stale snapshots, private/public repo issues, keepalive scripts, scheduled triggers. For each: impact (time/cost), root cause, fix or workaround. Derive what a platform must provide natively so none of this is hand-built.

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


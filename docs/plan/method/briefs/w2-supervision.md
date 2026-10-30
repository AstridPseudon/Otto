# Your task: lens "Manager supervision and cadence"
How did the orchestrator supervise managers? Check-in cadence (hourly triggers, 15-minute loops, send_later self check-ups that were removed), what each check-in examined (get_session, list_events, snapshots, queues), interventions sent (send_message) and their effect, idle/stall detection, manager handoffs/replacements (why managers were replaced, context exhaustion, cold-start briefs, HANDOFF.md), snapshot/export/import mechanics. Use `data/managers/*.json` for the manager side. Derive: the standard check-in question list, intervention triggers ("intervene when…"), and a handoff protocol.

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


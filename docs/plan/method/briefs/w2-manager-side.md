# Your task: lens "The manager's perspective"
**Do only this task. Ignore the `briefs/` folder and any other task descriptions in the workspace; they belong to other analysts.**
Primary source: the four manager ledgers `out/w1-mgr1.md` … `out/w1-mgr4.md` (verify in `data/mgrN-digest.txt`, readable transcripts oldest-first) plus the briefs `/home/user/repo/handoff-upd/BRIEF-claude-manager.md`, `/home/user/repo/astrid-install/MANAGER.md`, `MANAGER-CODEX.md`, `CODEX.md`. If the manager files are missing, say so and use the orchestrator transcript's view of managers instead. How did managers interpret their briefs, where did they get confused or stall, what did they do between tasks, how did they brief workers, review results, land work, and report? Which brief instructions demonstrably changed behaviour? What did managers need but not have?

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


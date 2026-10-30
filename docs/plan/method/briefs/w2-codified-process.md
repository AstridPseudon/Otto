# Your task: lens "The process as written vs as practised"
Read the codified process documents in full: `/home/user/repo/astrid-install/{ORCHESTRATOR.md,MANAGER.md,MANAGER-CODEX.md,CODEX.md,PROGRAM.md,GOAL.md,README.md}`, `/home/user/repo/handoff-upd/{BRIEF-claude-manager.md,ENVIRONMENT.md}`, and the skill draft `plans/drafts/astrid-deploy-SKILL.md`. Also check `git log -p --follow` is NOT available to you; use `data/plan-repo-gitlog.txt` to see how these files evolved. Summarise the operating model these documents define (roles, loops, files, rules), then compare to what actually happened in the transcripts: which rules were followed, ignored, changed, or never needed. Identify the stable core (rules that survived all revisions).

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


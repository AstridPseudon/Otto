# Your task: lens "Project setup and exploration"
How were projects started, scoped and planned? Trace: how a project went from idea → exploration (probes, sub-agent investigations, codebase best-practice discovery, feasibility checks with other tools) → plan document → review/sense-check (Opus, Codex/Astra, over-engineering reviews) → task queue with tiers → manager deployment. Which questions were asked of a new project? What did plans contain (end state, contracts, tasks, "Done when", decisions, risks)? What made a plan good or bad (later rework, owner pushback)? Identify the reusable "project kickoff" sequence and checklist.

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


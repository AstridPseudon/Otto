# Your task: lens "Failure modes and anti-patterns (red team)"
Be skeptical. Find the biggest wastes of time, money and owner attention, and repeated mistakes. Examples to check: orchestrator doing work itself, Opus used for implementation, managers idling between turns, 70-minute full test runs to bisect, wrong classification rules, unbounded review loops, stale snapshots, over-specified plans later cut by over-engineering review, process docs growing. Quantify where possible. For each: symptom, root cause, earliest detectable signal, the rule that would have prevented it. Also: which "rules" added overhead without payoff?

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


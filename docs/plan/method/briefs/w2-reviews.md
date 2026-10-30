# Your task: lens "Reviews, second opinions and simplification"
Find every review / second opinion / over-engineering check / elegance pass / coherence review / Astra or Opus or Codex sense-check. For each: who reviewed, what input, what came out (blocking counts, simplifications), what was accepted or rejected and why, and the cost/time. Analyse review loops (rounds, FIX cycles, bounded loops), when reviews added value vs churn, the "over-engineering" vs "robust" framing, and how the orchestrator applied its own judgement on top. Derive rules: when to review, with which model, how many rounds, what to ask.

## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.


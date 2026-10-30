# Your task: lens "Autonomy while the owner was away"
The owner went to sleep at least once with "No more questions… You have to figure out everything" (around [10-28 02:08]) and at other times was absent for hours. Reconstruct what happened during unattended periods: decisions made, work done, problems hit, how they were handled, and what the owner said on return (digest reception, corrections). Compare quality of unattended vs attended periods. Derive rules for unattended operation: what may be decided autonomously, what must wait, what to log for the owner, the shape of the morning digest, and safety limits (pushes, deploys, secrets, spend).
## Inputs
- Chronological ledgers from wave 1: `out/w1-chunk-1.md` … `out/w1-chunk-8.md` (read all).
- Raw sources to verify and deepen (search them with grep/rg; read the relevant parts): `data/main-full.txt` (whole orchestrator transcript), `data/user-messages.txt` (every owner message), `data/subagents.txt`, `data/plan-repo-gitlog.txt`, `data/managers/*.json` (manager transcripts as JSON pages, if present), and the plan repo at `/home/user/repo/astrid-install/` and `/home/user/repo/handoff-upd/`.
Verify ledger claims against raw sources before relying on them; ledgers can be wrong.

## Output
`## Lens: <name>` then: **Findings** (numbered, each with evidence), **What worked**, **What failed / friction**, **Candidate principles** (each phrased as a rule: "When X, do Y, because Z (evidence)"), and **Structure implications** (what a platform/process would need to make this automatic: an entity, a file, a field, a cadence, a trigger, a checklist question). Max ~3,000 words.

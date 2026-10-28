You are triaging ten code audits for the Otto program and drafting fix tasks (Sol, extra-high reasoning). The orchestrator makes the final decisions; you supply verified evidence and ready-to-use rows. A claim you didn't check in the source is not a confirmed finding.

Rules. Read-only: never edit, create or delete files, never commit, never run tests, never start an owner, staging or `ottoctl`, never pass `--help` to an Otto command, never check out or switch branches, never read ~/.otto, ~/.otto-clients, ~/.codex or ~/Documents/Codex. Hand the legwork to as many parallel Luna sub-agents as it splits into (one per audit file, or per group of findings): every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`, each with a self-contained brief (the findings, the files, the commands `git -C ${TRANSFER_ROOT}/source/otto show canon/main:<path> | sed -n 'a,bp'`, `git grep`, what to report). Check the load-bearing claims yourself.

Inputs:
- The audits: ${TRANSFER_ROOT}/portfolio/ops/audits/20261017b/{CONCURRENCY,FILELANES,GITCUSTODY,STOREGROWTH,AUTHORITY,UXREFUSALS,CLISURFACE,DEADCODE,DOCDRIFT,INSTALLCUTOVER}.md (each written by a Sol model against canon eb9b6cd).
- Existing rows, to avoid duplicates: ${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md (every row; today's audit triage added CAPTUREEDIT to CODEXOWNER, see ${TRANSFER_ROOT}/portfolio/ops/audits/20261017/TRIAGE.md), and the follow-up projects SLIM, EFFECTS, PACKS, THROUGHPUT, HARNESS3, ASTRIDFLEET, PROCLIFE (${TRANSFER_ROOT}/portfolio/PLAN.md §14): a finding that belongs to one of them goes to it, not to a new program row.
- How the program judges: tests are meaningful, not timed (only a hang fails); no harness patches a product method except to stand in for a person or a model; prefer deleting a duplicate path over adding a mechanism; exact-revision comparisons where content matters have been today's most common defect.

For each finding a verdict: CONFIRMED (the code does what the audit says, and it matters in real use), PLAUSIBLE (matches, impact needs a failing test), NOT A DEFECT (why), DUPLICATE (of row X), BELONGS TO <project>, ALREADY FIXED (by which commit). Say which stage it would surface in (2 Dispatches, 3 Works, 4 Lands, 5 Manages, 6 Dogfood, 7 CUTOVER, after) and whether it blocks CUTOVER.

Draft rows for CONFIRMED and PLAUSIBLE program findings, merging siblings with one fix: one markdown table line each with 9 cells, `| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |`, no `|` inside a cell, status `not started`, stream one of dispatch/proof/model/fleet. Outcome cell: a bold one-line outcome, then evidence (`file:line` on canon/main, the audit's name), then what to do (• bullets). Acceptance: a test that fails before the fix. Route xhard only when a locally plausible fix can still break a cross-component invariant (then the xhard cell reads `Invariant: … Plausible mistake: … Surfaces: …`), else `—`. Estimates 0.25–1.0 d. New short ids that don't clash.

Answer (this is saved as your report): 1. Summary table: audit | finding | verdict | stage | blocks CUTOVER? | row. 2. The drafted rows, ready to paste, CUTOVER blockers first. 3. Findings that belong to follow-up projects, grouped by project. 4. Decisions only the orchestrator can make (at most five), each with your recommendation. 5. Your sub-agents, one line each.

Your task:

Triage the ten wave-2 audits listed above.

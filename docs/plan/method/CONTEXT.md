# Shared context for retrospective workers (read first)

You are helping run a **retrospective** on a multi-agent software program that ran 26–28 Oct 2026. The owner (a human; call them "the owner", pronoun they/them) wants to understand **what worked and what didn't** in how the work was organised, so they can design a simple platform/process for running "orchestrator → managers → workers" programs in future. You are a read-only analyst: read the data files, write findings. Never run commands that change anything.

## Cast
- **Owner:** the human. Gives direction, corrections, preferences, approvals. Sometimes asleep ("figure it out yourself").
- **Orchestrator:** a Claude Code session (the transcript in `data/main-*.txt`, "ASSISTANT" lines). Role evolved into "guide and tastemaker": plans, equips, checks managers hourly, decides escalations; supposed to NOT do product work itself.
- **Managers:** separate Claude Code sessions (mostly Haiku model) that the orchestrator created to run a task queue; they dispatch **workers** (Claude sub-agents or Codex CLI workers: gpt-6-luna = cheap/normal, gpt-6.1-terra = hard, gpt-6.1-sol = super-hard, gpt-6-astra = reviewer) and land their results. Manager transcripts (if present) are in `data/managers/`.
- **Sub-agents:** short-lived helpers the orchestrator spawned (`data/subagents.txt`: prompt + final answer each).
- **Plan repo:** git repo holding plans, briefs, queues, cost log, evidence; its commit history is `data/plan-repo-gitlog.txt`. Live files are under `/home/user/repo/astrid-install/` (e.g. ORCHESTRATOR.md, MANAGER.md, MANAGER-CODEX.md, CODEX.md, PROGRAM.md, STATUS.md, COST-LOG.md, plans/, runs/QUEUE.md, runs/<task-id>/{brief.md,final.md}, tools/dispatcher.sh) and `/home/user/repo/handoff-upd/`.

## Projects mentioned
UPD (updater), REBASE (rebase UPD onto latest main), GATE/COH/INS (release safety, coherence, installer; paused), TST (cross-platform testing plan), FIX-W* (Windows tester findings), proof runs, CI on GitHub Actions.

## Transcript format
`[MM-DD HH:MM] USER:` = owner message (or a scheduled trigger / notification). `ASSISTANT:` = orchestrator text. `TOOL name (description): input` = an action. `result` / `RESULT-ERR` = truncated tool output. `=== COMPACTION SUMMARY ===` = the orchestrator's own summary when its context was compacted (good overview, but may be biased).

## Rules for your output
- Evidence-first: every claim cites a timestamp `[MM-DD HH:MM]` and/or file, with a short verbatim quote where useful (≤25 words).
- Distinguish **observed** (in the data) from **inferred** (your interpretation). Mark inferences.
- No flattery, no generic advice. Specific > general. If the data doesn't show something, say so.
- Markdown, concise, bullets/tables. Max ~2,500 words unless told otherwise.

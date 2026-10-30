# Project: attach

**Goal.** Let any existing chat window (Claude Code, Codex, an omp window) take a seat in the organisation (advisor, orchestrator, manager or worker), work through the ordinary CLI, and hand the seat back.

**How it runs.** **This is the v1 pilot** (plan D5). It's the first project the tool builds on itself, once the four v1 projects have qualified:
```
otto project new attach --pack megado --from docs/plan/projects/attach
```
- The orchestrator assigns a manager.
- The manager plans from `SPEC.md` and `TASKS.md`, and dispatches workers.
- The workers build in worktrees of the tool's own repo.
- The running tool stays on its installed, pinned version until this project lands and is released.

**What v1 already provides:**
- the `agents.host` column;
- identity lookup: `--as` beats `OTTO_AGENT`, which beats `.otto/agent`;
- the one-holder-per-seat rule.

The full design is in `../../13-spec.md` A4 under "Attach". This project's success is milestone 2 (`../../START-HERE.md`).

**Done when:**
- every task's check passes;
- the acceptance below is green in the tool's CI;
- the feature has been used for real at least once: the candidate build is installed side by side, in a **separate test organisation** (its own `OTTO_HOME` and database), and a Claude Code window is attached as a manager for a small project there, then detached. Production switches only at release (`../../DECISIONS.md` O6).

**Acceptance:**
1. Attaching to a seat held by `otto run` stops that holder first. There is never more than one holder.
2. Taking a seat from another outside session needs `--force`; a stale binding is refused.
3. The attached session receives the handover packet: role guide, skills, mandate, current work and inbox instructions.
4. CLI commands from that working folder act as the attached agent.
5. Messages and reminders wait in its inbox. The idle-manager check skips it.
6. `otto detach` starts a fresh supervised session for the seat, with a handover note.

**Out of scope:**
- attaching sub-agents;
- pushing into an outside session;
- multi-machine attach.

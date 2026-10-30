You are a read-only investigator (Codex Luna). Don't edit files, don't run git writes, and don't start services. Report facts with path:line; mark inferences. At most about 1,800 words.

**Context.** The owner wants a minimal tool for running multi-agent software work:
- four roles (orchestrator, manager, worker, sub-agent) and one spawn path (via the Pi coding-agent harness);
- packs, with Megado first, holding the role instructions and skills;
- projects as a spec folder of documents, synced to SQLite with **check-out / check-in**, turned into a task list;
- six tables (projects, tasks, agents, messages, schedules, events) in one SQLite file, optionally synced to Turso;
- one CLI;
- the only enforcement is the hierarchy, a turn-end check, and scheduled orchestrator reminders.

The design is in `../retro/12-minimal-design.md`. The existing code is Otto: `../otto/otto/src` (canon `a70b3f2`), with the project branches under `../otto/projects/<name>/src`. The Astrid thin path is `../astrid-plan-repo/tools`.

# Your question
For each part of the minimal design (the six tables; `otto spawn` with instruction composition; messages with wake-up by resuming a session; schedules and reminders; the turn-end check; the status digest; the task list derived from the spec), find the **closest existing code in Otto canon** (e.g. herzchen/domains/work for tasks, portfolio/issue_loop.py and help_delivery.py for messages, attention.py DueRecord for schedules, portfolio/status.py for status, agents/claude_adapter.py and fleet/hosts/{claude,codex}.py for launch and resume, kernel/store.py for SQLite). For each: what it does, its size, how entangled it is (with the owner service, the authority layer, Herzchen kernel types), and a verdict: **reuse as code / port the semantics / ignore**. Also check whether the Otto kernel SQLite schema (kernel/store.py) is usable directly, or whether a fresh six-table schema is simpler. Give the total reusable lines.

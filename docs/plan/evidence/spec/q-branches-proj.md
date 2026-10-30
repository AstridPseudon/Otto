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
Index the 7 **project branches** for pieces that are **already built and tested** and serve the minimal design. Worktrees: ../otto/projects/{packs,slim,effects,proclife,throughput,harness3,astridfleet}; commits per branch are in ../BRANCH-LOG.md; each has .project/ records (PROJECT.md, tasklist.md). For each branch, list the concrete pieces (files, functions, tests) that map to a minimal-design component: packs and role instructions; spec-folder sync; tasks; messages and wake-up; schedules; turn-end checks; status; spawn and resume through a harness; landing and integration. For each piece: does it have passing-test evidence (cite test names and any recorded results in .project/)? How entangled is it with the owner service or the authority layer? Verdict: lift / adapt / ignore. End with a ranked shortlist of the 10 most valuable tested pieces for the minimal design.

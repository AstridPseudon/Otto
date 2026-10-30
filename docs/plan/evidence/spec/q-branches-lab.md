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
Index the 16 **lab branches** (../otto/labs/*; commits in ../BRANCH-LOG.md) and **canon tests** (../otto/otto/tests, ../otto/otto/src/otto/portfolio/tests) for **tested building blocks** the minimal design can reuse or use as specs: task readiness and dependencies; landing order (rebase, check the merged commit, ff-only); flake rule; document sessions and check-out/check-in; message delivery and resume-with-answer (test_ask_*); schedule and due evaluation; manager turn timeouts and stall detection; spawn and resume of Claude and Codex sessions; status digest. For each: the test files and names, what invariant they prove, whether they run without the owner service (look for fixtures or stubs), and whether they could become acceptance tests for the minimal tool. End with a list of the 15 most valuable tests to carry over as specs.

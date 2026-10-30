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
Map Otto's existing **spec-folder <-> store document sync** precisely. Start from otto/portfolio/project_folder.py, documents.py, document_navigation.py, show.py, otto/hostctl/portfolio_apply.py, the otto CLI verbs open/save/release/show/retire (otto/portfolio/cli.py), herzchen/authoring/ (sessions.py etc.), herzchen/content, and the tests test_document_sessions.py, test_document_failures.py, test_project_onboarding.py. Answer:
1. The model: what is a document, a revision, a check-out, a check-in/save; how a stale base is detected ("otto_newer", conflict); what gets stored (bytes, hashes, metadata); the size and depth limits.
2. The commands and the end-to-end flow, with an example.
3. What it depends on: the owner service, sockets, the Store kernel, the identity and authority layers. Could it be **extracted as a standalone module over plain SQLite**? Which files and roughly how many lines, and what would have to be cut?
4. Is anything here already scheduled for deletion (SLIM A6 "document mirror", sync.py, sync-docs), and how does that relate?
5. Your recommendation for the minimal design: reuse as code, port the semantics, or rewrite small. Estimate the size.

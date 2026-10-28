# ASK: the orchestrator's answer (16 Oct 2026), resume

**Yes, expand to what the row's outcome needs:**
- `src/otto/portfolio/manager_journey_service.py` (the response handler at :1399) and `src/otto/portfolio/execution.py` (the manager-only continuation at :1768). The answer resumes the asking session, by session and generation, not by task. That change is this row's point: today answers go only to the manager.
- `src/otto/portfolio/cli.py` for the `otto wait` command. It is a thin entry: the long-poll itself is Herzchen's event cursor (`kernel/recovery.py`).
- **The paused guard:** a paused task is refused at the one launch entry, `admit_execution` (`execution_host.py:314`, `:363`), with a test. **Not** the dispatch launcher or `ready()`: those are DISPATCH's, which comes later and builds on your paused state.

Your sandbox now allows Unix sockets (TOOLING12), so run your tests red on `canon/main`, then green. Everything else stands: the invariant (an answer resumes exactly the asking session; a paused task never dispatches), and every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

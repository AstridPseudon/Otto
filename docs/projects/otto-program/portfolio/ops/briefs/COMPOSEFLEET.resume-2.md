# COMPOSEFLEET: the orchestrator's second answer (16 Oct 2026), resume

**Yes to both.** They are what "the owner composes the fleet" means:
1. **The worker's workspace is its assignment's lab.** `ManagerJourneyService._execution` (`src/otto/portfolio/manager_journey_service.py:181`) binds a dispatched worker to the lab the dispatcher created for its assignment, not to the project workspace. Make it one path, not a second one beside the old: every dispatched worker runs in its lab. If a caller truly needs the project workspace (the manager itself, not a worker), name it in your report.
2. **The owner prepares the assessment inputs `LandingService.done` needs.** The candidate is the lab's commit, and the input pins are the admitted revision and the criteria from the dispatch and assessment records, never from the worker's request.

Your work so far is committed (9471c6a). Keep its seven tests. Show the new ones red on `canon/main`, then green. Run the row's check, and say if anything needs the gate's sandbox (`ps`, sockets). The invariant stands: a worker can act only on its own assignment's lab and line. Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

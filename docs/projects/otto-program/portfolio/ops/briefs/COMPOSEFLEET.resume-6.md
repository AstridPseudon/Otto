# COMPOSEFLEET: the remaining seven (the orchestrator, 17 Oct), resume

1. **Yes to the fixtures:** give the services in `tests/test_bounded_project_host.py`, `src/otto/portfolio/tests/test_worker_occurrences.py` and `tests/test_worker_custody.py` the lab provider they now need. That's category 1 in my last message: fixture only, no assertion changed. Keep the provider guard; no fallback to the project workspace.
2. **The seventh** (`test_manager_journey_command.py`, `completion_intent_selection` not found) is fixed on canon: REDS landed `src/otto/portfolio/completion_intent_selection.py` (5f8a728). Your lab has been rebased onto canon/main, so it imports now. Confirm it passes; don't touch its setup.
3. Run all eight selectors to green, then your row's check. Give long runs a long `timeout_ms`. Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

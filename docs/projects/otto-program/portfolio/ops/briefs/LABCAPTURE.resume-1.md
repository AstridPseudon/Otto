# LABCAPTURE resume 1

Continue the existing LABCAPTURE task in the same session. Apply the Orchestrator's 2026-10-17T17:00:24Z direction exactly:

1. `sweep_landed_at_start()` currently runs in the fleet registry constructor (`self.startup_landed_sweep = ...` in `__init__`), before owner custody. Move its one-time invocation to owner start after the owner file is written and `_owns_owner_file = True`.
2. Do not rebuild the lab root manually in `sweep_landed_at_start`. Obtain the fleet through `self._pair(...)`, following `settle_landed_worker`, so lab layout is defined in one place.
3. Remove the `manager_acceptance.accepted` condition from removal. Remove after the owner's capture of the turn result has settled, including rejected capture results; a rejected result's lab must still be removed because its work already landed. Preserve retry behavior for failed removal.
4. Drop `labs-left-behind` from this row; PERCH2C owns that assertion now. Keep the named fake cleanup-hook deletions already completed.

Do not touch any paths owned by other active tasks or their labs. Current active owners are MANUALDISPATCH and FAILCLOSED, with PACKPARITY starting separately; limit edits to LABCAPTURE's owner lifecycle/capture scope and directly required tests. The previous LABCAPTURE brief's `execution_host.py` / capacity exclusion still applies. Do not run staging-owner tests in the sandbox.

Re-run the three focused lifecycle test files from the original brief and relevant focused regressions; report the exact results, changed paths, and any sandbox-only failures. Do not repeat or claim the orchestrator-only stage-2 `--fake` acceptance.

Codex rules: leave changes uncommitted for the launcher; give long tests a long timeout and let them finish. Since this is xhard, lead the invariant review and delegate execution to Luna using `spawn_agent` with `model: "gpt-6-luna"`; review the diff and test tail yourself. Every sub-agent must also use `spawn_agent` with `model: "gpt-6-luna"`.

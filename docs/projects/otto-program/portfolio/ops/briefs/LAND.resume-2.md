# LAND: orchestrator's 16:06Z scope decision, resume

Resume session `01a1456c-d312-7741-9550-c25ac4170299` with the amended row and brief. The 15:59Z scope is withdrawn for facade/hostctl wiring: do not touch `src/otto/agents/claude_cli.py` or `src/otto/hostctl/`. DISPATCH owns the production launch path, token issuance, MCP configuration and owner-side assignment resolution.

Your scope is now:
- `src/herzchen/fleet/landing.py` and `tests/test_landing.py` as before;
- `src/herzchen/fleet/tools/facade.py`: bind the facade's `done` and `check` to the landing lifecycle, tested with real `TokenBook` tokens bound to assignments. `done` starts landing; `check` runs the admitted check through the runner as feedback only and never accepts work.

The host lane cannot determine a worker's assignment. Use the authoritative assignment-bound token supplied by the launch path; never accept assignment identity from request arguments. The transport wiring that issues and grants this token belongs to DISPATCH. Keep `ops/bootstrap/land.sh`, `production/`, and `src/otto/hostctl/` out of scope. Existing invariant, acceptance criteria, tests, and Codex working rules remain in the updated brief. The launcher currently fails to commit this lab's draft because it stages the gitignored `.brief.md`; TOOLING11 is fixing that. Do not remove this lab or assume the launcher has committed your changes; preserve the work on exit and report its exact commit/diff state.

# COMPOSEFLEET: the orchestrator's third answer (16 Oct 2026), resume

**Yes: an owner-declared scope that accepts on the verified check, never a check passed off as a review.**
- Add an assessment scope, declared by the owner per project policy, under which a fleet check that passed on the exact rebased commit is the acceptance (PLAN.md D10: this program runs no per-task review; LAND's invariant is the check on the exact commit). Name it plainly, for example `check-accepted`.
- A project whose policy requires review keeps the current scope, and `done` waits for the manager's review there. Never record a check as review evidence: the two scopes stay distinct.
- The canary project, and this program's own projects when saved, declare the check-accepted scope.

Leave the perch and the staging repo map to the landing gate: don't run `perch.sh` yourself. Show the new scope test red on `canon/main`, then green, and keep your 9 + 14 passing. Give long test runs a long `timeout_ms`; never stop at a window. Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

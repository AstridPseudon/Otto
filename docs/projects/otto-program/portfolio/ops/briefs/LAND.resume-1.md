# LAND: the orchestrator's answer (16 Oct 2026), resume

**Expand your files as follows, and keep everything else as the brief says.**

1. **You own the wiring for the facade's `check` and `done`:**
   - `src/otto/agents/claude_cli.py`: add `worker-check` and `worker-done` to `OWNER_OPERATIONS` (:63), and the facade's tool specs to match. Change nothing else there.
   - The owner-side handlers for those two operations, in `src/otto/hostctl/` (beside `effective-context`: `cli.py:936`'s table and `service.py`). They are thin: they call `herzchen/fleet/landing.py`. `done` starts the landing; `check` runs the task's check through the runner and returns it as feedback only, never acceptance. Otto keeps the wiring, Herzchen the landing (D14).
2. **Don't retire or edit `ops/bootstrap/land.sh`.** It is the tool that lands every task in this program, LAND included. It retires in a later row, once Otto lands its own work. Your deletion budget: name what `landing.py` replaces when that happens, or say "none yet".
3. **`production/` in "Do not touch" is the film's folder** (the Astrid video), not production code. It has nothing to do with this task.
4. Everything else stands: Codex rules, every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`, and the invariant: the line moves only to a commit whose admitted check passed on exactly that commit.

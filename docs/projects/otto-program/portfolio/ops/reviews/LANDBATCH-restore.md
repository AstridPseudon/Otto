# LANDBATCH: fixes before it lands (orchestrator's ruling on Astra's review, ops/reviews/LANDBATCH-astra.md)

Make these changes in the lab, keep the gate tests real (scratch Git repos and a bare remote), and add a test for each numbered item.

1. No time limits anywhere (the user's rule: only a hang fails). Run the whole-gate heavy lease with no deadline (heavy's 60-minute default must not apply: pass its no-deadline option, or add one to `src/otto/hostctl/heavy.py` if none exists), and replace the signal test's 5-second deadline with event-driven waiting (wait for a marker file or a log line, with no deadline).
2. Push first, then move local canon. Push the candidate to GitHub with the expected old value (`--force-with-lease=main:<BASE>` or equivalent), and only after a known success fast-forward the local canon/main ref. Delete the rollback path this makes unnecessary. If the push outcome is unknown (no acknowledgement and `ls-remote` fails), report "LAND RESULT: unknown push outcome ..." and leave local canon alone; the next landing fetches first. A signal at any point must never leave local canon ahead of GitHub.
3. Every task in a batch is judged: a task whose commits are already contained in another batch task still runs its own check and its D19, and is reported as landed within that task. After each check, verify that HEAD still equals the candidate (refuse if a check moved it).
4. Sweep selection is the union of each task's own changed files (not the candidate's net diff).
5. Attribution reads imports with Python's ast (handles `from otto import (\n mod)` and the like), not a line regex.
6. The "LAND RESULT:" line is printed last, after heavy has released its slots and reaped children (print it from outside the heavy wrapper).
7. Raise the batch cap from 8 to 40.
Do not touch ops/manager_loop.py: the orchestrator already added the manager's "land-batch" effect.

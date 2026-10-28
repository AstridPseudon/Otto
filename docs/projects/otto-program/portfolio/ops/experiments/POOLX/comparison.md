# POOL vs POOLX (15 Oct 2026)

Same task, brief and base (c3880e0). POOL: Sonnet 5.5 high alone (a6c885ab), stopped once for disk and resumed.
POOLX: Sonnet 5.5 high lead delegating to Haiku 5.5 high sub-agents (d7f659cf), uninterrupted. Costs are the result JSON's modelUsage (list prices); sub-agent transcripts undercount output tokens, so use modelUsage.

## Time and cost
| | POOL actual | POOL to its disk stop (work committed at 11 min) | POOLX |
|---|---|---|---|
| active wall | 35.5 min | 22.4 min | 24.7 min |
| cost | $3.07 | $2.43 | $2.11 (Sonnet $1.28, Haiku $0.82) |
| Sonnet calls / avg context | 91 / 151k | 70 / – | 37 / 92k |
| Haiku calls | – | – | 122 (4 sub-agents) |
| tool calls (lead / Haiku) | 122 / – | – | 42 / 180 |

## Quality
- Check command: POOL 93 passed; POOLX 77 passed (POOL wrote 26 pool tests, POOLX 10).
- Sweep of the 38 test files that touch the changed modules, each file alone, vs canon e13c927 (src = c3880e0):
  POOL adds one failure, test_bounded_project_host::test_five_projects… (manager peak 3 ≠ 2; failed 4 of 5 runs, never fails on canon or POOLX). Not in its check command.
  POOLX adds none. Shared pre-existing: 12 stopped_writer, 3 correction_planning, 1 reentrant_ipc.
- POOL removes `manager_turn_limit` from ExecutionHost (its own test asserts TypeError) but install/controller/shared_operating_service.py:411 still passes it: the owner would crash at startup after install. POOLX changed that line.
- Admission: POOL fills the manager reserve first (canon-compatible: a worker starts once one of three managers ends). POOLX counts managers against the worker units, so running managers reduce worker turns; it edited two existing tests' expectations to fit (flagged in its report).
- Heavy work: POOL has a FIFO queue with dead-owner pruning and settle/release; POOLX has reserve/release without a queue, released only at restart. Neither is called by production (checks still go through otto-heavy); POOLX says so, POOL doesn't.
- HOLD pin wiring: POOL polls `ps` every 0.25 s for a child carrying the session id (heuristic); POOLX wraps the adapter's process observer (exact pid at spawn; only where an observer exists).
- Size: POOL +434 lines in execution_host.py plus a JSON index file (state kept twice); POOLX +206.
- Reports: POOLX lists its gaps, its edits outside the brief and the brief's wrong path; POOL's report omits the unused heavy API and the production call.

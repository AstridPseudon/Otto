# PROCLIFE: progress

Base: canon/main eb9b6cd. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T20:09:02Z | PLAN-REFRESH | committed f6ed84f | +36/-38 | source/task audit only | Replaced Astrid-only PL tasklist and stale plan with Otto scope plan after checking canon Land merges CUSTODY db1ac48, FAILCLOSED 28408ce, KILLFENCE e2f807b, ORPHANWORKER ac02366; FAILEDFENCE absent from local refs. Initial measured candidate deletion budget 99 direct legacy lines; file-specific actual totals will be logged per merge. Astrid film and sandbox-exec/ps/staging checks need the gate.

2026-10-17T20:17:20Z | PL1 | paused for D19, not merged; task branch b70c817 | +221/-44 | 11 targeted regressions passed; full `tests/test_fleet_custody.py` 21 passed/14 failed | Retained changes in `src/herzchen/fleet/custody.py` and `tests/test_fleet_custody.py` on `.worktrees/PL1`. Removed 22 of the 55 candidate descendant/per-PID lines. Marked sandbox-exec, ps, and Unix-socket cases `needs the gate`; no tests weakened. Astra reviews found failed-spawn intent leak and recovery doubt loss; both fixed and re-reviewed, including census-gap persistence from all entry paths. Existing setsid test was unchanged pending D19.

2026-10-17T20:20:00Z | DIRECTION | decision received | — | — | Orchestrator directs PL1 to keep the existing setsid escapee test expectation unchanged and retain ancestry/census discovery and birth-fenced per-PID signalling for escaped workers. Same-group descendants may be removed where `killpg` makes that work redundant. Deletion budget fixed at 99 direct legacy lines; orchestrator will add PROCLIFE and that budget to PLAN.md §14.

## Xhard review

- PL1 Astra review findings: failed `Popen` stranded its launch intent; census uncertainty was not durable; `status`, `_send`, and `signal_group` also bypassed doubt persistence on unavailable census. Sent these defects to the same worker; fixes landed on task branch through `b70c817`. Astra re-reviewed and found no remaining concrete defect at that revision. Orchestrator then directed preserving setsid escapee cleanup; PL1 is being reworked to that ruling and requires a fresh xhard review before merge.

## File inventory and accounting

Committed project-package files changed from `eb9b6cd`:

- `.project/PROJECT.md`
- `.project/agent_goal.md`
- `.project/manager-brief.md`
- `.project/northstar.md`
- `.project/plan.md`
- `.project/run.json`
- `.project/status.md`
- `.project/tasklist.md`

Unmerged PL1 worktree files on `task/PL1` at `b70c817`:

- `src/herzchen/fleet/custody.py`
- `tests/test_fleet_custody.py`

The current committed project diff is 8 files, +158/-0. Merged implementation deletions: 0. PL1 candidate deletion is 22 lines in its unmerged branch. The agreed 99-line Otto budget is not completed savings; the Astrid package's approximately 4,000-line ambition does not map to this clone.

## Final project review

- Astra's final review found stale run/status metadata and an incomplete changed-file inventory. Updated `.project/status.md` and `.project/run.json` to reflect the authorized run; listed all eight committed project files and the two unmerged PL1 files above. After that review, the orchestrator resolved D19 and fixed the budget at 99 lines. No implementation changes are merged yet.

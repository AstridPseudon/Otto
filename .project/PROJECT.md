# PROCLIFE: progress

Base: canon/main eb9b6cd. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T20:09:02Z | PLAN-REFRESH | committed f6ed84f | +36/-38 | source/task audit only | Replaced Astrid-only PL tasklist and stale plan with Otto scope plan after checking canon Land merges CUSTODY db1ac48, FAILCLOSED 28408ce, KILLFENCE e2f807b, ORPHANWORKER ac02366; FAILEDFENCE absent from local refs. Initial measured candidate deletion budget 99 direct legacy lines; file-specific actual totals will be logged per merge. Astrid film and sandbox-exec/ps/staging checks need the gate.

2026-10-17T20:17:20Z | PL1 | blocked, not merged; task branch b70c817 | +221/-44 | 11 targeted regressions passed; full `tests/test_fleet_custody.py` 21 passed/14 failed | Retained changes in `src/herzchen/fleet/custody.py` and `tests/test_fleet_custody.py` on `.worktrees/PL1`. Removed 22 of the 55 candidate descendant/per-PID lines. Marked sandbox-exec, ps, and Unix-socket cases `needs the gate`; no tests weakened. Astra reviews found failed-spawn intent leak and recovery doubt loss; both fixed and re-reviewed, including census-gap persistence from all entry paths. Astra confirmed ancestry-based signaling removal matches the scope boundary. Existing setsid test still expects ancestry kill; changing it needs the D19 Opus decision, so PL1 cannot merge. PL2–PL6 blocked behind PL1.

## Questions for the orchestrator

- Program PLAN.md §14 has no PROCLIFE row or deletion budget. This clone's measured candidate budget is 99 direct legacy lines (detailed in tasklist); please confirm the intended program-level ambition when you next update the portfolio. Work proceeds against the scoped candidate budget meanwhile.
- D19 requires an Opus decision when a task changes an existing test's expectation. PL1 removes ancestry-based killing, while `tests/test_fleet_custody.py::test_group_kill_takes_grandchildren_and_setsid_escapees` requires that behavior. Please decide whether to change that acceptance contract to the private-group boundary. The focused file also failed on sandbox-exec/socket/ps restrictions here and is marked `needs the gate`; the worker left this existing test unchanged. PL1 and dependent tasks cannot merge until the expectation is approved and the gate passes.

## Xhard review

- PL1 Astra review findings: failed `Popen` stranded its launch intent; census uncertainty was not durable; `status`, `_send`, and `signal_group` also bypassed doubt persistence on unavailable census. Sent these defects to the same worker; fixes landed on task branch through `b70c817`. Astra re-reviewed and found no remaining concrete code defect. Decision: keep the setsid expectation unchanged pending the required Opus decision; preserve the worktree for continuation.

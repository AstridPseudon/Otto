# PROCLIFE: progress

Base: canon/main eb9b6cd. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T20:09:02Z | PLAN-REFRESH | committed f6ed84f | +36/-38 | source/task audit only | Replaced Astrid-only PL tasklist and stale plan with Otto scope plan after checking canon Land merges CUSTODY db1ac48, FAILCLOSED 28408ce, KILLFENCE e2f807b, ORPHANWORKER ac02366; FAILEDFENCE absent from local refs. Initial measured candidate deletion budget 99 direct legacy lines; file-specific actual totals will be logged per merge. Astrid film and sandbox-exec/ps/staging checks need the gate.

2026-10-17T20:17:20Z | PL1 | paused for D19, not merged; task branch b70c817 | +221/-44 | 11 targeted regressions passed; full `tests/test_fleet_custody.py` 21 passed/14 failed | Retained changes in `src/herzchen/fleet/custody.py` and `tests/test_fleet_custody.py` on `.worktrees/PL1`. Removed 22 of the 55 candidate descendant/per-PID lines. Marked sandbox-exec, ps, and Unix-socket cases `needs the gate`; no tests weakened. Astra reviews found failed-spawn intent leak and recovery doubt loss; both fixed and re-reviewed, including census-gap persistence from all entry paths. Existing setsid test was unchanged pending D19.

2026-10-17T20:20:00Z | DIRECTION | decision received | — | — | Orchestrator directs PL1 to keep the existing setsid escapee test expectation unchanged and retain ancestry/census discovery and birth-fenced per-PID signalling for escaped workers. Same-group descendants may be removed where `killpg` makes that work redundant. Deletion budget fixed at 99 direct legacy lines; orchestrator will add PROCLIFE and that budget to PLAN.md §14.

2026-10-17T20:24:47Z | PL1 | merged 964120e | +254/-24 | 12 targeted regressions passed; full `tests/test_fleet_custody.py` 27 passed/14 failed (`needs the gate`) | Preserved the existing setsid escapee test unchanged. Birth-fenced ancestry discovery and per-PID signalling remain for escaped descendants; same-group members use `killpg`. Astra reviewed the reworked diff and found no concrete defect. Correction: the earlier b70c817 interim tally of 22 target lines deleted does not apply after D19 rework; this merge retires no complete candidate legacy block, so budget credit is 0. The 24 net removed lines are not counted as candidate cleanup.
2026-10-17T20:33:50Z | PL2 | merged eec2b98 | +315/-33 | `tests/test_runner.py` 9 passed/11 failed; `tests/test_runner_cli.py` 3 passed/6 failed (`needs the gate`); targeted runner regressions 5 passed and CLI credential regression 1 passed | Removed the 19 measured census-based nesting lines; authenticated run token is checked against one active parent lease, with launch synchronization, malformed-token rejection, and exact lease restoration after uncertain cleanup/restart. Astra re-reviewed through 8d6a1e8 and found no remaining concrete defect. Manager reran both focused files; Unix socket bind restrictions and unavailable process census (`ps`) account for gate failures. Direct deletion credit: 19/99.
2026-10-17T20:42:37Z | PL3 | merged f9d18e3 | +528/-60 | `tests/test_worker_custody.py` 9 passed/13 failed; `tests/test_host_contract.py` 39 passed/2 failed; `tests/test_codex_host_reader.py` 9 passed/1 failed (`needs the gate`); targeted regressions 10/3/2 passed respectively | Persisted the exact PL1 latch path in the existing owner process-group record before native launch; claimed-owner restart resumes only that latch. Unresolved scope keeps physical capacity; exact gone evidence releases the physical slot while occurrence custody remains fenced. Claude/Codex paths surface uncertain cleanup as UNKNOWN, including Codex postlaunch OSError; valid metadata lookup also fails closed on uncertain cleanup. Astra's earlier owner-close and error-return findings were fixed and its final review found no remaining concrete defect. It also found pre-start `restore_execution` can reconstruct capacity before owner claim; manager accepted Astra's scope assessment that this changes no process signaling and does not violate PL3's owner-claim-before-kill criterion. No candidate helper block deleted; direct deletion credit: 0/99.

## Xhard review

- PL1 Astra initially found a failed-`Popen` launch intent leak and census doubt lost on recovery or on unavailable-census early returns. Sent the defects to the same worker; fixes persisted intent/doubt and were included in merged `964120e`.
- The orchestrator then directed preserving setsid escapee cleanup. Astra reviewed the reworked diff at `1b06d2e`: the existing setsid test is unchanged, escaped identities are birth-fenced, same-group signaling uses `killpg`, and no concrete defect was found. Its deletion-accounting correction was adopted: this merge removes no complete candidate legacy block.
- PL2 Astra found restart settlement was not idempotent across repeated restarts, immediate nested submit could race parent launch identity, and non-ASCII tokens could raise from `compare_digest`. All three were returned to the same worker, covered by failing-first regressions, fixed through `8d6a1e8`, and Astra found no remaining concrete defect.
- PL3 Astra found the prelaunch latch was not associated with the owner recovery row, unresolved Codex metadata cleanup was discarded, replacement group identity and cleanup error paths needed stronger handling, and an unclaimed `close()` could resume another owner's latch. The same worker fixed these in `35f95f5`; Astra's final review found no remaining concrete defect. Astra also reported that pre-start `restore_execution` may mutate capacity before owner claim. This affects the capacity ledger but does not signal a process, so it was recorded and not broadened into a task whose stated acceptance is owner claim before kill.

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

PL1 implementation/test files merged in `964120e`:

- `src/herzchen/fleet/custody.py`
- `tests/test_fleet_custody.py`

PL2 implementation/test files merged in `eec2b98`:

- `src/herzchen/fleet/runner/client.py`
- `src/herzchen/fleet/runner/runner.py`
- `tests/test_runner.py`
- `tests/test_runner_cli.py`

PL3 implementation/test files merged in `f9d18e3`:

- `src/herzchen/adapters/host.py`
- `src/herzchen/fleet/hosts/contract.py`
- `src/otto/agents/claude_adapter.py`
- `src/otto/agents/claude_cli.py`
- `src/otto/agents/codex_host_reader.py`
- `src/otto/agents/owner_runtime.py`
- `src/otto/portfolio/execution_host.py`
- `tests/test_codex_host_reader.py`
- `tests/test_host_contract.py`
- `tests/test_worker_custody.py`

Merged implementation deletions credited toward the agreed budget: 19/99 (PL1: 0; PL2: 19; PL3: 0). PL1 and PL3 net removed lines did not retire complete candidate legacy blocks. The Astrid package's approximately 4,000-line ambition does not map to this clone.

Current committed branch diff from `eb9b6cd`: 24 files, +1275/-122 (8 project-package files, two PL1 files, four PL2 files, and ten PL3 files).

## Gate checks

- `tests/test_runner.py`: 11 failures need the gate. Several require Unix-domain socket bind; process lifecycle/capacity assertions also require `ps` census so Custody can prove settlement. The file had 9 passing tests in the manager rerun; focused PL2 regressions passed separately in the worker's test selection.
- `tests/test_runner_cli.py`: 6 failures need the gate due Unix-domain socket bind (`EPERM`); 3 tests passed in the manager rerun.
- PL3 `tests/test_worker_custody.py`: 13 failures need the gate because setup binds an AF_UNIX socket; 9 passed. `tests/test_host_contract.py`: 2 process-cleanup tests need the gate because `ps` is unavailable; 39 passed. `tests/test_codex_host_reader.py`: 1 valid metadata lookup fails closed because `ps` is unavailable; 9 passed. Targeted PL3 regressions passed separately as recorded above.

## Final project review

- Astra's final review found stale run/status metadata and an incomplete changed-file inventory. Updated `.project/status.md` and `.project/run.json` to reflect the authorized run; listed all eight committed project files and the PL1 files above. After that review, the orchestrator resolved D19 and fixed the budget at 99 lines; PL1 then merged after fresh Astra review.

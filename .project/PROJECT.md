# PROCLIFE: progress

Base: canon/main eb9b6cd. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T20:09:02Z | PLAN-REFRESH | committed f6ed84f | +36/-38 | source/task audit only | Replaced Astrid-only PL tasklist and stale plan with Otto scope plan after checking canon Land merges CUSTODY db1ac48, FAILCLOSED 28408ce, KILLFENCE e2f807b, ORPHANWORKER ac02366; FAILEDFENCE absent from local refs. Initial measured candidate deletion budget 99 direct legacy lines; file-specific actual totals will be logged per merge. Astrid film and sandbox-exec/ps/staging checks need the gate.

2026-10-17T20:17:20Z | PL1 | paused for D19, not merged; task branch b70c817 | +221/-44 | 11 targeted regressions passed; full `tests/test_fleet_custody.py` 21 passed/14 failed | Retained changes in `src/herzchen/fleet/custody.py` and `tests/test_fleet_custody.py` on `.worktrees/PL1`. Removed 22 of the 55 candidate descendant/per-PID lines. Marked sandbox-exec, ps, and Unix-socket cases `needs the gate`; no tests weakened. Astra reviews found failed-spawn intent leak and recovery doubt loss; both fixed and re-reviewed, including census-gap persistence from all entry paths. Existing setsid test was unchanged pending D19.

2026-10-17T20:20:00Z | DIRECTION | decision received | — | — | Orchestrator directs PL1 to keep the existing setsid escapee test expectation unchanged and retain ancestry/census discovery and birth-fenced per-PID signalling for escaped workers. Same-group descendants may be removed where `killpg` makes that work redundant. Deletion budget fixed at 99 direct legacy lines; orchestrator will add PROCLIFE and that budget to PLAN.md §14.

2026-10-17T20:24:47Z | PL1 | merged 964120e | +254/-24 | 12 targeted regressions passed; full `tests/test_fleet_custody.py` 27 passed/14 failed (`needs the gate`) | Preserved the existing setsid escapee test unchanged. Birth-fenced ancestry discovery and per-PID signalling remain for escaped descendants; same-group members use `killpg`. Astra reviewed the reworked diff and found no concrete defect. Correction: the earlier b70c817 interim tally of 22 target lines deleted does not apply after D19 rework; this merge retires no complete candidate legacy block, so budget credit is 0. The 24 net removed lines are not counted as candidate cleanup.
2026-10-17T20:33:50Z | PL2 | merged eec2b98 | +315/-33 | `tests/test_runner.py` 9 passed/11 failed; `tests/test_runner_cli.py` 3 passed/6 failed (`needs the gate`); targeted runner regressions 5 passed and CLI credential regression 1 passed | Removed the 19 measured census-based nesting lines; authenticated run token is checked against one active parent lease, with launch synchronization, malformed-token rejection, and exact lease restoration after uncertain cleanup/restart. Astra re-reviewed through 8d6a1e8 and found no remaining concrete defect. Manager reran both focused files; Unix socket bind restrictions and unavailable process census (`ps`) account for gate failures. Direct deletion credit: 19/99.
2026-10-17T20:42:37Z | PL3 | merged f9d18e3 | +528/-60 | `tests/test_worker_custody.py` 9 passed/13 failed; `tests/test_host_contract.py` 39 passed/2 failed; `tests/test_codex_host_reader.py` 9 passed/1 failed (`needs the gate`); targeted regressions 10/3/2 passed respectively | Persisted the exact PL1 latch path in the existing owner process-group record before native launch; claimed-owner restart resumes only that latch. Unresolved scope keeps physical capacity; exact gone evidence releases the physical slot while occurrence custody remains fenced. Claude/Codex paths surface uncertain cleanup as UNKNOWN, including Codex postlaunch OSError; valid metadata lookup also fails closed on uncertain cleanup. Astra's earlier owner-close and error-return findings were fixed and its final review found no remaining concrete defect. It also found pre-start `restore_execution` can reconstruct capacity before owner claim; manager accepted Astra's scope assessment that this changes no process signaling and does not violate PL3's owner-claim-before-kill criterion. No candidate helper block deleted; direct deletion credit: 0/99.
2026-10-17T20:55:00Z | PL4 | merged 580c6c4 | +508/-70 | 11 targeted custody regressions passed; manager `tests/test_heavy_lease.py` run: 14 passed, 8 failed, interrupted at 463s when remaining process cases blocked (`needs the gate`) | Replaced environment-tag signalling with exact recorded identity and private-group ancestry observation. Added pending launch intent; a private session root durably records its exact birth identity then waits for holder release before executing CMD. Holder death before release prevents CMD start; pending/unresolved claims survive recovery. Astra's re-review found no remaining concrete defect. The double-fork/setsid child reparented entirely between observations remains the explicit containment limitation in the goal. Direct deletion credit: 25/99.
2026-10-17T20:58:48Z | PL5 | merged 05ec363 | +94/-17 | `tests/test_runner_cli_retry_key.py` 1 passed; `tests/test_runner.py -k uncertain_scope_holds_only_its_own_units` 1 passed; `tests/test_runner_cli.py -k submit_mints_request_id_before_client_transport` 1 failed at AF_UNIX socket bind (`needs the gate`); worker's full CLI file run 3 passed/7 failed on the socket gate | Unknown run await/status now includes `next_action`. CLI mints and returns request IDs; a transport error exposes the same key for exact retry. Manager review caught and returned the initial transport-failure key loss; failing-first regression confirmed it and the worker fixed it. Worker guidance and manager journey entry were shortened. No direct lifecycle behavior/status lines deleted; direct deletion credit: 0/99. Installed-owner cold-agent baseline/result needs the gate; no owner/staging session was started.
2026-10-17T21:00:36Z | PL6 | merged e6b27eb | +70/-6 | `git diff --check` passed; no tests rerun | Reconciled the PL1–PL5 file inventory, 44/99 direct deletion credits, gate-dependent tests, cold-agent protocol, and exact normal/SIGKILL/Astrid film handoff probes. All PL1–PL5 tests and external gates remain as recorded; no owner or staging command was run. Final manager-owned whole-project Astra review follows. No source deletion; direct deletion credit remains 44/99.
2026-10-17T21:04:34Z | PL4-G1 | merged 4e195a1 | +73/-5 | `tests/test_heavy_lease.py -k 'census_gap_is_sticky_through_empty_cleanup_and_dead_holder_recovery or normal_run_persists_a_census_gap_even_if_later_scans_succeed'` 2 passed; worker selected PL4 regressions 13 passed | Final Astra review found that a census gap could be erased by later empty scans. Persisted sticky `census_gap` in the existing holder record from the run loop and each cleanup census/recheck; recovery retains the claim across process restart. The same PL4 worker fixed both failing-first regressions; Astra reviewed the fix and found no remaining defect. Direct deletion credit: 0.
2026-10-17T21:06:43Z | PL5-NEXTACTION | merged 7209c93 | +3/-1 | `tests/test_runner_cli_retry_key.py` 1 passed | Astra found the structured transport-error refusal exposed the request key but omitted `next_action`. The PL5 worker added exact-same-key retry guidance and a regression assertion; manager reran the focused file successfully. No deletions.

## Xhard review

- PL1 Astra initially found a failed-`Popen` launch intent leak and census doubt lost on recovery or on unavailable-census early returns. Sent the defects to the same worker; fixes persisted intent/doubt and were included in merged `964120e`.
- The orchestrator then directed preserving setsid escapee cleanup. Astra reviewed the reworked diff at `1b06d2e`: the existing setsid test is unchanged, escaped identities are birth-fenced, same-group signaling uses `killpg`, and no concrete defect was found. Its deletion-accounting correction was adopted: this merge removes no complete candidate legacy block.
- PL2 Astra found restart settlement was not idempotent across repeated restarts, immediate nested submit could race parent launch identity, and non-ASCII tokens could raise from `compare_digest`. All three were returned to the same worker, covered by failing-first regressions, fixed through `8d6a1e8`, and Astra found no remaining concrete defect.
- PL3 Astra found the prelaunch latch was not associated with the owner recovery row, unresolved Codex metadata cleanup was discarded, replacement group identity and cleanup error paths needed stronger handling, and an unclaimed `close()` could resume another owner's latch. The same worker fixed these in `35f95f5`; Astra's final review found no remaining concrete defect. Astra also reported that pre-start `restore_execution` may mutate capacity before owner claim. This affects the capacity ledger but does not signal a process, so it was recorded and not broadened into a task whose stated acceptance is owner claim before kill.
- PL4 Astra found unidentified-PID recovery, unreadable Linux process identity, verified PID reuse, and the spawn-to-persist crash window. The PL4 worker fixed all four with failing-first regressions; Astra re-reviewed through `65f3257` and found no remaining concrete defect. The separately observed fast double-fork/setsid/reparent gap is accepted under the goal's explicit never-recorded-daemonization limit. Manager's full focused file run showed 14 pass and 8 gate failures before it was interrupted while a process-census case remained blocked; selected custody regressions passed.
- The whole-project Astra review then found PL4 could erase an unavailable process-census gap after later empty scans, violating G1 across restart. Returned it to the same PL4 worker; failing-first cleanup/restart and normal-run regressions passed after it durably set `census_gap` on any unavailable census and retained the holder forever as unknown. Astra reviewed the fix diff and found no remaining defect. The existing manager full-file failures still need the `ps` host gate.
- PL5 was a normal-route Agent-UX pass, so no Astra review was required. Manager review found the first request-key change lost its minted ID when transport failed; the same worker added a failing-first regression and exposed the key in the structured transport error. Manager's focused retry and unresolved-scope checks passed. The CLI fixture's AF_UNIX socket bind is denied here and remains a gate check.

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

PL4 implementation/test files merged in `580c6c4`:

- `src/otto/hostctl/heavy.py`
- `tests/test_heavy_lease.py`

PL5 implementation/test/guidance files merged in `05ec363`:

- `docs/manager-journey-commands.md`
- `src/herzchen/fleet/runner/runner.py`
- `src/otto/portfolio/skills/references/worker.md`
- `src/otto/runner_cli.py`
- `tests/test_runner.py`
- `tests/test_runner_cli.py`
- `tests/test_runner_cli_retry_key.py`

Merged implementation deletions credited toward the agreed 99-line ambition: 44/99 (PL1: 0; PL2: 19; PL3: 0; PL4: 25; PL4-G1: 0; PL5: 0). The remaining 55 measured candidate lines are PL1's escaped-descendant ancestry and exact per-PID cleanup retained by D19. PL3's proposed helpers were retained because production callers still rely on them; PL5 shortened prose but did not retire a measured lifecycle block. This is a recorded shortfall against the §15 ambition, not a claim that 99 lines were removed. The Astrid package's approximately 4,000-line ambition does not map to this clone.

Current committed branch diff from `eb9b6cd`: **31 files, +2077/-204** (`git diff --shortstat eb9b6cd...proj/proclife`). The inventory is 8 original project-package files, one PL5 gate-evidence file, and 22 implementation/test/docs files.

Complete implementation, test, and user-guidance inventory (all paths changed by PL1–PL5):

- `docs/manager-journey-commands.md`
- `src/herzchen/adapters/host.py`
- `src/herzchen/fleet/custody.py`
- `src/herzchen/fleet/hosts/contract.py`
- `src/herzchen/fleet/runner/client.py`
- `src/herzchen/fleet/runner/runner.py`
- `src/otto/agents/claude_adapter.py`
- `src/otto/agents/claude_cli.py`
- `src/otto/agents/codex_host_reader.py`
- `src/otto/agents/owner_runtime.py`
- `src/otto/hostctl/heavy.py`
- `src/otto/portfolio/execution_host.py`
- `src/otto/portfolio/skills/references/worker.md`
- `src/otto/runner_cli.py`
- `tests/test_codex_host_reader.py`
- `tests/test_fleet_custody.py`
- `tests/test_heavy_lease.py`
- `tests/test_host_contract.py`
- `tests/test_runner.py`
- `tests/test_runner_cli.py`
- `tests/test_runner_cli_retry_key.py`
- `tests/test_worker_custody.py`

The eight project-package files are `.project/PROJECT.md`, `.project/agent_goal.md`, `.project/manager-brief.md`, `.project/northstar.md`, `.project/plan.md`, `.project/run.json`, `.project/status.md`, and `.project/tasklist.md`.

Additional project evidence file: `.project/evidence/PL5-ux-gate.md` records why the installed-owner cold-agent comparison needs the gate and the paired measurement protocol.

### PL5 installed-owner cold-agent baseline

**Result: needs the gate. No installed-owner measurement was run in this restricted worktree.** No baseline or post-change time, tool count, or outcome is claimed. Measure on the installed Otto staging owner with a cold agent receiving only its installed role introduction and entry point: (1) present a retained occurrence/run whose cleanup is `unknown`; (2) ask the agent to identify the scope and safe next action; (3) observe whether it reads the exact status/occurrence and follows `next_action` (wait or reconcile) without issuing a new request key or retrying provider work; (4) record elapsed time, exact verbs/tool calls, whether the scope was identified, whether recovery guidance was followed, and any unsafe retry. Run baseline against the parent install and result against PL5 install under identical fixtures and instructions. Attach both transcripts and measurements to the gate receipt.

### Gate handoff probes — not run here

The orchestrator/staging owner should run these using the current installed introduction and its pinned interpreter/client paths. Preserve raw request IDs, occurrence/run IDs, state snapshots, and process identities in the gate receipt.

1. **Normal operation:** through the installed normal manager/runner route, submit one bounded harmless command with a stable request key, read its exact request/occurrence, follow/await it, and verify successful terminal status, captured result, parent consumption where applicable, and released capacity. Repeat the exact lookup with the same key/input and prove it returns the same occurrence without a second launch. Then exercise an unresolved-scope refusal and confirm `next_action` points to status/reconcile; do not create a new key to bypass it. For the lower-level Otto runner, use the installed `otto run submit`/`await`/`status` commands documented in the installed help and verify the minted `request_id` is returned.
2. **SIGKILL recovery:** on an isolated staging host, start one bounded child through the installed owner and capture its exact occurrence, owner recovery row, PID/birth identity and process group. SIGKILL the owner at the controlled point after durable launch intent/identity exists but before settlement. Restart the owner; inspect the same occurrence and recovery row; verify only the matching recorded incarnation is cleaned up, the state remains unknown while evidence is incomplete, capacity/custody remain held as specified, and another independent project can proceed only within its own capacity. Reconcile, then prove terminal settlement and no provider retry. Repeat with PID/group reuse and require the replacement process to survive. This is a staging fault-injection probe, not a local test command.
3. **Astrid film journey:** run only on the orchestrator's actual Astrid project/film installation (absent from this clone). Use the canonical film task and current installed manager route; capture the exact admission, worker/film execution, artifact/result publication, parent consumption, recovery/status, and final journey evidence. Inject an owner interruption at the documented recoverable boundary, restart/reconcile the same retained journey, and verify no duplicate film/provider execution and no false completion. Record the installed project/task refs, command/tool calls, artifact refs/hashes, timings, recovery result, and explicit pass/fail criteria. The Otto custody tests do not substitute for this film gate.

All three probes remain **needs the gate**. PL6 has not run an owner, staging owner, `ottoctl`, `perch.sh`, `land.sh`, or staging/film gate.

### PL6 integration checks

Focused results and gate-dependent failures above are the PL1–PL5 evidence; no test suite was rerun during PL6. PL6 ran only `git diff --check` before commit. Full Otto staging, Unix socket/`ps`/`sandbox-exec` process checks, SIGKILL recovery, the cold-agent installed-owner comparison, and Astrid film journey remain gate-dependent.

## Gate checks

- `tests/test_runner.py`: 11 failures need the gate. Several require Unix-domain socket bind; process lifecycle/capacity assertions also require `ps` census so Custody can prove settlement. The file had 9 passing tests in the manager rerun; focused PL2 regressions passed separately in the worker's test selection.
- `tests/test_runner_cli.py`: 6 failures need the gate due Unix-domain socket bind (`EPERM`); 3 tests passed in the manager rerun.
- PL3 `tests/test_worker_custody.py`: 13 failures need the gate because setup binds an AF_UNIX socket; 9 passed. `tests/test_host_contract.py`: 2 process-cleanup tests need the gate because `ps` is unavailable; 39 passed. `tests/test_codex_host_reader.py`: 1 valid metadata lookup fails closed because `ps` is unavailable; 9 passed. Targeted PL3 regressions passed separately as recorded above.
- PL4 `tests/test_heavy_lease.py`: manager run had 8 failures and 14 passes before interruption after 463 seconds. Failed cleanup cases leave exact claims unresolved when macOS process census (`ps`) is denied; waiting integration tests then time out behind those correctly retained claims. These process-census/cleanup cases need the gate. The worker's 11 selected custody regressions, including the spawn crash handshake, passed.
- PL4-G1 `tests/test_heavy_lease.py` census-gap regressions: manager selected run 2 passed; worker's selected set 13 passed. The full file remains gate-dependent because macOS `ps` census is denied.
- PL5 `tests/test_runner_cli.py`: socket fixture bind is denied (`EPERM`), so its manager-targeted mint test failed at setup and worker full-file run had 7 socket-gate failures (3 passed). The standalone transport retry key regression passed after both retry-key and `next_action` fixes. The installed-owner cold-agent measurement needs the gate.

## Final project review

- Astra's final review found stale run/status metadata and an incomplete changed-file inventory. Updated `.project/status.md` and `.project/run.json` to reflect the authorized run; listed all eight committed project files and the PL1 files above. After that review, the orchestrator resolved D19 and fixed the budget at 99 lines; PL1 then merged after fresh Astra review.
- Astra's first whole-project review found two concrete defects: PL4 census-gap loss could falsely settle custody after a later empty scan; PL5's transport refusal lacked `next_action` for exact-key recovery. The same PL4 worker fixed the census gap and dedicated Astra review found no remaining defect. The same PL5 worker added exact-key recovery guidance and the focused regression passed. Fresh final whole-project Astra review at `deea8ca` found no remaining evidence-backed defect and confirmed D19, G1/G2, inventory, 31 files +2077/-204, 44/99 deletion accounting, and gate disclosure. Astra ran no tests. External gates remain pending.
- Astra xhard findings and dispositions for PL1–PL4 are recorded above. PL5/PL6 used the normal route; the PL5 retry-response follow-up came from final review. Do not treat PL6 completion as the final whole-project review.

## Canon integration audit — corrections in progress

On 17 Oct 2026, Astra's integration audit `ops/audits/astra-strategy/INTEGRATE-PROCLIFE.md` reviewed `df534f3` against `eb9b6cd`; canon had advanced to `d02e46e` with FAILEDFENCE, OWNERCOMPLETION, FACADEFD, CTLRACE and CAPTUREEDIT. The audit blocks wholesale integration and identifies six corrections: exact kernel birth identity for PL1; PINALL-compatible PL3 capacity settlement; PL2 missing-parent/unmatched-latch accounting; durable PL3 metadata-reader custody; PL4 same-group descendant cleanup; and PL5 guidance based on current custody plus heavy status details. It also blocks PL4's timing-only spawn crash test. These are being handled as isolated failing-first follow-ups and receive Astra review before merge. PL6 remains evidence only and is not a canon source landing.

The audit also names D14 placement: fleet custody mechanisms stay in Herzchen. PL1's birth reader will therefore be a single shared primitive in the fleet layer, with `otto.portfolio.execution_host._process_start_identity` kept as the ORPHANWORKER-compatible entry point. The changed bystander assertion from D19 remains an orchestrator question in `.project/tasklist.md`; earlier D19 approval preserved the setsid escapee test and did not explicitly decide this assertion. The audit's 99-line deletion ambition is met by 44 credited lines; the remaining 55 stay for escaped-descendant custody under D19. The audit's full eight-file/twice-on-unrestricted-host check and staging/owner/film probes remain gate work and are not claimed here.

### Correction merge log

- 2026-10-17 21:58 UTC | PL1-BIRTH | merged `95fcd426999ab7d53b616c4b7a7a049228bd2f48` | +266/-55 | manager focused custody regressions 8 passed; worker focused selection 12 passed | Astra found stale ps/kernel PID-lifetime binding; fixed with kernel parent/group consistency and regressions, then Astra found no remaining defect. The unchanged setsid escapee acceptance test still needs the gate because `/bin/ps` is denied.
- 2026-10-17 22:01 UTC | PL3-CAPACITY | merged `5fef03a38e7c6269c64660c295ccea594c6944c4` | +59/-13 | capacity unit regressions 3 passed; worker-custody regression 1 passed | Astra found no defect. The two original capacity integration tests remain unchanged but need the socket gate (`EPERM` during shared fixture setup).

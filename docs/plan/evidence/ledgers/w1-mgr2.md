## mgr2 ledger

### Span, goal, outcome

**Observed.** Mgr2 ran from **28 Oct 02:52 to 04:54 UTC**. It was asked to restore the updater program, run three parallel Opus reviews, check the known Pinokio busy-refusal failure against `upd-base`, then run review fixes by tier, up to four at once. It was also told to keep its own context small by sending command output to `/tmp` and reading summaries [10-28 02:52].

**Observed.** It finished the review round’s blocking tasks, plus one non-blocking task: busy-refusal test fix; App N1, N2, N3, N4, N5, N6; Pinokio H1; Agent A-N1, A-H1, A-N3, A-N2; and Runtime S1. It pushed snapshots and reported completion to the orchestrator at 04:53 [10-28 04:53].

**Observed.** The orchestrator’s instruction was to land round 1 blockers S1 and N6, push, and report—without starting round 2. Mgr2 did that. It also completed A-N2 while waiting [10-28 03:58]. The full Pinokio stopped-update integration run for S1 timed out at 25 minutes; mgr2 reran the two new kill-point cases, verified those passed, and disclosed the unverified full-run result [10-28 04:52–04:53].

### Event table

| time | type | what happened | evidence | outcome |
|---|---|---|---|---|
| 02:52 | START/RESTORE | Took over final phase; read brief and checked repository state. | `IN`: “Start now”; [10-28 02:52] | Import succeeded; pull failed because the plan repo was on detached HEAD. |
| 02:54 | FIX-ROUND | Switched to the designated plan branch after checking ancestry. | [10-28 02:54] “repo is on a detached HEAD” | Continued from the designated branch tip. |
| 02:55 | CHECK | Read queue, reviews, and open row 26 finding; confirmed C2c was deferred. | [10-28 02:55] | Identified review row 15 and the stopped-state handoff finding. |
| 02:55–02:56 | TEST-RUN | Compared Pinokio suite on `prog/upd` and `upd-base`. | [10-28 02:55–02:56] | `prog/upd`: 143 tests, 1 failure; `upd-base`: 52/52 pass. Classified the busy-refusal test as a UPD regression. |
| 02:56–02:57 | DISPATCH | Prepared three area briefs with diff summaries and contract extracts; created a task for the busy-refusal issue. | [10-28 02:56–02:57] | Used `UPD-FR1-*` folders to avoid overwriting earlier review artifacts. |
| 02:57 | DISPATCH | Started the busy-refusal fix before reviews completed. | [10-28 02:57] | Hard-tier task ran in parallel with review work. |
| 03:02 | CHECK | App review returned `BLOCKING: 4`; manager wrote queue rows for four fixes. | [10-28 03:02] | N1 running; N2, N3, H1 queued; agent and Runtime reviews still running. |
| 03:02–03:03 | CHECK | Worker found the failure was a test timing race: a killed grandchild was a zombie awaiting reaping, not a live leak. | [10-28 03:02–03:03] | Manager reviewed the test-only diff and reran the full Pinokio suite: 142 pass, 0 fail, 1 skip. |
| 03:04 | LAND | Landed busy-refusal fix. | [10-28 03:04] | A mistaken `update-ref` moved `prog/upd` to an older commit; the manager caught it and restored the ref using explicit SHAs and an expected-old guard. |
| 03:04 | DISPATCH | Started H1, the Pinokio async-update fix, alongside N1 and the two reviews. | [10-28 03:04] | Four workers active. |
| 03:05–03:07 | CHECK / LAND | Reviewed and landed App N1, which exposed required updates on the page. | [10-28 03:05–03:07] | Focused tests passed 7/7; `prog/upd` advanced to `b8584ea`. |
| 03:06–03:10 | STALL/CONFUSION / ESCALATE | Re-vendoring the App runtime lock fixed the lock check but broke `installManifestSkew.test.ts`; manager confirmed the break was caused by the re-vendor and escalated options. | [10-28 03:06–03:10] | N4 left unlanded pending a ruling. |
| 03:10 | RECEIVED-RULING/CORRECTION | Orchestrator chose ruling B: keep shipped Runtime pin, revert the hand-patched generated type, add a defensive release read and tests. | [10-28 03:10] | N4 re-tiered Hard, queued until a slot opened. |
| 03:10–03:12 | CHECK / LAND | N2 fixed fully-local required-update manifest reading. | [10-28 03:10–03:12] | Manager reran focused tests (3/3); landed at `e54b61e`. |
| 03:12 | DISPATCH | Started N3 and converted agent-review findings into A-H1, A-N1, A-N2, renaming to avoid task-ID collisions. | [10-28 03:12] | A-N1 ran; A-H1 and A-N2 queued. |
| 03:15 | LAND / DISPATCH | Landed Pinokio H1 and started Agent A-H1. | [10-28 03:15] | Full Pinokio suite: 146 pass, 0 fail, 1 skip. |
| 03:20–03:23 | CHECK / CORRECTION | Found two App failures and the skip-policy failure during landing checks; disproved workers’ “pre-existing” claims by checking `upd-base` or bisecting. | [10-28 03:20–03:23] | Briefed N5 for App regressions and A-N3 for skip policy; left A-H1 running. |
| 03:22–03:23 | LAND | Landed A-N1 (installer fixture fixes) and N3 (fully-local update command). | [10-28 03:22–03:23] | Agent ref `6b5003a`; App ref `b6c66d8`. |
| 03:23 | DISPATCH | Started N5 and A-N3; N5 addressed the two App regressions, A-N3 the hand-written skips. | [10-28 03:23] | Continued with four active workers, including A-H1 and Runtime review. |
| 03:24–03:25 | CHECK / LAND | A-N3 replaced hand skips with lane/unavailable declarations. | [10-28 03:24–03:25] | Guard tests passed 55/55; ruff reported 11 pre-existing errors in the new test file. |
| 03:27–03:32 | CHECK | N5 fixed provider-less `AppHeader` use and corrected a stale Settings test expectation; full-suite comparison showed two failures fixed and unrelated existing failures remained. | [10-28 03:27–03:32] | Manager did not accept the worker’s claim that VideoEditorPage failures were pre-existing without checking the base. |
| 03:31–03:39 | CHECK / LAND | Reviewed A-H1’s change to keep the pre-C1 probe and update stale fixture expectations. Merged current `prog/upd` into its branch before the full test rerun. | [10-28 03:31–03:39] | 1,259 passed, 22 skipped, 3 failures also on base; landed Agent ref `7b96c05`. |
| 03:39 | CHECK | Runtime review returned `BLOCKING: 1`, S1: recovery could be stranded if the controller died mid-stop. | [10-28 03:39] | Briefed as Super-hard and dispatched to sonnet. |
| 03:39–03:47 | DISPATCH / LAND | N4 followed ruling B: re-vendored from the shipped Runtime, guarded the release read, added tests and release note. | [10-28 03:39–03:47] | Manager verified focused tests and vendor lock, then landed App ref `6310c92`. |
| 03:54–03:57 | STALL/CONFUSION / FIX-ROUND | N5’s full suite uncovered a mock gap from using the safe Runtime hook; manager had the worker update the mock and checked VideoEditorPage against `upd-base`. | [10-28 03:54–03:57] | Confirmed the page failures were regressions, not pre-existing; dispatched N6. |
| 03:58 | RECEIVED-RULING/CORRECTION | Orchestrator directed: land S1 and N6, push and report; do not start round 2. A-N2 could ride along if quick. | [10-28 03:58] | Mgr2 started A-N2 as a non-blocking task. |
| 04:00–04:01 | CHECK | A-N2 added a real-C1 crash-recovery test; mutation check made it fail when the stop path was stubbed. | [10-28 04:00–04:01] | Adjacent tests passed; manager landed it at Agent ref `472f76c`. |
| 04:01–04:11 | LAND / CHECK | N6 fixed VideoEditorPage’s stale auth mock and source-checkout banner expectation. | [10-28 04:01–04:11] | Manager reran the file: 71/71; landed App ref `3afbc89`. |
| 04:11–04:27 | IDLE/WAIT / TEST-RUN | S1 worker’s broad Agent integration run continued through long background runs. | [10-28 04:11–04:27] | Worker reported Runtime 126 and Agent 30 passing; manager began independent verification. |
| 04:27–04:37 | CHECK / LAND | Manager reran Runtime suites and landed Runtime S1. | [10-28 04:27–04:37] | Runtime tests passed 126/126; Runtime ref `ee05c23`. |
| 04:37–04:52 | IDLE/WAIT | Agent integration verification kept running; manager recorded Runtime landing and waited. | [10-28 04:37–04:52] | The manager’s 25-minute run timed out after 29 tests; it isolated the two new kill-point cases. |
| 04:52–04:53 | TEST-RUN / LAND | Reran the S1 kill-point tests; both passed, then landed Agent test changes. | [10-28 04:52–04:53] | Agent ref `5149baa`; full file still not independently verified to 30/30. |
| 04:53 | SNAPSHOT/PUSH / REPORT | Exported and pushed snapshot; messaged orchestrator with landed refs and caveat. | [10-28 04:53] | Round 1 blockers complete; no round 2 started. |

### How it worked

- **Parallelism — observed:** It used the four available worker slots repeatedly. At 03:04, for example, it reported four workers: agent and Runtime reviews, H1, and N1 [10-28 03:04]. It queued new tasks as slots opened, rather than dispatching all work at once.
- **Model choices — observed:** The brief called for Normal on Haiku, Hard on Haiku at xhigh with Sonnet after one failure, and Super-hard on Sonnet [10-28 02:52]. Normal fixes used Haiku; H1, A-H1 and N4 used Haiku at xhigh; S1 used Sonnet [10-28 03:10, 03:15, 03:39]. The three area reviewers were asked for Opus reviews [10-28 02:56]; they completed at 03:02, 03:12 and 03:39.
- **Briefing and review — observed:** It wrote bounded area-specific reviewer briefs using diff summaries and contract extracts, then turned findings into per-task briefs and separate worktrees [10-28 02:56–02:57, 03:12]. It required workers not to commit or merge, reviewed diffs itself, reran focused tests, and used checked refs for landings.
- **Test handling — observed:** Long outputs generally went to `/tmp` or run-folder logs; manager summaries quoted counts and verdicts. It checked “pre-existing” claims against `upd-base` or an earlier commit, correcting several worker misclassifications. It also noticed that root `tsc --noEmit` was a no-op because root `tsconfig.json` had `"files": []`, and used `tsconfig.app.json` instead [10-28 03:31].
- **Context growth — observed and inferred:** The instructions explicitly said to keep output small [10-28 02:52], and mgr2 often followed that. But long worker activity was still interleaved into its transcript, with frequent `SUBAGENT` tool output. **Inference:** the split between manager and worker contexts reduced direct code-reading load, but did not fully insulate the manager from noisy asynchronous results.

### Friction

- **Branch safety:** A mistaken ref update moved Pinokio `prog/upd` backwards to `bbba620`; mgr2 caught and repaired it with an expected-old guard [10-28 03:04]. The error arose because it ran the update in a clone whose `HEAD` was on the wrong branch.
- **Weak regression attribution:** The first App worker called `vendorLock` pre-existing; mgr2 checked both branches and found it passed on `upd-base` but failed on `prog/upd` [10-28 03:05–03:07]. N3’s “two pre-existing” claim was also wrong; bisecting showed one regression from D1 and one from N1 [10-28 03:20–03:22].
- **Review and task naming collided:** Agent review’s H1/N1 task IDs overlapped with already-running Pinokio H1/App N1, so mgr2 renamed them to A-H1/A-N1/A-N2 [10-28 03:12].
- **Tool-use friction:** Several test attempts used unsupported `--basetemp` flags with Vitest; edits were also rejected until files had been read through the editor’s Read tool [10-28 03:04, 03:10–03:11, 03:14]. These were corrected, but consumed iterations.
- **Overlapping test work:** A-H1 initially tested against an older base; mgr2 merged current `prog/upd` and reran the suite before landing [10-28 03:34–03:39]. N5 likewise required additional checks after the worker’s attribution proved wrong.
- **Incomplete long-run verification:** The manager’s full Agent integration run timed out one test short of the worker’s reported count. It verified the two new tests separately and disclosed the remaining gap rather than treating the worker’s count as its own [10-28 04:52–04:53].

### Which instructions changed its behaviour

- **Initial handoff:** The orchestrator specified the restore procedure, three parallel Opus reviews, the base-branch comparison for the busy-refusal test, tier/model mapping, and `/tmp` output discipline [10-28 02:52]. Mgr2 followed the review structure and model tiers, and used the base comparison to classify the test.
- **N4 ruling:** Orchestrator chose ruling B after the re-vendor broke schema compatibility [10-28 03:10]. Mgr2 reset the unlanded attempt and rewrote N4 to keep Runtime `11443b0`, avoid hand-editing generated types, and make the release read defensive.
- **End-of-round direction:** The orchestrator asked it to land S1 and N6, push and report, and not start round 2 [10-28 03:58]. Mgr2 complied, while starting only the allowed non-blocking A-N2.

### What it needed but didn’t have

- **Observed:** No automatic safeguard stopped a ref update from targeting the wrong clone/branch; mgr2 found the mistake by checking afterward [10-28 03:04].
- **Observed:** It lacked a reliable short status for long-running workers and integration tests; it inspected output files and waited for notifications, and its own long Agent run timed out [10-28 04:37–04:53].
- **Inference:** A structured landing checklist could have reduced repeated branch, test-baseline, and “pre-existing” verification work. The manager repeatedly had to reconstruct which commit, worktree, and test claim a worker meant before deciding whether to land.
## Lens: Manager supervision and cadence

### Findings

1. **The intended oversight cadence was hourly, with a deeper review every six hours.** The owner requested those loops on 10-26 22:32; the hourly and deep-check triggers were created at 22:57. Early hourly ticks could also land reviewed work and dispatch the next tasks. The 10-27 01:50 runbook change narrowed the hourly role to “babysit only.” [10-26 22:32, 22:57; `data/main-full.txt`; `/home/user/repo/astrid-install/ORCHESTRATOR.md`]

2. **There’s no evidence of a recurring 15-minute orchestrator check-in.** The documented manager self-wake schedule was `send_later` every 20 minutes while working and 60 minutes while waiting. That caused the manager to stop after one task and wait; at 00:35–00:36 on 10-28, the owner corrected this. The orchestrator told the manager to cancel its pending wake-up, work back to back, and rely on the hourly check as its safety net. [10-28 00:35–00:36; `data/compaction-summaries.txt`; `handoff-upd/BRIEF-claude-manager.md`]

3. **Check-ins combined live session inspection with saved-state inspection.** The later runbook called for `get_session` to check status and rate limits, `list_events` to inspect recent activity, and review of the latest snapshot manifest and queue. It also asked whether work had landed in the last two hours, whether the sequence made sense, whether tests supported “passed” claims, whether work was looping, and whether it was headed to the end state. Earlier ticks also checked uptime, dispatcher logs, worker liveness, escalations, queue states, and branch tips. [`/home/user/repo/astrid-install/ORCHESTRATOR.md`, “Hourly tick”; 10-27 02:57–03:58; `data/main-full.txt`]

4. **Interventions were specific corrections, not routine status pings.** At 00:36, a `send_message` stopped self-scheduled idling and restarted back-to-back dispatch. At 14:17, another message halted 70-minute full-suite bisects and prescribed narrow isolation checks. At 16:58, after an integration run was silent since 16:21, the manager was told to run bounded chunks, record hangs as “not run,” and close with a completion report. At 10:19, the orchestrator caught contradictions between the rebase plan and its rulings and required the plan to be reconciled. [10-28 00:36, 10:19, 14:17, 16:58; `data/main-full.txt`]

5. **The recorded effects of interventions were mixed but visible.** The back-to-back instruction was picked up “straight away”; the 14:17 reroute avoided further long full-suite hunts; and the bounded R8 approach produced a closeout that recorded 1,021 tests as hung/not run rather than leaving their state implicit. Conversely, the 10:19 instruction corrected contradictory documents, showing that the manager’s own queue and plan had not yet formed one coherent source of truth. [10-28 00:36, 10:19, 14:17, 20:56; `data/main-full.txt`; `data/managers/mgr1-page-001.json`]

6. **Managers were replaced at provider, context, and phase boundaries.** The Codex manager handed over after a usage limit; a Claude Haiku manager was created at 00:23 on 10-28. At 01:57 its context was reported at 263K tokens, and at 03:57 a later manager was at 281K; fresh sessions were started for the final review phase. At 09:59 a new manager was created for rebase execution, with the prior one told to stop and then archived. The final rebase manager was archived at closeout. These are observed reasons and phase transitions; the records do not establish that context size alone caused every replacement. [10-28 00:00, 00:23, 01:57, 02:52, 03:57, 09:59, 20:38; `data/main-full.txt`; `data/compaction-summaries.txt`]

7. **Handoffs relied on a cold-start brief plus a portable snapshot.** The owner explicitly requested the `HANDOFF.md` process at 00:06 on 10-28. The implemented transfer used `export.sh` and `import.sh`: Git bundles for program branches, a `refs.lock` mapping each repo/base/ref/tip, and text run records with a manifest. Import rebuilt repos and verified branch tips; a scratch import confirmed all 140 refs. The handoff brief told the new manager to resume interrupted rows from WIP branches and to treat the queue as the source of truth. [`data/user-messages.txt`; 10-28 00:06, 00:11–00:14; `handoff-upd/export.sh`; `handoff-upd/import.sh`; `handoff-upd/BRIEF-claude-manager.md`]

8. **Snapshot freshness was a recurring supervision problem.** At 05:58, a snapshot missed cleanup queue entries and work already landed; at 13:03 and 16:02, snapshots were stale since 10:44 and 14:17 respectively. The orchestrator then instructed the manager to export after each landing. Early handoff pushes were also blocked while the destination repo was public; after the owner made it private, export/push proceeded. [10-28 00:16–00:23, 05:58, 13:03, 16:02; `data/main-full.txt`; `out/w1-chunk-6.md`]

### What worked

- The runbook made the hourly check repeatable: inspect session, events, snapshot, queue, progress, tests, models, cost, and brief size. [`/home/user/repo/astrid-install/ORCHESTRATOR.md`]
- `send_message` could promptly restart idle work or narrow a slow, poorly targeted test loop. [10-28 00:36, 14:17]
- Tested export/import and cold-start instructions let work continue across manager sessions; the new manager resumed the queue from saved branches and records. [10-28 00:11–00:23; `handoff-upd/BRIEF-claude-manager.md`]
- Bounded test chunks made incomplete coverage explicit at closeout. [10-28 16:58, 20:56]

### What failed / friction

- The first Claude manager’s brief told it to stop and self-schedule, producing avoidable idle time until the owner intervened. [10-28 00:23–00:36]
- Hourly checks did not guarantee fresh saved state. Snapshot lag made progress harder to verify and delayed visibility of landed work. [10-28 05:58, 13:03, 16:02]
- Very large manager contexts and repeated log/diff reads raised cost and motivated manager resets. Output-hygiene rules had to be added after the problem appeared. [10-28 01:57–03:57]
- A public destination blocked the initial handoff snapshot; the owner had to change the repo visibility before the transfer completed. [10-28 00:16–00:23]
- **Inference:** check-in procedures evolved reactively. The owner had to diagnose the pacing bug, and snapshot freshness rules were tightened only after stale exports were found.

### Candidate principles

- When work is still startable, require back-to-back dispatch and reserve self-scheduled wake-ups for a real external wait, because the 20-minute `send_later` policy caused idling. [10-28 00:35–00:36]
- When checking a manager, compare session activity with the saved queue and snapshot, because session status alone did not reveal stale or unrecorded work. [10-28 05:58, 13:03; `ORCHESTRATOR.md`]
- When a manager is silent on a long test, switch to bounded chunks with timeouts and record unfinished tests explicitly, because R8’s full run went quiet and the final record had a known 1,021-test gap. [10-28 16:21, 16:58, 20:56]
- When replacing a manager, first save WIP and export refs plus run records; give the successor a narrow phase goal, queue authority, and exact resume point, because the handoff worked when branches, records, and a cold-start brief traveled together. [10-28 00:11–00:23, 02:52, 09:59]
- When a standing correction changes how work is run, update the brief/runbook as well as sending the message, because the pacing rule and later snapshot rules needed to persist beyond one intervention. [10-28 00:36; `data/plan-repo-gitlog.txt`]

### Structure implications

- **Manager record:** stable session ID, provider/model, phase, predecessor/successor, replacement reason, and archive status.
- **Check-in record:** timestamp; session status/rate limit; last activity; snapshot time; queue counts/states; last landing; active workers; test evidence; cost delta; intervention and observed result.
- **Automatic triggers:** nudge when startable work exists but no worker is active; flag stale snapshots; warn on no landing/activity over a configurable interval; prompt bounded test recovery when a run is silent.
- **Handoff checklist:** WIP committed; refs exported; manifest and run records current; import tip verification passed; brief names the current phase and resume rows; trigger points to successor session; old manager stopped/archived.
- **Cadence:** one hourly manager check-in with an optional deeper review interval; do not conflate manager self-wakes with orchestrator supervision. The observed self-wake was 20/60 minutes, not a 15-minute orchestrator loop.
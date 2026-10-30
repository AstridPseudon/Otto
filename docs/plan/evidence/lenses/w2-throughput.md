## Lens: Throughput, timing and idle time

**Observed** means the transcripts, commits, queues, or cost log record it. **Inferred** labels a likely cause or process implication. Times are UTC.

### Findings

1. **Throughput depended on the dispatch path actually working.** At the 10-26 22:57 kickoff, four tasks were assigned. By 23:32, all four had failed on their first worker command because nested workers could not run shell commands. That is roughly 35 minutes with no task execution. After an external dispatcher was added, the git log records at least seven task completions between 10-27 00:00 and 01:39: GATE-11, COH-C1, COH-C8a/b/c, COH-C9, and INS-C1. [data/plan-repo-gitlog.txt, 10-26 22:57–10-27 01:39; data/main-full.txt, 10-26 23:32–23:38]

2. **The first UPD work sprint was fast once the manager dispatched continuously.** The snapshot commits record eight named task landings or closures from 10-28 00:32 to 01:01, including AR1-X9, F1d, AR1-X8, two E1 UI subtasks, X2, and F1e. At 01:41 the queue showed 60 done, 3 running, 2 blocked, and 7 todo; the orchestrator estimated the main task list at about 85% by effort. [data/plan-repo-gitlog.txt, 10-28 00:32–01:01; data/main-full.txt, 10-28 01:41]

   That pace followed a clear correction: the manager had stopped after one task and scheduled its own wake-up. The owner said work should run “back to back”; the brief was changed at 00:36 to keep dispatching available work. [data/main-full.txt, 10-28 00:34–00:36; `mgr1-page-001.json`, 10-28 00:27–00:35]

3. **Review and cleanup produced a second concentrated burst.** Final review round 1 began at 02:57. By 04:53, seven blocking and one non-blocking fix had landed. Round 2 and 3 fixes were recorded by 05:44; 12 of 13 cleanup tasks were landed by 06:58. The cost log shows the final-phase manager at $17.90 by 03:57 and $22.46 by 06:58. [data/plan-repo-gitlog.txt, 10-28 02:57–06:31; `COST-LOG.md`, 10-28 03:57, 06:58; data/main-full.txt, 10-28 06:58]

4. **Long tests, then slow recovery from a silent run, dominated the UPD closeout.** Final testing started around 06:31 and the queue was marked complete at 09:53–09:58: about 3 hours 20 minutes elapsed. The 07:58 cost entry says two agent suites were each expected to take about 100 minutes and were running on the branch and base. At 08:58 the exported snapshot was still from 06:31, with no movement since 07:27; the check-in had to prompt log inspection and targeted reruns. The final run found 24 regression IDs and three test-fix tasks landed. [data/plan-repo-gitlog.txt, 10-28 06:31, 09:53–09:57; `COST-LOG.md`, 10-28 07:58, 09:57; data/main-full.txt, 10-28 07:58–09:53; `QUEUE-COMPLETE.md`]

5. **The rebase was the overall critical path.** It ran from plan approval and fresh manager startup at 09:59 to a completion snapshot at 20:22, around 10 hours 23 minutes. R1–R5 were merged by 10:20; R3, R6, and the R7b review followed by 10:44. The delay then accumulated in regression classification, fixes, and integration testing. The completion report records 1,021 agent tests as “not run (hung),” so completion meant a documented, bounded closeout, not full verification. [data/plan-repo-gitlog.txt, 10-28 09:59–20:22; `COST-LOG.md`, 10-28 10:58–20:38; `REBASE-COMPLETE.md`]

6. **A test-isolation investigation spent time on runs too broad to answer the question.** The manager used full-suite runs of about 70 minutes while bisecting R7-F1/F2. At 14:17, the orchestrator redirected it to direct isolation fixes. The cost log attributes about $2 of the preceding increase to Opus review and about $1 to Sonnet, but does not break out test compute cost. **Inference:** the larger loss was elapsed time and queue delay, not just model spend. [data/main-full.txt, 10-28 14:16–14:17; `COST-LOG.md`, 10-28 14:17]

7. **Container sleep and scheduling gaps repeatedly throttled work.** The 10-27 13:02 hourly loop was not present when checked at 14:56; uptime was zero and no scheduled jobs were listed. The owner chose check-in-only operation at 15:06, which the orchestrator estimated would run work for only 5–10 minutes per hour. At 16:05, “Nothing is running.” Separately, a tracked keep-alive was reported working from 16:07 onward. [data/main-full.txt, 10-27 13:02–16:07; `out/w1-chunk-4.md`]

8. **The manager’s live snapshot was not a reliable clock for progress.** The cost log reports snapshot staleness at 05:58 and again from 14:17 to 16:02. Those gaps caused check-in nudges, even when some work had landed. **Inference:** commit/snapshot cadence obscured actual throughput and made a slow test run look indistinguishable from an idle manager. [data/plan-repo-gitlog.txt, 10-28 05:58, 14:17, 16:02; `COST-LOG.md`]

9. **Owner instructions usually took effect quickly when the target was clear, but some operational fixes arrived late.** The back-to-back dispatch correction took effect around 00:36, about a minute after the 00:35 correction. The speed-up changes—overlapping independent tasks, raising the cap to four, and starting an early elegance pass—were applied 11 minutes after the 12:01 request. By contrast, the failed hourly-loop configuration was only discovered nearly two hours later. [data/main-full.txt, 10-28 00:35–00:36 and 10-27 12:01–12:12, 13:02–14:56]

### What worked

- **External dispatch restored execution** after the nested worker shell failed; completed tasks then appeared in the queue and snapshot commits. [data/main-full.txt, 10-26 23:32–10-27 01:39]
- **Back-to-back dispatch plus file-overlap limits** enabled useful parallelism without treating every task label as a separate lane. The manager was told to dispatch up to four independent workers and land finished work while others ran. [data/plan-repo-gitlog.txt, 10-28 00:36, 12:12]
- **Parallel final reviews and fixes** compressed review work: three review areas ran in parallel, followed by parallel fix work. [data/main-full.txt, 10-28 02:52–06:58; `COST-LOG.md`]
- **Bounded test chunks made a silent run closeable.** At 16:58, the manager was told to rerun in chunks with time limits and label unfinished tests “not run (hung),” rather than leave the run open indefinitely. [data/main-full.txt, 10-28 16:58; `REBASE-COMPLETE.md`]
- **A base-comparison rule improved triage.** The owner required checking only new failures; later the rebase brief was corrected so `origin/main` determined whether a failure was pre-existing. [data/main-full.txt, 10-28 01:52, 13:04; `REBASE-COMPLETE.md`]

### What failed / friction

- **Dispatch health was discovered reactively.** The first wave ran for about 35 minutes before anyone surfaced that all four workers had failed immediately. [data/main-full.txt, 10-26 22:57–23:32]
- **“Hourly check” was confused with “keep the work running.”** A scheduled check could report or restart a manager, but could not compensate for a sleeping container; the check-in-only mode explicitly left long intervals with almost no runtime. [data/main-full.txt, 10-27 14:56–16:05]
- **Idle, waiting, and testing were not distinct queue states.** The manager’s self-scheduled wake-up caused avoidable idleness; later silent tests and stale snapshots made the same symptom ambiguous. [data/main-full.txt, 10-28 00:34–00:36, 07:58–08:58, 16:58]
- **Broad test runs were used for a test-isolation defect.** About 70 minutes per full run delayed fixes that could be checked with a reproducing pair and then individual tests. [data/main-full.txt, 10-28 14:16–14:17]
- **Final test scope exceeded practical runtime.** The rebase ended with 1,021 tests explicitly unrun after chunks hit the 30-minute cap. [REBASE-COMPLETE.md]
- **Manager context growth was a large cost sink.** The first manager reached 263K context tokens and about $9 in the preceding hour; a fresh manager was started at phase boundaries. The final-phase manager later reached 281K context and was also replaced. [data/main-full.txt, 10-28 01:57, 03:57; `COST-LOG.md`]

### Candidate principles

- When a worker is dispatched, require an acknowledged start or first heartbeat within 2–5 minutes, because the first wave’s four failed launches went unnoticed for about 35 minutes. [10-26 22:57–23:32]
- When any independent task is ready, dispatch it immediately and keep the manager cycling, because the initial “send later” pacing left the manager idle despite queued work. [10-28 00:34–00:36]
- When a task waits on another worker, expose it as **waiting on worker** with that worker’s ID; when it waits on tests, expose the test run and expected finish time, because a stale snapshot otherwise makes both conditions look like a stall. [10-28 07:58–08:58; 16:02–16:58]
- When a test run exceeds its expected duration, send a liveness check first; if it is silent, restart it in bounded chunks and record timed-out IDs, because the final rebase left 1,021 tests unrun and needed hours of follow-up. [10-28 16:21–20:22; REBASE-COMPLETE.md]
- When testing regressions, first compare the smallest reproducing test and its base result; only run the full suite after targeted fixes, because two ~70-minute full runs were used on isolation bugs. [10-28 14:16–14:17]
- When context approaches a phase threshold, snapshot queue, decisions, and test status and start a fresh manager, because context reached 263K–281K and repeatedly drove handoffs. [10-28 01:57–03:57]

### Structure implications

- **Task state fields:** `ready`, `running`, `waiting_on_worker`, `waiting_on_test`, `waiting_on_owner`, `blocked`, `done`; require a `waiting_on` entity and last-progress timestamp.
- **Dispatch handshake:** record dispatch time, worker/session ID, first heartbeat time, and first output; alert after a short no-start window.
- **Test-run entity:** suite, branch/base, start time, expected duration, heartbeat, timeout, completed IDs, hung IDs, and whether a full suite is permitted.
- **Queue cadence:** manager continues through available work until all open tasks are explicitly waiting; check-ins read state but do not serve as the execution loop.
- **Stall trigger:** alert when there is no heartbeat or state change beyond the task’s expected interval; classify expected long test vs silent worker vs waiting for owner before escalating.
- **Snapshot rule:** push a lightweight snapshot after each landing and at a fixed interval while long tests run; include `last_progress_at`, `next_expected_event`, and `snapshot_at`.
- **Parallelism fields:** worker cap plus file ownership/touch set; increase parallelism only where task touch sets do not overlap, and reserve capacity for review/fix tasks.
- **Phase handoff checklist:** reconcile all task IDs, unresolved tests, decisions, owner waits, current branches, and context/cost before archiving a manager.

### Evidence limits

- Task landings per hour above come from named task/snapshot events in the git log and queues; they are not a complete count of every worker edit or commit.
- Wall-time figures are elapsed intervals between recorded events; they include tests, manager time, infrastructure delays, and reporting latency where the sources do not separate them.
## Lens: Failure modes and anti-patterns (red team)

### Findings

1. **Stale source snapshots produced wrong plans and repeated revalidation.**  
   **Observed:** The first installer audit relied on a snapshot 127 commits behind main; the orchestrator retracted its PATH and skills claims after checking current source. Later, the Windows task-host branch was already on main, and the rebase plan still contradicted approved rulings until the owner challenged it. (10-26 00:57–01:14; 10-26 09:43, 19:26; 10-28 10:19; `data/main-full.txt`; `out/w1-chunk-1.md`, `out/w1-chunk-2.md`, `out/w1-chunk-7.md`)  
   **Inference — root cause:** Plans and snapshots had no hard freshness check tied to the exact base they described.  
   **Earliest signal:** At the first audit, before assessing behavior: the source snapshot was already 127 commits behind.  
   **Preventive rule:** Before analysis or assignment, record each repo’s commit SHA and reject evidence older than the agreed base. Require the plan to name that base.

2. **The orchestrator crossed into execution and reviewer roles, then needed owner corrections.**  
   **Observed:** On 10-27 the owner said, “No more digging into diffs myself” and asked the orchestrator to keep work moving through the manager. On 10-28 the owner corrected Opus use after it had been assigned implementation and mid-project design; a later operating rule says the orchestrator should not implement, review diffs, run tests, or land tasks. (10-27 01:01; 10-28 00:38–01:40, 02:08; `data/main-full.txt`; `out/w1-chunk-3.md`, `out/w1-chunk-6.md`; `/home/user/repo/astrid-install/ORCHESTRATOR.md`)  
   **Inference — root cause:** Role boundaries were captured in documents after work began, rather than enforced at task assignment. Model choice also drifted as policy changed.  
   **Earliest signal:** The initial installer handoff already gave Opus advisory and review roles, but the later manager phase used it for implementation/design.  
   **Preventive rule:** Every assignment gets a role and allowed actions; reject implementation work routed to a reviewer or orchestrator.

3. **Manager throughput was gated by turn scheduling and review, not worker capacity.**  
   **Observed:** At one check-in, seven completed worker runs were waiting for the manager while only one worker was busy. Earlier, first-wave tasks had all failed on their first command and were discovered roughly 35 minutes after kickoff. Later, hourly-only operation let the container sleep, interrupting a large task four times; the owner repeatedly asked whether work was progressing. (10-26 22:57–23:38; 10-27 15:59–16:07, 17:58–17:59; `data/main-full.txt`; `out/w1-chunk-3.md`, `out/w1-chunk-5.md`)  
   **Inference — root cause:** The workflow had no fast health signal for failed dispatch, completed-worker backlog, or an idle manager with startable work. Adding more worker slots did not solve manager-side queuing.  
   **Earliest signal:** The first wave’s immediate command failures; later, finished runs accumulated faster than the manager processed them.  
   **Preventive rule:** Alert on dispatch failure, idle manager plus ready work, and completed results awaiting review; require the manager to drain completed workers before dispatching more.

4. **A faulty failure-classification rule hid regressions until a costly rerun.**  
   **Observed:** The initial rule treated failures also seen on the updater branch as pre-existing. The orchestrator changed it to “origin/main decides,” then reported that 82 of 87 failures also failed on main, 10 passed on main, and 5 were environmental. Separately, two new Pinokio switch tests were initially called pre-existing because they failed on the updater branch. (10-28 13:04, 14:17, 15:27; `data/main-full.txt`; `out/w1-chunk-7.md`)  
   **Caveat:** The 82 + 10 + 5 figures total 97 for 87 IDs; the transcript does not reconcile overlap or counting. Do not treat those figures as a complete partition.  
   **Inference — root cause:** The baseline was chosen for convenience instead of matching the question “did this rebase introduce a failure?”  
   **Earliest signal:** The queue’s three-way classification used the old branch as evidence of pre-existence before comparison with `origin/main`.  
   **Preventive rule:** Define the base branch as the sole pre-existing-failure baseline before testing; require a recorded result on that base for every failure classification.

5. **Full-suite runs were used to debug narrow test-isolation failures.**  
   **Observed:** The manager bisected order-dependent tests with full runs of about 70 minutes each. The orchestrator stopped this and asked for pair/file-level checks, with one full rerun at the end. The final closeout still recorded 1,021 agent tests as not run because of hangs; manager cost reached $13.84 for the rebase session. (10-28 14:16–14:17, 20:56; `data/main-full.txt`; `out/w1-chunk-7.md`, `out/w1-chunk-8.md`; `/home/user/repo/astrid-install/COST-LOG.md`)  
   **Inference — root cause:** The plan lacked a required test-isolation debugging strategy and time bounds before the expensive suite started.  
   **Earliest signal:** The failures passed individually and only failed in ordered suites.  
   **Preventive rule:** For order-dependent failures, reproduce with the smallest pair or file, fix isolation there, then run one full suite; time-limit chunks and report hung tests as unrun.

6. **Large manager context became a direct cost driver.**  
   **Observed:** The cost log records a $9.03 increase in an hour, with manager context at 263K tokens and 60.6M cached tokens; the next phase reached 281K. A later digest reported about $59 across three manager sessions since handoff. (10-28 01:57–03:57; `data/main-full.txt`; `/home/user/repo/astrid-install/COST-LOG.md`)  
   **Inference — root cause:** Managers repeatedly reread accumulated context instead of relying on compact task state and summaries.  
   **Earliest signal:** The 263K-context/$9.03-hour entry.  
   **Preventive rule:** Give each manager a bounded brief and a compact state file; roll over at phase boundaries and keep logs, test output, and full reports out of the active prompt.

7. **The planning/review cycle repeatedly expanded work before cutting it.**  
   **Observed:** The cross-platform test plan went from 24 tasks to 17 after Astra review and owner-directed judgment calls. The CI/pack proposal briefly included a four-worker audit sweep; it was removed in the later review because mandatory checks already covered the relevant packs. The revision history shows repeated plan/brief changes. (10-27 21:08–21:45; 10-28 16:48–17:10; `data/main-full.txt`; `out/w1-chunk-5.md`, `out/w1-chunk-8.md`; `data/plan-repo-gitlog.txt`; final `/home/user/repo/astrid-install/MANAGER-CODEX.md`)  
   **Inference — root cause:** Initial plans optimized for completeness before they had an explicit “minimum sufficient” pass.  
   **Earliest signal:** The 24-task TST plan was presented before its requested simplicity review.  
   **Preventive rule:** Before queueing, state the minimum outcome and remove work that does not enforce a named failure mode or release requirement.

8. **Snapshot lag weakened oversight and caused avoidable owner attention.**  
   **Observed:** The rebase snapshot was stale from 10:44 until the 13:03 check, and again from 14:17 until 16:02; the orchestrator said it could not see which tests or review findings the manager had. On 10-27 the owner asked about status or progress six times between 15:12 and 20:36. (10-28 13:03, 16:02; 10-27 15:12–20:36; `data/main-full.txt`, `data/user-messages.txt`; `/home/user/repo/astrid-install/COST-LOG.md`)  
   **Inference — root cause:** The manager’s snapshot cadence was aspirational, not an enforced condition of work.  
   **Earliest signal:** A two-hour gap between snapshots despite hourly oversight.  
   **Preventive rule:** Publish a small status snapshot after each landed task or at a fixed short interval; escalate when stale, and include “last landed,” “current blocker,” and “next action.”

### What worked

- Independent reviews found concrete issues and sometimes led to real cuts: Astra’s over-engineering review removed the audit sweep and reduced the scope of the TST close; deeper review caught a task marked ready despite a blocker. (10-27 21:27–21:45; 10-27 01:06; 10-28 17:05–17:11; `out/w1-chunk-3.md`, `out/w1-chunk-5.md`, `out/w1-chunk-8.md`)
- Correcting the test baseline caught genuine regression candidates and a Runtime file-handle leak. (10-28 13:04–14:17; `data/main-full.txt`)
- Bounded test chunks and explicit “not run (hung)” reporting made the final gap visible rather than silently treating the suite as complete. (10-28 16:58, 20:56; `out/w1-chunk-8.md`)
- The “finished workers first” correction directly addressed the observed manager backlog. (10-27 17:58–17:59; `data/main-full.txt`)

### What failed / friction

- Owner attention was repeatedly spent correcting role assignment, checking progress, reconciling stale plans, and clarifying whether a deliverable was a full package or a delta. (10-26 01:23; 10-27 15:12–20:36; 10-28 10:19, 16:55–16:57; `data/user-messages.txt`)
- Several process rules changed midstream: model tiers, Opus’s role, review cadence, and which phase ran next. Some changes responded to evidence, but the handoff did not consistently distinguish current rules from superseded ones. (`data/plan-repo-gitlog.txt`; `/home/user/repo/astrid-install/ORCHESTRATOR.md`, `/home/user/repo/astrid-install/MANAGER-CODEX.md`)
- Some overhead had no demonstrated execution payoff: the four-worker audit sweep was cut before execution; the 24-task TST draft had to be reduced before it was queued. The time spent drafting/revising is not quantified. (10-27 21:08–21:45; 10-28 16:48–17:10; `data/main-full.txt`)
- Hourly review was eventually turned off at the owner’s request; a cadence rule without a clear end condition became a manual cleanup task. (10-28 18:09–18:24; `data/main-full.txt`)
- **Inference:** Three rounds of Astra review, an elegance pass, and periodic deep checks risked overlapping review scope. The logs show some deep checks being skipped after three Opus reviews, but do not establish that all review spend lacked value. (10-28 05:58; `COST-LOG.md`)

### Candidate principles

- When analyzing a repo, pin the source SHA first, because the 127-commit-stale snapshot caused a wrong audit. (10-26 01:14)
- When a worker fails, compare against the actual rebase base before calling it pre-existing, because “also fails on updater” hid regression candidates. (10-28 13:04–15:27)
- When a test failure is order-dependent, isolate it with the smallest reproducing set before running the full suite, because full runs took about 70 minutes. (10-28 14:17)
- When an orchestrator role is “guide,” route implementation, diff review, and test execution to the manager, because the owner had to restate that boundary. (10-27 01:01; 10-28 02:08)
- When a manager has completed workers waiting, process their results before dispatching more, because seven completed runs accumulated behind one manager. (10-27 17:58–17:59)
- When a manager’s context or spend spikes, roll over to a fresh session with a compact handoff, because context reached 263–281K and spend rose sharply. (10-28 01:57–03:57)
- When a plan is still unqueued, do a complexity pass before presenting it as a proposed task inventory, because the TST plan was cut from 24 to 17 tasks. (10-27 21:27–21:45)

### Structure implications

- **Repo snapshot entity:** repo, commit SHA, captured-at time, and stale threshold; block assignment when evidence is out of date.
- **Task/worker state:** queued, dispatched, failed-to-start, running, result-ready, reviewed, landed; alert on idle manager with startable work and on result backlog.
- **Test classification record:** test ID, exact baseline SHA, baseline result, candidate result, environment label, and evidence link; require baseline evidence before “pre-existing.”
- **Test-run controls:** chunk, per-test timeout, wall-clock cap, reproduction set, last test name, and explicit not-run/hung status.
- **Manager budget field:** context size, spend since last check, brief size, and rollover trigger.
- **Decision/version field:** current rule, supersedes, owner approval, date, and affected task IDs; prevent stale handoffs from presenting old policy as current.
- **Review gate checklist:** named failure mode each review covers, finding-to-fix mapping, round cap, and a stop criterion.
- **Cadence trigger:** owner, active phase, end condition, and last successful snapshot; automatically disable or revise when the owner changes the next-phase plan.
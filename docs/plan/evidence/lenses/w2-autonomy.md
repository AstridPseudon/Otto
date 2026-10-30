## Lens: Autonomy while the owner was away

### Findings

1. **The owner gave a clear overnight delegation, and the orchestrator recorded it as a bounded operating rule.** At [10-28 02:08], the owner said, “No more questions. I’m going to bed. You have to figure out everything.” The orchestrator promised hourly checks, manager rulings, a morning digest, and to leave larger structural issues for the owner. It recorded “no questions to the owner” in [ORCHESTRATOR.md](/home/user/repo/astrid-install/ORCHESTRATOR.md).  
   **Observed:** this meant deciding within the project’s existing scope, not taking over paused work or making release decisions.

2. **During the night, work continued and at least one manager escalation was resolved without waking the owner.** At 03:10 the orchestrator chose the manager’s recommended fix for FR1-N4: keep the App pinned to the shipped Runtime, read the new `release` field defensively, and document release-time pin work. It assigned the fix and tests to the manager. The decision is summarized in [DIGEST-2026-10-28.md](/home/user/repo/astrid-install/DIGEST-2026-10-28.md) and visible in the transcript at [10-28 03:10].  
   **Observed:** the choice preserved compatibility and stayed within the already stated “no pin change” boundary. The digest lists 11 larger issues as recommendations for the owner rather than actions taken overnight.

3. **Hourly checks provided oversight, but they did not guarantee fresh or complete evidence.** The manager completed three review rounds, the elegance pass, and final testing work overnight; manager costs were recorded at 02:57, 03:57, 04:54, 05:58, 06:58, 07:58, and 09:57 in [COST-LOG.md](/home/user/repo/astrid-install/COST-LOG.md). At 05:58 the snapshot lacked cleanup work and some landed tasks had not been pushed, so the orchestrator told the manager to record changes and push after each merge [10-28 05:58]. At 08:58, no snapshot progress had arrived since 07:27; the orchestrator asked the manager to check the long-running tests [10-28 08:58].

4. **The morning digest was useful, but its first version misstated test status.** At 08:59, the orchestrator sent a digest covering project status, overnight decisions, costs, and 11 bigger issues [10-28 08:59; `DIGEST-2026-10-28.md`]. A minute later it corrected the digest: 10 Runtime tests failed on the updater branch but passed at the starting point, so they were regressions requiring a fix [10-28 09:00].  
   **Inference:** a digest built from a stale snapshot or while tests are still resolving needs an explicit “as of” time and confidence/status labels, plus a final freshness check before delivery.

5. **The owner’s return brought scrutiny back to documentation and operating choices.** The next recorded owner message was at 10:19: “Does that all make sense? And is it all clear and coherent” about the rebase plan and testing strategy. Later messages clarified model tiers and decisions [10-28 10:31–10:51]. At 10:59, the owner explicitly authorized public CI use and said, “Please don’t take any blockers. Keep pushing.” [10-28 10:59].  
   **Observed:** the transcript shows no explicit acknowledgment or praise of the digest itself. The first return message instead asks for a coherent, documented plan.

6. **Unattended execution was strongest for reversible, in-scope decisions; owner input mattered for policy and scope.** The overnight FR1-N4 ruling and deferral of bigger issues fit the announced delegation. In attended periods, the owner corrected role assignments, clarified delivery and scope, and supplied permissions—for example, zip delivery at [10-26 01:52], clarifying the manager’s remit at [10-27 02:46–02:52], and specifying rebase rules at [10-28 10:19].  
   **Inference:** autonomous execution can preserve momentum, but it cannot safely infer new product policy or broaden authorization from “figure it out.”

7. **Other absences exposed a continuity problem more than a decision problem.** On 27 Oct, the owner expected hourly oversight, but the loop missed a check-in; by 16:05 the orchestrator found nothing running and restarted work [10-27 13:02–16:06; `out/w1-chunk-4.md`]. Earlier, the 26 Oct thread resumes after a long gap with a new owner instruction at 09:42 [10-26 02:05–09:42; `out/w1-chunk-2.md`].  
   **Inference:** “owner away” and “program operating unattended” are distinct states. A platform must report whether workers are alive, snapshots are current, and scheduled checks actually fired.

### What worked

- The owner’s no-questions instruction became a written rule, and the orchestrator maintained hourly checks and a morning reporting commitment [10-28 02:08; `ORCHESTRATOR.md`].
- The orchestrator handled a concrete technical escalation without pausing the manager or waking the owner, and recorded a release-time note instead of changing pins [10-28 03:10].
- The digest included decisions, cost, larger issues, and recommendations; the incomplete test result was corrected promptly [10-28 08:59–09:00].
- The orchestrator deferred structural/product choices for owner review instead of turning the overnight mandate into blanket authority [10-28 02:08; `DIGEST-2026-10-28.md`].

### What failed / friction

- A manager snapshot was stale and omitted landed work; the orchestrator had to impose a more frequent save/push cadence [10-28 05:58].
- The morning digest’s initial test status was wrong, despite the digest being a key return handoff [10-28 08:59–09:00].
- Hourly oversight sometimes failed operationally: the owner noticed a two-hour gap on 27 Oct, and later the orchestrator found no workers running [10-27 14:56–16:06; `out/w1-chunk-4.md`].
- The attended return still required the owner to check whether the rebase plan and test strategy were coherent [10-28 10:19]. The record does not establish whether the owner had read or accepted the digest before that question.

### Candidate principles

- **When the owner says “no questions,” decide only within the current approved scope and record each meaningful ruling, because the overnight mandate authorized judgment but did not erase project boundaries** [10-28 02:08; `ORCHESTRATOR.md`].
- **When a decision changes product behavior, release policy, scope, or an external commitment, defer it for the owner unless an earlier instruction explicitly covers it, because larger issues were deliberately held for the morning** [10-28 02:08; `DIGEST-2026-10-28.md`].
- **When evidence is stale, incomplete, or still running, label it as provisional and include its timestamp; refresh before sending the digest, because the 08:59 test status needed correction at 09:00** [10-28 08:58–09:00].
- **When an unattended action touches a repository, use only the exact destination and branch already authorized; if a permission layer blocks it, report the block and continue independent work, because authorization changed over time and the runbook forbids bypassing refusals** [`ORCHESTRATOR.md`; 10-28 10:59; 10-28 15:53].
- **When a task would pin, deploy, touch Railway, or access secrets, stop for explicit authorization, because those are written hard limits in the runbook** [`ORCHESTRATOR.md`].
- **When work runs unattended, record cumulative spend and change by interval; stop or seek approval at a configured budget threshold, because overnight manager spend reached about $59 and no hard spend cap is evident in the records** [`COST-LOG.md`; `DIGEST-2026-10-28.md`].
- **When a manager is active, require durable snapshots after landings and an hourly liveness check, because the 05:58 snapshot was stale and the prior hourly loop sometimes failed** [10-28 05:58; 10-27 14:56–16:06].

### Structure implications

- **Autonomy record:** per program, store the owner’s absence window, allowed decision classes, forbidden actions, escalation criteria, and the return time or digest trigger.
- **Decision log:** each unattended ruling should capture timestamp, question, options considered, choice, rationale, supporting evidence, reversibility, affected tasks, cost, and whether owner review is needed.
- **Authorization registry:** list repository, branch, action type, expiry, and source of authorization. Require an exact match for pushes; separately mark deploy, pin, and secret permissions.
- **Liveness and checkpoint fields:** manager heartbeat, latest snapshot timestamp, last landing, running worker count, next scheduled check, and overdue alert.
- **Spend control:** record cumulative and interval spend against a configured limit; define who can approve exceeding it.
- **Morning digest trigger and checklist:** send after the first completed post-09:00 check; include what landed, decisions made, evidence and confidence, cost, unfinished or failed tests, stale snapshots, owner decisions needed, and next action. Confirm the snapshot is current and test statuses are final or clearly marked provisional before delivery.
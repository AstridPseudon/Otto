## Lens: Model tiering, difficulty and cost

### Findings

1. **The tier labels changed as the available worker pool changed.** Early task lists used Normal → Codex Luna and X-hard → Codex Sol, with Astra for reviews [10-26 01:40; 10-26 22:32–22:36]. On 10-27, the owner split X-hard into Hard → Terra and Super-hard → Sol 6.1 [10-27 20:54–20:55]. When work moved to a Claude Haiku manager, the mapping became Normal → Haiku, Hard → Haiku at xhigh with a Sonnet retry after one failure, and Super-hard → Sonnet [10-28 00:37–00:39; 02:05–02:08]. The owner later asked to return workers to Codex’s Luna/Terra/Sol tiers when available [10-28 10:31]. **Observed:** the tier names stayed familiar, but the model mapping depended on the execution environment.

2. **Opus drifted beyond the owner’s intended role and needed repeated correction.** The owner first asked why Opus was doing “normal work” [10-28 01:29]. The orchestrator acknowledged assigning it implementation, then briefly limited it to design and review before the owner clarified that it was for final reviews and the elegance pass [10-28 01:29–01:40]. The resulting brief reserved Opus for those end-stage tasks and barred it from implementation [10-28 01:39; `handoff-upd/BRIEF-claude-manager.md`]. **Observed:** the restriction became written policy after the assignment had already caused unchecked Opus code to require review.

3. **Some apparent difficulty was actually a dispatch or verification problem.** The first four Codex tasks escalated because nested workers could not run their first shell command; no product work had happened. A dispatcher was added, after which workers ran normally [10-26 23:32–23:38]. Later, R7-F1 and R7-F2 were investigated with repeated full test runs of about 70 minutes each; the orchestrator redirected the manager to targeted isolation checks [10-28 14:16–14:17]. One of those “test” problems, R7-F2, proved to be a real file-handle leak in `_materialize_export` [10-28 14:17–15:00]. **Inference:** difficulty labels alone could not distinguish a hard code change from a broken worker path or an inefficient test approach.

4. **Review outcomes exposed both over- and under-estimation.** C2 went through four Astra rounds, each finding more edge cases; the process was then capped at three fix rounds [10-27 10:00; `data/main-full.txt`, 4423]. Conversely, R8-F1 was escalated as a Super-hard Sonnet product fix, but the investigation found the product refusal was correct and the test fixture was incomplete [10-28 15:28–16:04]. R7-F2 went the other way: initially grouped with test-isolation failures, it revealed a real runtime bug [10-28 14:17]. **Inference:** tier estimates were most unreliable when the root cause or test validity was not yet established.

5. **The owner’s one-failure Sonnet fallback is clear as a rule, but not shown as a systematically measured policy.** The brief records Hard → Haiku xhigh, then Sonnet after one failure [10-28 02:07; `handoff-upd/BRIEF-claude-manager.md`]. The available records do not show a per-task comparison of fallback rate, time saved, or quality by tier. Codex availability also varied: the orchestrator could test Codex locally, but asked whether the remote manager could run it [10-28 10:31–10:32]. The Codex dispatcher workaround itself addressed nested shell access, not task difficulty [10-26 23:32–23:38].

6. **The cost log tracks session totals and milestones, not cost per task or tier.** [COST-LOG.md](/home/user/repo/astrid-install/COST-LOG.md) records manager endpoints of $16.05, $19.62, and $27.28 across the earlier sessions, and $13.84 for the rebase manager at closeout [10-28 02:52; 04:54; 09:59; 20:38]. Those endpoints sum to about **$76.80**, but should be read as recorded session totals, not a precise program invoice. An earlier closeout estimated about $66 through the first phases, and a later summary reported the rebase at about $10.92 before it finished [10-28 08:59; 17:09]. The log also identifies manager context growth as a major cost driver: 263K tokens at 01:57, with 60.6M cache-read tokens reported; a fresh session was started at phase boundaries [10-28 01:57–02:52]. One known review cost was $2.02 for Opus; the log does not generally break down costs by task or model [10-28 14:17].

### What worked

- The owner’s eventual two-stage rule put a cheaper first attempt on Hard tasks while preserving a stronger fallback: Haiku xhigh, then Sonnet after one failure [10-28 02:07–02:08].
- The three-tier Codex mapping made the distinction between ordinary, hard, and especially hard work explicit [10-27 20:54–20:55].
- Opus reviews found useful simplifications and produced bounded fix work; reviews were later capped after C2’s repeated rounds [10-27 10:00; 12:11–12:21].
- Fresh manager sessions reduced accumulated context at phase boundaries, while the cost log made large jumps visible [10-28 01:57–02:52; COST-LOG.md].

### What failed / friction

- The manager’s Opus assignments conflicted with owner intent, producing repeated corrections and a need to inspect work committed before the restriction [10-28 01:29–01:40].
- Initial Codex worker failures were counted as task escalations despite being caused by nested sandbox dispatch, not task complexity [10-26 23:32–23:38].
- The Sonnet escalation for R8-F1 overestimated a fixture defect as product difficulty; the R7-F2 “test isolation” framing underestimated a real product defect [10-28 14:17; 15:28–16:04].
- Long full-suite runs were used where targeted checks would have answered the question faster [10-28 14:16–14:17].
- Cost figures were logged cumulatively by session, but not attributed to individual tasks, retries, or review rounds, limiting their use for future tier calibration [COST-LOG.md].

### Candidate principles

- **When the root cause is unknown, start with a diagnosis task at Normal or Hard and classify the implementation separately, because R8-F1’s apparent product bug was a fixture defect while R7-F2 concealed a real bug [10-28 14:17; 15:28–16:04].**
- **When a worker fails before inspecting or changing the code, classify it as a dispatch/environment failure, not a task escalation, because all four initial escalations came from a broken nested-worker shell path [10-26 23:32–23:38].**
- **When a Hard task fails once under Haiku xhigh, retry it on Sonnet with the failure evidence attached; keep Super-hard tasks on Sonnet, because this was the owner’s selected cost/strength trade-off [10-28 02:07–02:08].**
- **When a test failure may depend on ordering or shared state, require a focused reproducer before expensive full-suite runs, because two 70-minute runs were spent before the manager was redirected to isolation checks [10-28 14:16–14:17].**
- **When assigning Opus, require a review/design deliverable and prohibit implementation, because the manager assigned Opus code work contrary to the owner’s stated role [10-28 01:29–01:40].**

### Structure implications

- **Task fields:** `difficulty_score`, `score_factors`, `root_cause_known` (yes/no), `verification_cost` (focused/full/long-running), `model_tier`, and `tier_rationale`.
- **Simple scoring proposal:** add one point each for (a) multiple repositories or shared interfaces, (b) lifecycle/stateful behavior such as stop, rollback, repair, or update, (c) concurrency, ordering, or environment-sensitive tests, and (d) an uncertain root cause or missing reproducer. Score **0–1 = Normal; 2–3 = Hard; 4 = Super-hard**. Mark security, data-loss, or unprovable-stop changes Super-hard regardless of score. **Inference:** these factors match the observed spread from the Normal `music.duck`/message fix to the cross-component stop and rollback work [10-28 16:42; FIX-W1..W6 summary in `data/main-full.txt`, 8650–8658].
- **Escalation trigger:** after the first failed Hard attempt, attach the failure summary and verification evidence to the Sonnet retry; count dispatch errors separately from implementation failures [10-28 02:07; 10-26 23:32–23:38].
- **Model policy field:** store both abstract tier and actual backend/model (e.g. `Hard`, `Haiku xhigh`) so a Codex/Claude handoff does not silently change what the tier means [10-28 00:37–00:39; 10-28 10:31].
- **Cost cadence:** keep hourly manager totals, but add per-task model, retries, and cost delta at completion; flag context size for reset at phase boundaries, since the current log exposes session and context costs but not per-task economics [COST-LOG.md; 10-28 01:57–02:52].
> **HISTORY. This is not a current requirement.** This document is the retrospective of the Astrid build programme (27–28 Oct). The current documents start at `START-HERE.md`.

# What happened and what worked

The full scorecard (28 events) and the Luna draft this is edited from are in `evidence/drafts/w3-retro.md`. The critic's corrections are applied here.

## The program, 26–28 Oct

| Phase | What happened | Agents | Cost (recorded) |
|---|---|---|---|
| **26 Oct night: explore and plan** | Windows installer complaint → Haiku probes, Astra/Opus reviews → plan. The source snapshot was 127 commits stale, and current `main` reversed two conclusions. | Orchestrator, Haiku probes, Astra, Opus | Not recorded |
| **26 Oct eve – 27 Oct early: release-safety and installer program** | Codex manager; the first 4 workers failed silently for ~35 min (nested sandbox), fixed with the file-based dispatcher. Containers slept and workers were lost; keepalive and recovery scripts were added. | Codex manager; Luna/Sol, Astra | Not isolated |
| **27 Oct: pivot to the updater (UPD)** | The owner paused the program and started UPD. Tiers split into Normal/Hard/Super-hard. The hourly loop went missing for ~2 hours, and the owner found nothing running. 7 finished workers waited for one manager. TST was planned (22 Luna explorations → 24 tasks → Astra → 17) but left unqueued. | Codex manager; Luna/Terra/Sol; Astra; Opus elegance pass | Not isolated; the Codex usage limit forced a handoff |
| **28 Oct 00:00–10:00: finish UPD** | A Haiku manager took over (cold-start-tested export/import, 140 refs). The owner fixed the pacing ("back to back") and the model policy (Opus only for the end reviews). 3 review rounds (7 blocking found and fixed) + an elegance pass (12 cleanups). The final test run found regressions, which were fixed. | 3 Claude managers in turn; Haiku/Sonnet workers; Opus reviews | $16.05 + $19.62 + $26.24. **About $35 of that was spent in the two hours that ran the Opus review rounds, fixes included** |
| **28 Oct 10:00–20:40: rebase onto `main`** | One merge per repo, no repins. The baseline was corrected to `origin/main`; full-suite bisects (2 × 70 min) were redirected to isolation, which found a real fd leak. 1,021 agent tests hung and were recorded as not run. GitHub Actions jobs stayed queued. Handover packs were sent; Windows tester logs were investigated and specced. | Rebase manager (Haiku), Sonnet fixes, one Opus coherence review ($2) | $13.84 |

**End state:**
- The updater is **built and integrated, but not fully verified**: 1,021 tests not run, and Windows, macOS and CI written but not run.
- The release-safety and installer program is paused.
- TST is planned but not queued; the Windows fixes are specced.
- All of it is packaged for the owner.

**Recorded manager spend:** about $76. The orchestrator's own spend and the Codex phases weren't logged.

## What worked (ranked by impact)

1. **One queue per project as the manager's source of truth,** with tiers, dependencies and a Done when per row. A 62-row project closed through three manager changes without losing state.
2. **Owner-set role separation, once enforced:**
   - orchestrator = guide;
   - manager = executor;
   - Opus = end reviews only;
   - workers by tier.

   Once enforced, the owner stopped having to correct roles and models.
3. **Back-to-back dispatch.** Eight tasks landed in the half hour after the 00:35 correction. That's timing, not a measured effect.
4. **Cheap fan-out exploration, then a strong planner, then an over-engineering critic, then orchestrator judgement.** Plans got smaller and safer at the same time. Release safety gained a hotfix path and a safety floor; TST lost an audit swarm and a matrix explosion.
5. **Tested handoffs:** bundles plus `refs.lock` plus a cold-start brief. A provider switch (Codex → Claude) and three manager rotations cost minutes, not hours.
6. **Fixed evidence vocabulary:**
   - "the base decides";
   - "written, not run";
   - release-pending;
   - not run (hung).

   It caught real regressions and an fd leak, and kept the final report honest.
7. **Specific, timely interventions at hourly checks:**
   - stop idling (00:36);
   - reconcile the plan with the rulings (10:19);
   - stop full-suite bisects (14:17);
   - bound the hung run (16:58).
8. **Bounded end reviews with a bigger-issues list.** 7 blocking fixes and 12 cleanups landed; structural items went to the owner instead of being silently changed.
9. **The file-based dispatcher.** It turned an unusable worker path (sandboxed managers can't run git or start workers) into a working one, the same evening.
10. **Fast, reasoned rulings on escalations:**
    - "build the route, it's in scope";
    - "pin stays put";
    - "stop patching piecemeal";
    - test-only fixes accepted only if no assertion changes.

## What went badly (ranked by cost to the owner)

1. **The owner had to ask whether work was alive, about 20 times.** No live status combined manager, worker and test liveness with the next action.
2. **Policy drifted at handoffs, and the owner had to correct it:** the orchestrator doing hands-on work, Opus implementing, self-scheduled pacing. The fix is one policy block rendered into every brief.
3. **Infrastructure ate the first evening:** nested-sandbox dispatch, false "lost" workers, sleeping containers, a missing hourly trigger, classifier blocks on pushes. A platform should own all of it.
4. **Stale inputs:** the 127-commit-old snapshot, snapshots older than the last landing (three times), a rebase plan contradicting its rulings.
5. **The wrong test baseline,** then **expensive debugging:** "fails on the old branch" counted as pre-existing; 2 × 70-minute full runs to bisect; a silent hour-long hung run.
6. **Long manager contexts (263K–281K) coincided with the steepest non-review spend.** Repeated reads were the likely contributor; this wasn't isolated.
7. **Plans grew before they shrank** (24 → 17, the audit swarm, ~850 lines cut in the elegance pass), costing review and writing time.
8. **Package churn at the end.** Six handover zips in about four and a half hours, one sent before tests finished; the owner had to clarify that they wanted a delta for an existing manager.
9. **CI never ran.** Pushes succeeded; jobs sat queued (an account or repo hold). Hours of "is CI running?" when push, queue and run should have been separate states from the start.
10. **One change was applied without recorded approval** (the 27 Oct speed-up). It was harmless, but the difference between proposal, ruling and approval was invisible.

## What the owner consistently wanted
1. **The manager does the work; the orchestrator guides, checks and decides.** No product work by the orchestrator.
2. **Keep moving.** Back to back; no pauses while work is startable; "don't take any blockers, keep pushing".
3. **Cheap models by default, strong models by difficulty, Opus sparingly for taste and end review.** "Without resulting in more tasks."
4. **Don't over-engineer.** Ask for an over-engineering review, then apply judgement rather than every cut.
5. **Elegant and coherent:** one way to do each thing, not patch layers.
6. **Only new failures count,** compared with the right base.
7. **Honest gaps are fine;** fake passes aren't. "I'm happy to accept those gaps."
8. **Autonomy while away,** with the big calls saved for them. "No more questions… figure out everything."
9. **Concrete status:** what's running, what's done, what's needed from them.
10. **Deliverables they can act on:** zips, paste-ready messages, a decision list with recommendations.
11. **The boundaries they set are held:** plan versus queue, investigate versus fix, update the pack versus execute.

## Surprises that held up
- **More workers ≠ more throughput.** The manager's landing step was the bottleneck.
- **Simplicity and safety weren't opposed.** The same reviewers added a missing safety check and removed duplicate machinery.
- **Test failures were often test defects** (R8-F1/F2/F3 were fixtures), but not always: R7-F2 was a real leak. Diagnose before tiering.
- **The durable part was the ownership and evidence model, not the tools.** Providers, models and scripts changed mid-program; queue, briefs, rulings and evidence rules carried over unchanged.
- **Opus review rounds were the single biggest cost line,** and they also found the most blocking issues. Worth it at the end of a big build; budget for them explicitly.

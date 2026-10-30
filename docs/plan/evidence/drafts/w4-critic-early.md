## Critic pass: over-engineering and evidence check

**Limit:** `out/w3-retro.md`, `out/w3-principles.md`, and `out/w3-structure.md` are absent from the mounted workspace, so I can’t verify draft wording or compare contradictions between those documents. The edits below are recommendations grounded in the available lenses and raw evidence.

### 1. Over-engineering

1. **Cut numeric intervention thresholds unless measured.** The lenses propose idle, context, and snapshot thresholds, but the evidence establishes incidents, not calibrated cutoffs: manager context reached 263K–281K tokens, and snapshots were stale at 05:58, 14:17, and 16:02 ([`w2-antipatterns`](out/w2-antipatterns.md); [`w2-supervision`](out/w2-supervision.md), 10-28). Keep event-based triggers—failed dispatch, ready work with no active worker, and status older than the last landing—until data supports numeric thresholds.

2. **Merge check-in, heartbeat, and status into one compact state view.** Don’t require separate entities or forms for each. A check-in needs only last activity, ready/running/result-ready counts, last landing or blocker, and next action. The evidence supports these signals: seven completed runs waited behind one worker, and hourly checks did not guarantee fresh snapshots ([`w2-antipatterns`](out/w2-antipatterns.md), 10-27 17:58–17:59; [`w2-supervision`](out/w2-supervision.md), 10-28 05:58–16:02).

3. **Keep roles, but avoid elaborate permission matrices.** Retain the role boundary and permitted action in the handoff. The owner repeatedly corrected the orchestrator/Opus taking execution or review work outside its assigned role (10-27 01:01; 10-28 01:29–02:08; [`w2-antipatterns`](out/w2-antipatterns.md)). The record supports clear assignment boundaries, not a complex authorization system.

4. **Use one task record with attempts and linked evidence, not separate required entities for every event type.** A task needs its current state, brief, model/tier, base revision where relevant, and result/evidence links. Retries can be attempt records; reviews and escalations can be linked notes. This addresses scattered state across queue rows, JSON, marker files, and folders without implementing a platform data model prematurely ([`w2-tracking`](out/w2-tracking.md)).

5. **Make reviews conditional and bounded.** Keep independent review for named risks or end-stage review; don’t prescribe multiple reviewer roles, mandatory reviews after every task, or overlapping recurring “deep,” “taste,” and elegance loops. The owner narrowed Opus to final review and elegance work (10-28 01:29–01:40); three end-review rounds and an elegance pass still produced substantial fixes, but their cost is not separable ([`w2-reviews`](out/w2-reviews.md)).

6. **Cut a mandatory difficulty formula.** The proposed scoring factors and tier cutoffs are inference, not validated prediction. The owner selected model routing by task tier (10-28 10:31), but the records do not compare estimates against outcomes by score. Use a manager’s tier choice with a short rationale; separately classify dispatch and environment failures.

7. **Do not require per-task cost fields in v0.** Costs were logged by session and context growth was visible, but no evidence shows reliable task-level attribution ([`w2-models-cost`](out/w2-models-cost.md)). Keep session-level cost and model records; add per-task attribution only if it informs routing.

### 2. Evidence check

1. **Qualify any claim that hourly checks failed as a cadence problem.** There is no evidence for a recurring 15-minute orchestrator check-in. Hourly oversight was requested; the observed 20/60-minute self-wake policy caused manager idling, and the owner later turned hourly review off (10-28 00:35–00:36; 18:09; [`w2-supervision`](out/w2-supervision.md)). Describe the specific failure as self-scheduling idle work and stale snapshots, not proof that hourly review is always too slow.

2. **Do not present specific idle/context/staleness cutoffs as discovered facts.** The evidence supports the conditions to watch, not “idle > N minutes,” “context > X tokens,” or “stale > Y.” Label these as configurable starting hypotheses if included.

3. **Do not claim a difficulty score predicts the right model.** Failures before code inspection were dispatch problems; an apparent product defect turned out to be a fixture issue; another test-isolation issue exposed a real file-handle leak (10-26 23:32–23:38; 10-28 14:17, 15:28–16:04; [`w2-models-cost`](out/w2-models-cost.md)). Require diagnosis when the cause is unknown and distinguish infrastructure failure from implementation failure.

4. **Qualify “base decides” for failure classification.** Comparing against `origin/main` corrected the old-branch baseline error, but tests absent or un-runnable on the base need a distinct classification (10-28 13:04, 15:27–15:29; [`w2-verification`](out/w2-verification.md)). Don’t reduce the rule to “every failure is pre-existing if it fails on base.”

5. **Avoid claiming that every review round paid for itself.** Reviews found concrete defects and scope cuts, but the recorded costs often combine review, implementation, and other work. The evidence supports bounded reviews with explicit scope; it does not establish an optimal number of rounds ([`w2-reviews`](out/w2-reviews.md)).

6. **Treat release-safety rules as untested where the program did not execute them.** The release-skill draft described procedures, but the process lens says no deployment used it ([`w2-codified-process`](out/w2-codified-process.md)). Present those as proposals, not proven practices.

### 3. Gaps to add

1. **Add a minimum-sufficiency check before queueing.** The owner repeatedly asked for an over-engineering and elegance pass; a 24-task test plan was reduced to 17, and an audit sweep was removed before execution (10-27 21:08–21:45; 10-28 16:48–17:11; [`w2-antipatterns`](out/w2-antipatterns.md)). Require every added task or process step to name the failure or release condition it prevents.

2. **Add source freshness to kickoff.** The installer audit began from a snapshot 127 commits behind main and had to correct claims about PATH and skill syncing after checking current source (10-26 01:12–01:14; [`w2-antipatterns`](out/w2-antipatterns.md)). Record the repo revision used for analysis and assignment.

3. **Add “work complete” separately from “verification complete.”** The rebase closeout said 1,021 tests were not run because they hung (10-28 20:56; [`w2-tracking`](out/w2-tracking.md)). A task or project can be implemented while verification remains incomplete; report both states.

4. **Add replacement-pack/delta handling.** Several zips superseded one another, and one was sent before tests finished; the owner clarified that the next manager already had earlier packs (10-28 16:13–17:11; [`w2-communication`](out/w2-communication.md)). Require version/supersedes, what changed, verification state, and recipient’s next action.

### 4. Contradictions between drafts

I can’t identify draft-to-draft contradictions without the three draft files. The available evidence does reveal tensions the drafts should resolve consistently:

1. **Continuous execution versus frequent supervision:** the manager should dispatch ready tasks back-to-back, while the orchestrator checks status separately. The owner corrected self-scheduled pauses; hourly oversight did not itself advance work (10-28 00:35–00:36; [`w2-supervision`](out/w2-supervision.md)).

2. **Autonomy versus approval gates:** the owner authorized independent decisions within scope while reserving actual direction changes and owner-dependent choices for escalation (10-28 02:08; [`w2-communication`](out/w2-communication.md)). State which decisions are delegated and which require approval; avoid a general approval gate on routine execution.

3. **“Done” versus unrun checks:** a completion gate must not imply all verification passed when tests or CI were unavailable. The queued Actions jobs and 1,021 hung tests were explicitly unverified (10-28 16:13, 20:56; [`w2-verification`](out/w2-verification.md)).
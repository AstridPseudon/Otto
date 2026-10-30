## Lens: Communication with the owner and deliverables

### Findings

1. **The owner repeatedly had to ask for the current state and the next step.** They asked whether work was “all cooking” several times, requested a completion percentage, then asked what was open, where the overall process stood, and what would happen after the rebase. [10-27 18:49, 19:10, 19:46, 20:36; 10-28 01:41, 09:53, 15:48] **Observed:** status replies were most useful when they named completed work, active work, blockers, and what came next; one answer estimated UPD at 65–70% and the overall program at about 30%. [10-27 19:10] **Inference:** status was not reliably available in a predictable, compact form, so the owner repeatedly pulled it.

2. **The morning digest and decision list made a large overnight phase easier to inspect, but the digest needed a correction.** It summarized project state, overnight decisions, costs, bigger issues with recommendations, and items awaiting the owner. [10-28 08:59; `DIGEST-2026-10-28.md`] At 09:00, the orchestrator corrected its test summary: ten Runtime tests were regressions, not clean results. [10-28 09:00] **Observed:** the digest’s shape helped expose decisions and remaining work; a mistaken test classification undermined its reliability.

3. **Zips provided durable handoffs, but version churn and incomplete packages created confusion.** Snapshots preserved work during a project pause and manager handoff. [10-27 02:24–02:26, 06:00; 10-28 00:00] On 28 Oct, several successive handover zips were sent; the 16:13 integration zip arrived while R8 tests were still running, and later packages explicitly replaced earlier ones. [10-28 16:13, 16:36, 16:41, 16:55, 17:11, 20:39] **Observed:** “replaces” labels and notes such as “updater bundles unchanged” helped recipients understand whether to reapply work. [10-28 17:11, 20:39] The owner still had to point out that the task was to update the zip for their own use, not execute the next program. [10-28 16:55]

4. **A manager message landed better as a delta once the owner clarified the recipient already had earlier packs.** The first message was framed as onboarding. The owner replied, “I already sent them the other packs,” and asked for an update to merge. [10-28 16:57] The later `MANAGER-NOTE.md` led with what changed, whether the new bundle was a fast-forward, sequencing, and a focused testing plan. [`out/astrid-handover-20261028-2038/MANAGER-NOTE.md`] **Inference:** paste-ready messages work best when they match the recipient’s current state and tell them exactly what changed and what action to take.

5. **Structured AskUserQuestion was used sparingly and for consequential choices.** The raw transcript shows three uses: choosing a repo owner, choosing whether to keep the session awake between hourly checks, and confirming a model-tier policy relayed from another session. [10-26 01:55; 10-27 14:58; 10-28 02:06] The keep-awake prompt explained the speed tradeoff; the repo prompt offered options based on account access. **Observed:** other decision and permission exchanges happened in ordinary messages—for example, the owner explicitly asked for an approval request when a CI push was blocked. [10-28 15:53] **Inference:** the structured tool was effective for bounded choices with clear options, but it was not the consistent path for asking owner-dependent questions.

6. **The owner explicitly authorized autonomy while asleep, with decisions recorded for later review.** At 02:08 they said, “No more questions. I'm going to bed. You have to figure out everything.” The runbook recorded a no-questions rule and said to report decisions in the morning digest. [10-28 02:08; `ORCHESTRATOR.md`] The owner also repeatedly bounded the role: orchestrate and unblock, while the manager executes. [10-28 02:08] **Observed:** the digest recorded overnight rulings and recommendations. **Inference:** autonomy was appropriate within the agreed scope and operating rules; product-direction or external-authorization choices still needed explicit owner attention when they could not be resolved from those rules.

7. **Decision lists were clearest when they separated a recommendation from a decision the owner still needed to make.** The 09:00 digest listed bigger issues with a recommendation for each and a separate “Still waiting on you” section. [`DIGEST-2026-10-28.md`] The final `NEXT-STEPS.md` similarly grouped open owner decisions, including a recommended macOS floor, broader product questions, a signing certificate, and unresolved CI behavior. [`out/astrid-handover-20261028-2038/NEXT-STEPS.md`] Earlier, the owner asked what cross-platform testing “require[d] from me,” and the orchestrator answered with six numbered decisions, rationales, and named gaps. [10-28 10:44–10:51]

### What worked

- **Evidence-backed status:** report rows done, active workers, stalled work, and next actions; the owner could distinguish “pushing works” from “Actions has run” when those were stated separately. [10-27 17:58–18:00; 10-28 15:55]
- **Durable snapshots and explicit replacement labels:** they preserved state and made the current handoff identifiable. [10-27 02:25; 10-28 20:39]
- **Decision tables with recommendations:** they let the owner review tradeoffs without rediscovering the underlying options. [10-28 08:59; 10-28 10:49–10:51]
- **Delta-oriented manager notes:** the final note explained what changed, what was already done, and how to continue without restarting the whole handoff. [10-28 17:11, 20:39]

### What failed / friction

- **Status was often owner-prompted.** Repeated “is it cooking?” and “what’s open?” questions suggest the promised hourly checks did not consistently answer the owner’s practical status questions in a visible, stable format. [10-27 18:49–20:36; 10-28 01:41, 09:53]
- **Digest accuracy needed a correction after delivery.** The Runtime regressions were initially missed because an integration-test note was read as covering all Runtime tests. [10-28 08:59–09:00]
- **Package state changed quickly.** Multiple zips superseded one another, and the early integration zip preceded completion of the test run. [10-28 16:13–20:39]
- **The first manager message did not fit the recipient’s context.** The owner had to clarify that the manager already had earlier packs and needed a delta. [10-28 16:57]
- **Some owner-dependent decisions were not surfaced in a single consistent format.** Structured questions were rare, while the owner repeatedly asked what remained for them to decide. [10-27 14:58; 10-28 10:44–10:51]

### Candidate principles

- **When the owner asks for status, give the phase, completed work, active work, blockers, and next action in one update, because repeated “what’s open?” questions show that activity alone did not answer their need.** [10-27 19:10; 10-28 09:53]
- **When reporting test results, state the baseline and separate passed, regressed, pre-existing, environmental, and not-run results; verify the source before sending, because the morning digest required correction.** [10-28 08:59–09:00]
- **When sending a replacement pack, identify the superseded version, what changed, what stayed identical, and whether work remains unverified, because several packages were replaced and one arrived before tests finished.** [10-28 16:13–20:39]
- **When writing for a manager who already has prior material, provide a delta with the next action, because the owner corrected an onboarding-style message into a merge/update request.** [10-28 16:57]
- **When owner input is required, list the decision, recommendation, reason, and consequence of deferring it; otherwise decide autonomously within the approved scope and record the ruling, because the owner asked both for practical decision lists and overnight autonomy.** [10-28 02:08; 10-28 08:59]
- **When a choice is bounded and materially changes execution, use a short structured question with concrete options and tradeoffs; reserve open discussion for product direction, because the three structured prompts were specific operational choices.** [10-26 01:55; 10-27 14:58; 10-28 02:06]

### Structure implications

- **Status record:** one live summary with phase, completed/active/blocked/not-run counts, last evidence update, next action, and next check time.
- **Decision record:** each item has owner-needed/autonomous status, recommendation, rationale, deadline or trigger, and final ruling.
- **Digest template:** project state; what changed since the last digest; verified test outcomes and baseline; decisions made while owner was unavailable; owner decisions still open; next actions.
- **Pack manifest:** version, timestamp, supersedes, changed files/repos, unchanged bundles, verification state, and remaining work.
- **Manager handoff field:** recipient context (“new” or “already has prior pack”), delta, required action, and read-first files.
- **Escalation checklist:** task ID, blocker, attempts/logs, proposed choices, whether it changes product scope or external permissions, and whether the owner is available. Escalate hard blocks or direction changes through the agreed reviewer path; reserve owner escalation for genuine owner decisions. [10-26 02:05; `ORCHESTRATOR.md`]
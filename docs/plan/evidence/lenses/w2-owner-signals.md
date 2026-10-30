## Lens: Owner signals

**Count note:** Counts are owner messages that clearly signal a correction, preference, frustration, approval, or praise. Themes overlap; routine questions and repeated “what’s happening?” status requests are counted under progress and visibility.

### Findings

1. **The owner repeatedly drew a boundary around the orchestrator’s role: guide the manager, don’t take over its work. — 10 messages.**  
   **Observed:** The owner described the orchestrator as a “guide to the manager” and “tastemaker,” with the manager “doing everything” [10-28 02:08]. Similar instructions appeared earlier: “the manager should be doing everything” [10-27 02:52], and “You should just be using a /loop to check in every hour” [10-27 13:02]. Later, when asking for a handover update, the owner clarified: “it’s not you doing this. You just need to update the zip file” [10-28 16:55].  
   **Trigger:** The orchestrator’s role drifted into inspecting, deciding, and doing implementation or integration work itself. The transcript shows it explicitly saying “No more digging into diffs myself” [10-27 01:01], but then continuing to take hands-on steps.  
   **Did the fix stick?** **Partly.** The owner restated the boundary the next day [10-28 02:08]. Near the end, the orchestrator prepared a package and manager note instead of starting that work itself [10-28 17:11].

2. **The owner wanted the manager to keep moving through tasks without unnecessary pauses. — 20 messages.**  
   **Observed:** “It should just be running through all the tasks back to back” [10-28 00:35]; “the manager should be doing everything” [10-27 02:52]; “don’t take any blockers. Keep pushing” [10-28 10:59]. The owner also checked repeatedly whether work was “cooking,” “moving,” or had stopped [10-27 15:12, 19:46, 20:36; 10-28 00:34].  
   **Trigger:** The manager stopped or paced work between turns, while scheduled checkups did not reliably establish that it was progressing. The orchestrator’s own notes say it had used `send_later` pacing and then changed the brief to prohibit it [main-full.txt, 10-28 17:58 summary].  
   **Did the fix stick?** **Not fully.** The brief was changed to run tasks back to back, but the owner later asked again why it had stopped [10-28 00:34–00:35]. The owner eventually turned hourly review off [10-28 18:09], showing the monitoring loop itself had become unwelcome.

3. **The owner corrected model routing and the role of expensive review models. — 7 messages.**  
   **Observed:** The owner asked why Opus was doing normal work and said it should do “review work and high-level taste-based work” [10-28 01:29]. They sharpened the rule: Opus should be used for a small number of end reviews, “without resulting in more tasks” [10-28 01:39, 02:08]. Later, they specified Luna for normal work, Terra for hard work, and Sol for super-hard work [10-28 10:31].  
   **Trigger:** Model assignments and responsibilities were not consistently reflected in manager execution.  
   **Did the fix stick?** **Partly.** The orchestrator updated model instructions [main-full.txt, 10-28 17:09], but the owner’s repeated questions suggest the routing rule had not been made visible or reliable enough.

4. **Proportionate, coherent plans mattered more than exhaustive process. — 13 messages.**  
   **Observed:** The owner opened with “not to over-engineer this or overdo it” [10-26 00:54], then repeatedly requested checks for over-engineering and an elegant, cohesive approach [10-26 01:15; 10-27 21:09, 21:41; 10-28 16:47, 16:57]. They explicitly asked for a first-principles review that could “simplify everything” [10-27 22:00].  
   **Trigger:** Plans accumulated overlapping projects, open decisions, review rounds, and process machinery that the owner could not easily see as one coherent path.  
   **Did the fix stick?** **Partly.** The owner approved plans and requested an “Elegance Pass,” but continued to ask whether the latest plan was appropriate, complete, and cohesive [10-28 16:34–17:02]. The repeated checks indicate that simplification and coherence remained active acceptance criteria, not a one-time review.

5. **The owner expected clear progress, proof, and status—not just assurances. — 20 messages.**  
   **Observed:** They asked whether the loop was working after a two-hour silence [10-27 14:56], what percentage was done [10-27 15:27, 19:10], whether CI was actually running [10-28 15:50], and whether there was a way to test the approval flow [10-28 15:58].  
   **Trigger:** Reports and scheduled checks did not reliably answer the practical questions: what is running, what passed, what remains, and what is blocked.  
   **Did the fix stick?** **Partly.** The orchestrator began reporting concrete state and later explained that the rebase was still running and named the pending tests [main-full.txt, 10-28 17:58 and 20:38]. But repeated status questions show that visibility was not dependable enough throughout the program.

6. **The owner wanted autonomy, with interruptions reserved for genuine decisions. — 6 messages.**  
   **Observed:** “ORGANISE IT YOURSELF AND WITH HAIKU HELPERS” [10-26 19:55]; “No more questions. I’m going to bed. You have to figure out everything” [10-28 02:08]. They also said they were happy to accept gaps and asked the orchestrator to keep pushing [10-28 10:48–10:59].  
   **Trigger:** The process risked turning implementation choices and routine obstacles into owner decisions.  
   **Did the fix stick?** **Partly.** The owner delegated broad judgment, but still had to reassert that the manager should continue and that the orchestrator should only prepare the handoff [10-28 16:55].

7. **The owner changed scope deliberately and expected those changes to propagate. — 6 messages.**  
   **Observed:** They paused the original program to run the updater [10-27 02:24], said not to start the testing plan yet [10-27 21:50], and later asked for analysis of a failure without fixing it [10-28 16:24].  
   **Trigger:** The program had multiple mapped projects, so scope boundaries could blur as new findings arrived.  
   **Did the fix stick?** **Mostly.** At 16:24, the request was investigation-only; the owner then asked for a written spec and updated pack [10-28 16:34–16:55]. The orchestrator ultimately prepared the package and message rather than launching implementation [main-full.txt, 10-28 17:11].

8. **Approval and praise most often followed concrete, bounded proposals.**  
   **Observed:** The owner said “Cool, yeah, let’s add that” after a specific Start Menu shortcut proposal [10-26 01:45], “Yeah, I agree” after a recommendation on open project decisions [10-28 10:59], and “nice” when asking about elegance and testing [10-27 17:51]. They approved the hotfix/full-release distinction and version pinning after those were made explicit [10-27 22:42].  
   **What preceded it:** A defined choice, a clear recommendation, and a visible outcome or boundary. Praise is sparse; these approvals should not be treated as blanket satisfaction with the overall process.

### What worked

- **Specific choices could be approved quickly.** The shortcut, release paths, and model tiers got direct approval once framed concretely [10-26 01:45; 10-27 22:42; 10-28 10:31].
- **The owner’s trust rose when judgment was delegated explicitly.** “ORGANISE IT YOURSELF” and “No more questions” authorized independent decisions within the stated goal [10-26 19:55; 10-28 02:08].
- **A bounded handoff fit the owner’s role separation.** The updated pack and manager note let the owner direct another manager without asking the orchestrator to run that manager’s work [main-full.txt, 10-28 17:11].
- **Concrete execution evidence was more useful than broad reassurance.** The final rebase update named fixes, test-only changes, tests not run, and the delivered package [main-full.txt, 10-28 20:38–20:56].

### What failed / friction

- **Role boundaries had to be repeated.** The owner specified the orchestrator/manager split on 10-27 and again on 10-28; the orchestrator’s practical behavior did not immediately match it [10-27 02:52; 10-28 02:08].
- **The manager’s continuity was not self-evident.** Stopping, pacing, and sparse updates generated repeated “is it running?” checks [10-27 14:56, 18:49; 10-28 00:34–00:35].
- **Model policy was stated but not enforced visibly.** The owner had to ask why Opus was doing normal work, then restate the routing [10-28 01:29–01:39].
- **Project status and CI status were too ambiguous.** The owner asked whether CI was running and offered a zip fallback despite earlier permissions [10-28 15:50–16:11].
- **Plans could grow faster than their shared shape stayed clear.** Requests for first-principles review, coherence, and over-engineering checks recurred across the planning period [10-27 21:09–22:19; 10-28 16:34–17:02].

### Candidate principles

- **When a manager owns execution, keep the orchestrator to planning, unblocking, and scheduled review, because the owner explicitly assigned coordination and implementation to the manager [10-28 02:08].**
- **When the owner delegates judgment, make routine decisions and continue; escalate only the agreed decision types, because the owner said “No more questions” and “figure out everything” [10-28 02:08].**
- **When work is meant to run continuously, dispatch the next ready task immediately and make idle states visible, because the owner objected to scheduled checkups interrupting back-to-back work [10-28 00:35].**
- **When assigning work, make task tier, worker model, and reviewer role explicit in the queue, because the owner had to correct Opus’s use and re-specify Luna/Terra/Sol routing [10-28 01:29–01:39, 10:31].**
- **When a new finding appears, record whether it is investigation, implementation, or deferred scope, because the owner explicitly asked for investigation without fixing and later requested only a pack update [10-28 16:24, 16:55].**
- **When presenting a plan, show the simple end state, open decisions, proof needed, and what is out of scope, because the owner repeatedly asked for a coherent, elegant plan without over-engineering [10-27 21:41; 10-28 16:47].**
- **When reporting progress, state active task, last activity, next milestone, blocked reason, and evidence, because the owner repeatedly asked whether work and CI were actually running [10-27 14:56; 10-28 15:50].**

### Structure implications

- **Program roles:** Add `orchestrator_scope`, `manager_scope`, and `escalation_triggers` to the program brief; display them in every manager handoff.
- **Task queue:** Require `tier`, `worker_model`, `reviewer_model`, `status`, `next_action`, and `blocked_reason`; flag any task assigned outside the approved routing.
- **Run state:** Record `last_activity_at`, `active_worker`, `current_task`, `next_task`, and `idle_reason`. Trigger an alert when a manager is idle while eligible queued work exists.
- **Cadence:** Separate manager execution cadence from orchestrator review cadence. A scheduled review should inspect the run, not become the mechanism that advances tasks.
- **Progress report:** Use one compact status shape: completed / active / queued / blocked, latest evidence, next milestone, and estimate confidence.
- **Scope changes:** Add a change record with `requested_by`, `decision`, `effective_after`, and `implementation_allowed`; distinguish “investigate only” from “implement.”
- **Plan review:** Add a checklist question: “What can be removed while preserving the owner’s stated end state?” Require a short rationale for each added process layer.
- **Handoffs:** Include the latest approved decisions and explicitly mark replaced versions, so the manager does not repeat work or follow stale instructions.
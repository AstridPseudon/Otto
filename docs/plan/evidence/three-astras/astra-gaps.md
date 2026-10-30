> Astra (read-only review, 30 Oct). Links into `/tmp/...scratchpad` point at the restored Otto, oh-my-pi and Astrid clones used for the review; they are not in this repo.

**The plan does not yet guarantee the end state.** The architecture fits the owner’s direction, but several tasks can pass their stated checks while leaving attachment, recovery, delivery or acceptance incomplete.

This is a read-only source review. I checked the integrated Otto code at `a70b3f2`, the packs branch at `403182e`, omp at `95db18e`, and Astrid’s `origin/main`. I did not run live sessions or recovery tests.

**1. Gap table**

| Gap | Why it matters | Evidence | Smallest fix | Owner |
|---|---|---|---|---|
| **G1 — Acknowledgement and idempotency remain unspecified.** | Replaying a message can create another task, worker or reply even if setting a task’s state twice is harmless. Admission and settlement do not establish that the requested action was applied. | [Spec:75][s75]; [R3:111][p111]. omp creates a new in-memory ticket for each `begin(id)` call: [rpc-prompt-results.ts:86][rpc86]. | Define acknowledgement separately from admission and reply resolution. Give mutating CLI operations stable operation keys and transactional replay behaviour. Define how external inbox users acknowledge messages. Limit the guarantee to operations the tool controls. | **L0, C1, R3** |
| **G2 — Session recovery is not work recovery.** | A transcript can reopen successfully while its interrupted task remains stranded. Conversely, releasing a task to `todo` and later resuming its original worker can produce competing attempts. | [R1/R5b:109][p109]; automatic task release in [spec:162][s162]. omp distinguishes resume from unfinished-work restoration; `--restore` is interactive-only: [CLI:87][cli87]. | Specify interrupted-turn continuation, task-attempt ownership and stale submissions. Preserve the original worktree and unfinished edits. Distinguish supervisor restart, deliberate stop, cancellation and replacement. The manager still decides whether to redispatch. | **L0, R1, R5b, C4, R2** |
| **G3 — Landing and task acceptance lack a recovery contract.** | Git may advance before SQLite records completion, or a task may become done before its code lands. Rebase/check/fast-forward alone does not close that window. | [D2:132][p132]; old landing performs assessment and acceptance before its Git update: [landing.py:279][land279]. | Record the submitted commit, target/base and checked commit on the task or existing events. Mark done only after landing. On restart, reconcile the recorded candidate against Git ancestry before retrying. Make D2’s final gate depend on C4/R2 integration. | **D2, C4, R1** |
| **G4 — Attach does not deliver “any seat,” or a complete handover.** | AT implements only orchestrator and manager attachment. It specifies CLI identity but not delivery of role instructions, skills and current responsibility. Stopping a supervised process also does not resolve two outside sessions claiming the same seat. | “Any seat” in [15:21][short21]; [AT:103][p103]; native sub-agents remain omp-owned in [spec:130][s130]. | Decide supported seats explicitly. Return a handover containing role guide, skills, mandate, current work and inbox instructions. Bind identity to the database and attachment, define external-to-external takeover, and reject stale bindings. State that outside processes themselves require cooperative handover. | **AT, L0, P2** |
| **G5 — Spec reconciliation has no submission policy.** | “Worker notified” does not determine whether its old brief remains valid. A worker can submit while the manager changes or cancels its task. “Spec revision” also needs a precise meaning for a folder of independently versioned files. | [Spec:61][s61]; [C5:102][p102]; document and task fields in [spec:146][s146]. | Define an immutable folder snapshot or revision map. Preserve the assignment’s original snapshot. Let the manager explicitly continue, amend or cancel it; validate submission against that assignment. Include the race between reconciliation and submission. | **L0, C3–C5, P3** |
| **G6 — Model changes have undefined timing.** | Updating `otto-manager` in the picker does not change a healthy manager already running. Long-lived roots could retain their original models indefinitely. P4’s overlay wording also conflicts with R2’s explicit exclusion of `modelRoles`. | [Spec:53][s53]; [R2:110][p110]; [P4:122][p122]. Actual reload behaviour: [omp settings:111][settings111]. | Define new-spawn, resume and explicit live-switch semantics. Show configured role and actual active model separately. State that P4 exposes agent definitions through the overlay; role seeds remain in omp’s normal settings. | **S0, L0, C2, R2, P4** |
| **G7 — Megado is source material, not a ready replacement pack.** | Copying it carries the retired owner service, admission, allowances and old command vocabulary into the new product. Its advisor is paired with a manager, not the portfolio orchestrator. | Old service instructions: [Megado SKILL.md:24][mega24]; advisor policy: [SKILL.md:224][mega224]. The pack is on a separate preservation ref: [branches.json:157][branches157]. | Pin that source ref and deliberately translate the method into the new CLI and five roles. Preserve pragmatic review, task decomposition and improvement follow-through; remove obsolete mechanics. Evaluate whether a fresh agent can perform the workflow, not merely whether files have frontmatter. | **P1–P5** |
| **G8 — Advisor delivery stops at “advice returned.”** | A consultation can succeed technically while producing no decision or useful change. The existing Megado method explicitly requires follow-through. | [R4:124][p124]; [improvement-loop.md:15][improve15]. | Put “adopt, defer with reason, or reject; then verify adopted changes” into the orchestrator/check-in skills. Include prior advice and its disposition in the next snapshot. No automatic execution or new ledger is needed. | **P2, P3, R4** |
| **G9 — Native sub-agents are not fully covered by the hierarchy/message promises.** | R6 records events for status. It does not define durable helper results, interrupted-helper handling or CLI identity. Checking `otto spawn` alone does not restrict omp’s native delegation. | [Spec:130][s130]; [R6:114][p114]. Unspecified native spawn policy is unrestricted: [spawn-policy.ts:19][spawn19]. | Define the worker/native-helper boundary: allowed delegation, identity, results and restart behaviour. Configure native delegation consistently with the hierarchy. Either bridge helper results into the durable contract or explicitly scope the single-inbox promise to managed seats. | **L0, R2, R6, P4** |
| **G10 — The idle rule misses some unfinished managerial work.** | A manager can settle with submitted tasks awaiting acceptance, or a new spec awaiting decomposition, and have no “startable tasks.” Observation mode also has no named release condition. | Broad promise in [15:16][short16]; narrower predicate in [spec:77][s77]; [R5a:125][p125]. | Define actionable manager work to include pending acceptance and unreconciled spec changes, while retaining legitimate waits. Name when enforcement starts and require the pilot to demonstrate it. | **R5a, C5, P2** |
| **G11 — Validator reuse needs a defined extraction boundary.** | `validate_files` checks strings and path collisions; filesystem safety lives elsewhere. Validating each incoming batch separately also misses collisions with concurrently saved files. The old save implementation is explicitly non-atomic. | [project_folder.py:47][folder47], [project_folder.py:467][folder467]; filesystem checks in [snapshots.py:180][snap180]. | Extract leaf validators and filesystem checks without owner-service dependencies. Validate the resulting tree within the save transaction. Keep the atomic revision/base/notification implementation new. | **C3** |
| **G12 — The final gate can omit attached operation.** | D3 names acceptance items 1–10; attach is item 11. The plan’s pilot list omits the attached-orchestrator scenario required by the spec and end-state summary. | [D3:133][p133]; [plan pilot:180][p180]; [spec:202][s202]. | Update D3 to 1–11 and add an outside-session attach → operate → detach sequence to D5, including pending messages and reminders. | **D3, D5, AT** |
| **G13 — Moving machines is only a copying suggestion.** | Stored session paths, overlays and worktree locations may become invalid; unsaved checkouts and pack assets may lie outside the listed copied directories. | [Spec:113][s113]; agent/config fields in [spec:148][s148]. | Document the complete state bundle and either a stable directory layout or relocation procedure. Include an offline restore exercise. Describe “one SQLite file” as orchestration state; omp still owns additional state. | **D4, R1, D5** |
| **G14 — Closeout is outside the task list.** | Completing all 28 tasks does not itself freeze the required refs, finish cleanup or record the next-pack decision. The spec also retains a competing 28-day implementation plan. | [Plan:189][p189]; obsolete estimate in [spec:243][s243]. | Add a small owned closeout task preserving the packs ref as well as canon. Replace spec Part C’s duplicate schedule with a pointer to the authoritative plan. | **New closeout task; orchestrator/M4** |

**2. Top five gaps**

1. **G1: Durable delivery needs an acknowledgement and mutation contract.** Otherwise “a repeated message does no harm” remains an aspiration.
2. **G2: Recovery must preserve unfinished work and one current task attempt.** Reopening the correct transcript is insufficient.
3. **G3: Landing must reconcile Git with task completion.** Otherwise the database can report an outcome that the repository does not contain.
4. **G4: Attach needs a defined scope and complete handover.** The current task does not implement the advertised “any seat.”
5. **G5: Spec changes need explicit treatment of running assignments and submitted results.** Notification alone cannot keep the spec authoritative.

G12 is the immediate plan edit that prevents attachment from disappearing at the final acceptance gate.

**3. Ambiguities the owner must decide**

| Decision | Recommended answer |
|---|---|
| **Does “any seat” include native sub-agents?** | Support advisor, orchestrator, manager and worker attachment in v1. Keep native helpers under their worker. This explicitly narrows [15:21][short21]; if literal attachment to all five roles is required, add and estimate a native-helper takeover task. |
| **One orchestrator per database, or several?** | One orchestrator and one advisor per database; use another database for another organisation. This resolves the existing [open question][p204] without adding portfolio ownership machinery. |
| **Does changing a model role immediately reroute existing sessions?** | Apply changes to new agents. Resume preserves the saved model unless explicitly changed; offer an explicit switch at a settled boundary for long-lived seats. omp’s reload alone does not perform that switch ([settings:111][settings111]). |
| **What happens to running work when the spec changes?** | The manager chooses continue under the original brief, amend, or cancel. Preserve that decision and the original snapshot. This retains manager judgment and avoids automatic replanning ([C5][p102]). |
| **How broad is “a repeat does no harm”?** | Guarantee replay-safe tool-owned mutations. Arbitrary shell, repository and external effects require reconciliation after an uncertain interruption. A universal guarantee would reintroduce machinery explicitly excluded by [spec A5][s93]. |
| **Which real project is the pilot?** | Pick a small repository that supports two concurrent workers, an actual landing, a mid-work spec change and outside-session attachment. The owner’s selection remains outstanding ([plan:203][p203]). |

**4. Reuse assumptions that are wrong, and corrected estimates**

These are planning estimates from source inspection, not measured implementation times.

| Assumption | What the code actually supplies | Corrected allowance |
|---|---|---|
| **D2 can lift Otto’s landing service into a small script.** | `LandingService` requires fleet, admission, sealed runner results, assessments and completion gates ([landing.py:62][land62]). Reuse the Git sequence and selected behavioural cases, including the [rebased-commit test][landtest275]. The existing Astrid [land.sh:30][shell30] is not an alternative implementation: it uses `--no-ff`, performs no post-merge check and removes worktrees. | **D2: 3–4 days**, replacing 1.5, including the task/Git recovery boundary. |
| **Megado mainly needs rearranging into files.** | The packs branch contains 24 Megado files and 1,854 lines; its main skill alone is about 6,150 words. It needs substantive translation to the approximately 3,000-word target, new commands and a different advisor relationship ([old entry instructions][mega24], [old advisor][mega224], [new target][s187]). | **P2+P3: 4–5 days**, replacing 3. Other pack tasks retain their existing allowance. |
| **“Folder validators” constitute a self-contained module.** | Portable-path checks, content checks and filesystem capture checks are distributed across modules. The folder service uses separate commits and reports `atomic: False` ([folder validators][folder47], [filesystem boundary][snap180], [save result][folder467]). | **C3: 3.5–4 days**, replacing 3. This includes extraction; it does not count atomic check-in as reusable. |
| **omp resume supplies interrupted execution recovery.** | Exact-session resume is reusable. Continuation of interrupted work, task ownership and worktree reconciliation remain application work; automatic `--restore` is interactive-only ([CLI:87][cli87]). | **R1+R5b: 5.5–6 days**, replacing 4.5. |
| **Astrid installation can be reused unchanged.** | The revised plan already correctly says **recipe pattern**, new pin and hashes ([D1][p130]). That correction is sound; no further reuse penalty is warranted before S0. | Retain **D1: 1.5 days**, conditional on S0. |

For a complete revised baseline, also allow **AT 3–4 days**, **R3 3–3.5 days**, **C5 2 days**, and **0.5 day for closeout**. Together these adjustments put the plan at approximately **53–58 engineer-days**, retaining its existing contingency and assuming the recommended four-seat attachment scope. Recalculate the calendar schedule after S0/L0.

**5. Verdict and minimum changes**

**No: executing the plan literally can produce individually passing components without the promised complete workflow.** Proceed with S0, then revise the execution contract before parallel implementation.

The minimum changes are:

- Extend **L0** with acknowledgement/replay semantics, task-attempt recovery, attachment handover, spec-change policy and Git/task reconciliation.
- Strengthen the affected tasks’ completion conditions using **G1–G5**.
- Translate Megado deliberately; settle model-change timing and the native-helper boundary.
- Include **acceptance item 11 and attached operation in the pilot**.
- Assign restore documentation and closeout, preserve the packs branch, and update estimates.

These changes can use the existing tables, events, CLI and skills. They do not require automatic dispatch, spend controls or restoring Otto’s authority architecture.

[s53]: /home/user/repo/astrid-install/retro/13-spec.md:53
[s61]: /home/user/repo/astrid-install/retro/13-spec.md:61
[s75]: /home/user/repo/astrid-install/retro/13-spec.md:75
[s77]: /home/user/repo/astrid-install/retro/13-spec.md:77
[s93]: /home/user/repo/astrid-install/retro/13-spec.md:93
[s113]: /home/user/repo/astrid-install/retro/13-spec.md:113
[s130]: /home/user/repo/astrid-install/retro/13-spec.md:130
[s146]: /home/user/repo/astrid-install/retro/13-spec.md:146
[s148]: /home/user/repo/astrid-install/retro/13-spec.md:148
[s162]: /home/user/repo/astrid-install/retro/13-spec.md:162
[s187]: /home/user/repo/astrid-install/retro/13-spec.md:187
[s202]: /home/user/repo/astrid-install/retro/13-spec.md:202
[s243]: /home/user/repo/astrid-install/retro/13-spec.md:243
[p102]: /home/user/repo/astrid-install/retro/14-plan.md:102
[p103]: /home/user/repo/astrid-install/retro/14-plan.md:103
[p109]: /home/user/repo/astrid-install/retro/14-plan.md:109
[p110]: /home/user/repo/astrid-install/retro/14-plan.md:110
[p111]: /home/user/repo/astrid-install/retro/14-plan.md:111
[p114]: /home/user/repo/astrid-install/retro/14-plan.md:114
[p122]: /home/user/repo/astrid-install/retro/14-plan.md:122
[p124]: /home/user/repo/astrid-install/retro/14-plan.md:124
[p125]: /home/user/repo/astrid-install/retro/14-plan.md:125
[p130]: /home/user/repo/astrid-install/retro/14-plan.md:130
[p132]: /home/user/repo/astrid-install/retro/14-plan.md:132
[p133]: /home/user/repo/astrid-install/retro/14-plan.md:133
[p180]: /home/user/repo/astrid-install/retro/14-plan.md:180
[p189]: /home/user/repo/astrid-install/retro/14-plan.md:189
[p203]: /home/user/repo/astrid-install/retro/14-plan.md:203
[p204]: /home/user/repo/astrid-install/retro/14-plan.md:204
[short16]: /home/user/repo/astrid-install/retro/15-in-short.md:16
[short21]: /home/user/repo/astrid-install/retro/15-in-short.md:21
[shell30]: /home/user/repo/astrid-install/tools/land.sh:30
[rpc86]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/packages/coding-agent/src/modes/rpc/rpc-prompt-results.ts:86
[cli87]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/docs/cli-reference.md:87
[settings111]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/docs/settings.md:111
[spawn19]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/research/oh-my-pi/packages/coding-agent/src/task/spawn-policy.ts:19
[land62]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:62
[land279]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:279
[landtest275]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/tests/test_landing.py:275
[folder47]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/otto/portfolio/project_folder.py:47
[folder467]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/otto/portfolio/project_folder.py:467
[snap180]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/authoring/snapshots.py:180
[mega24]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/projects/packs/src/otto/packs/megado/skill/SKILL.md:24
[mega224]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/projects/packs/src/otto/packs/megado/skill/SKILL.md:224
[improve15]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/projects/packs/src/otto/packs/megado/skill/references/improvement-loop.md:15
[branches157]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/branches.json:157
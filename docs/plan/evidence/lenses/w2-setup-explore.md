## Lens: Project setup and exploration

### Findings

1. **The strongest kickoff started from an owner problem and a design constraint.** On 10-26 00:54, the owner described a Windows installer complaint and asked for a solution that was convenient, cross-platform, and not over-engineered. Follow-up questions established the actual concerns—unsigned scripts, background startup, PATH changes, symlinks, and global skills—and the owner’s preferences. **Observed:** the plan began with a problem and constraints, not a list of implementation tasks. [10-26 00:54–00:59; `data/main-full.txt`]

2. **Exploration used narrow investigations, then checked conclusions against current code.** Three Haiku probes examined the UI, agent instructions, and installer lifecycle. That produced a first task list, but a later check found its source snapshot was 127 commits behind `main`; the orchestrator corrected claims about PATH and skill syncing before finalizing the list. **Observed:** the re-check caught a material error. **Inference:** “what does the code do now?” should be an explicit kickoff gate, separate from interpreting the original report. [10-26 01:07–01:14; `data/main-full.txt`, `data/subagents.txt`]

3. **Independent review improved scope, but reviewer roles and outputs needed clarification.** The owner asked for Astra to judge over-engineering and for Opus to lead Mac/Linux exploration. The owner corrected the first assignment because Opus was asked for a general review rather than to lead the platform work; the resulting Opus report also said it had not used Haiku sub-agents. Later, Astra reviewed the task list. [10-26 01:15–01:26; `data/main-full.txt`]

4. **Plans became actionable when they specified a user-visible end state, shared contracts, task dependencies, and acceptance.** The program plan described the end state by user journey, set shared principles, divided work into stages and lanes, and established precedence between meta-plan, contracts, and plan files. The TST queue added dependencies, owners/models, a one-line “Done when,” and an explicit “NOT ACTIVE” state. [`PROGRAM.md` §§1–5; `plans/TEST-cross-platform-testing.md`; `runs/TEST-QUEUE.md`]

5. **The TST kickoff shows a complete explore → plan → review → queue sequence.** On 10-27 21:07, the owner supplied a testing-plan draft and asked for first-principles exploration through Codex Luna agents. Opus produced a 24-task plan based on 22 Luna explorations; Astra then recommended 16 implementation tasks plus qualification, and the plan was trimmed. The project was registered as planned but unqueued, as requested. [10-27 21:07–21:28; `data/main-full.txt`; `data/plan-repo-gitlog.txt` commits `67fb970`, `236f187`, `9bf632c`]

6. **A good plan separated test work from product changes and made uncertainty visible.** Astra’s TST review said to keep real-product qualification and recovery coverage while cutting excessive infrastructure and matrix multiplication. It also called for unresolved coverage to remain explicitly “not run” or a named gap. The revised plan made TST tests-only and escalated product bugs to their owning project. [`evidence/2026-10-27-astra-TST-overeng.md`; `plans/TEST-cross-platform-testing.md`]

7. **Over-planning and incomplete alignment between documents created avoidable friction.** The first TST plan had 24 tasks; Astra recommended 16 implementation tasks, while the final qualification brings the tiered task count to 17. The current queue describes a single Astra review round, despite the rewrite instructions specifying two; the plan header and queue should be reconciled before activation. **Inference:** a plan is not “ready to queue” until its scope, task count, review cadence, and current version agree across files. [10-27 21:23–21:41; `evidence/2026-10-27-astra-TST-overeng.md`; `runs/TEST-QUEUE.md`]

8. **The handoff to managers was a distinct setup step, not an automatic consequence of planning.** The program docs defined the manager’s role, the worker tiers, task queue, status source, and escalation path. TST remained explicitly unqueued until owner authorization; by contrast, the program kickoff commit records the first wave assigned and scheduled tasks created. [`README.md` §§“Read in this order,” “Roles,” “Starting the program”; `MANAGER.md`; `data/plan-repo-gitlog.txt` commits `ddebe16`, `9709254`]

### What worked

- Asking for the owner’s underlying concerns before scoping tasks exposed both product goals and constraints, including cross-platform support and simplicity. [10-26 00:54–01:07; `data/main-full.txt`]
- Narrow probes and a current-main check combined evidence gathering with a correction loop. [10-26 01:07–01:14; `data/subagents.txt`, `data/main-full.txt`]
- Independent review changed the plan: Astra’s cuts removed redundant test machinery while preserving core coverage. [10-27 21:23–21:45; `evidence/2026-10-27-astra-TST-overeng.md`]
- The queue carried execution details—dependencies, tiers, acceptance, and activation state—so a manager could start from a defined source of truth. [`runs/QUEUE.md`; `runs/TEST-QUEUE.md`]

### What failed / friction

- The initial investigation relied on stale source evidence; verifying `main` late forced plan corrections. [10-26 00:57, 01:12–01:14; `data/main-full.txt`]
- Reviewer roles were initially misunderstood, and the requested Opus-led delegation did not happen as specified. [10-26 01:18–01:26; `data/main-full.txt`]
- The TST plan initially overbuilt the test system: automatic historical-version discovery, broad cross-OS crash matrices, shell multiplication, and heavy traceability. Astra recommended replacing these with bounded release anchors and focused evidence. [`evidence/2026-10-27-astra-TST-overeng.md`]
- Plan facts drifted across artifacts: the original 24-task version was still present after a trimmed version was recommended, and the current queue’s review-round count differs from the rewrite instruction. [10-27 21:39–21:41; `runs/TEST-QUEUE.md`]

### Candidate principles

- When a project begins from a complaint or proposal, write down the user problem and constraints first, because the owner’s constraints shaped both the installer design and the TST scope. [10-26 00:54–01:07; 10-27 21:07]
- When a plan depends on code behavior, verify the relevant branch and commit before estimating or assigning tasks, because the stale snapshot led to incorrect claims about PATH and skill syncing. [10-26 01:12–01:14]
- When exploration is delegated, give each investigator a narrow question, required sources, and an expected report, because the UI, agent-flow, and lifecycle probes produced distinct evidence for the plan. [10-26 01:07; `data/subagents.txt`]
- When asking for a review, state the reviewer’s role, inputs, and required output, because the Opus platform-lead assignment was initially misunderstood. [10-26 01:18–01:26]
- When a plan has many coverage dimensions, require an over-engineering review before queueing, because Astra reduced TST from 24 implementation tasks to 16 while preserving the stated confidence goals. [10-27 21:23–21:45]
- When a project is ready for execution, require each task to name its “Done when,” dependencies, tier, and evidence, because those fields were used in the manager queue and task reviews. [`runs/TEST-QUEUE.md`; `runs/QUEUE.md`]
- When a queue is not authorized to start, encode that state in the queue itself, because TST was explicitly held until the owner queued it. [`runs/TEST-QUEUE.md`]

### Structure implications

- **Project brief:** fields for problem/source, intended user, constraints, end state, non-goals, known decisions, open questions, and evidence freshness (repo, branch, commit, date).
- **Exploration record:** one item per probe with question, assigned model/tool, sources examined, findings, confidence, and follow-up verification.
- **Plan review gate:** separate checks for correctness against current code, cross-platform or domain coverage, feasibility, and over-engineering; capture accepted cuts and unresolved risks.
- **Task schema:** ID, scope, owning repo/lane, tier/model, dependencies, one-line “Done when,” verification evidence, risks, and state.
- **Activation control:** distinct states such as draft, reviewed, approved, queued, active; queueing should require reconciled plan and task counts.
- **Manager handoff:** generate a concise brief from the approved plan and queue, including authority boundaries, escalation triggers, source-of-truth files, and explicit start authorization.
The goal is **trustworthy progress with little owner intervention**, within agreed scope, cost and quality. That requires clear delegation, reliable execution and durable evidence. Instruction compliance supports that goal; it is not the goal itself.

I used seven Luna investigations and checked the load-bearing evidence directly. No files were changed. References below use `06` for `retro/06-otto-end-state.md`, `ops/` for `otto/portfolio/ops/`, and `src/` for `otto/source/otto/src/`.

**#1 — Goal alignment: The proposed end state over-centers agent behavior and under-specifies successful delivery.**

- **Reasoning from first principles:** An obedient manager can complete its queue while the intended user workflow remains broken. The owner needs evidence of outcomes, including explicit limitations.
- **Evidence:** `06:42–49` defines the product around behavior and enforceable “done.” Yet `data/mgr3-digest.txt:3287` reports queue completion while about 707 agent integration tests and Pinokio integration remain unrun. Otto’s later installed-client failure prevented dispatch despite extensive preceding checks (`ops/requests.md:1807–1813`).
- **Recommendation:** Define project acceptance through the real user path. Preserve distinct states for implemented, verified and accepted-with-gaps. Task completion must not silently imply project verification.
- **What it would cost or lose:** Real-environment qualification costs time and may require owner access or explicit acceptance of gaps.
- **Confidence:** High.

**#2 — Hole: Turn-end checks cannot provide liveness, and repetition alone cannot bound a stall.**

- **Reasoning from first principles:** A process that dies, hangs or loses its wake-up may never produce the second event needed for escalation.
- **Evidence:** `06:17–25,46,66–69` centers stop hooks and repetition. A restart stopped the manager, worker and landing process (`ops/requests.md:199–200`). Stage 2 later waited forever for a worker never dispatched (`:1807–1810`). Existing guidance also requires managers to yield when an active turn prevents result settlement (`otto/skills/otto/references/manager.md:35–37`).
- **Recommendation:** Keep managers choosing and dispatching tasks. Automatically deliver completions and wake the responsible manager; independently detect missing starts, lost sessions and overdue dependencies. Use repetition for recurring behavioral mistakes, deadlines for unresolved waits, and immediate handling for hard-limit violations.
- **What it would cost or lose:** A small persistent monitor, configurable timing and some false alarms. Automatic wake-up is additional machinery, but does not require automatic task selection.
- **Confidence:** High.

**#3 — State integrity: Record effects when they happen; do not make managers reconstruct truth afterward.**

- **Reasoning from first principles:** A generated digest is only as trustworthy as its underlying records. Automating presentation does not fix stale or false inputs.
- **Evidence:** A killed landing printed “landed” for another task’s commit (`ops/requests.md:218–220`). A stale status column caused already-landed tasks to be reported as unfinished (`:453–455`). `06:28,59` still combines manager-maintained snapshot obligations with generated views.
- **Recommendation:** Have launch, check, landing and publication tools record their own receipts. Reconcile interrupted operations against actual process and repository state. Derive views with an observation timestamp and explicit unknowns. Preserve tested handoff/import checks.
- **What it would cost or lose:** Tool integration and recovery logic. It eliminates neither exceptional reconciliation nor the need to retain artifacts.
- **Confidence:** High.

**#4 — Guarantee to retain: Baseline and execution identity must remain attached to evidence.**

- **Reasoning from first principles:** “Passed” is meaningless without knowing which code, dependencies, environment and comparison it describes.
- **Evidence:** The rebase manager’s old classification treated failures on `prog/upd` as “known-UPD”; correcting the baseline exposed ten regression IDs and five failing new-test IDs (`data/mgr4-digest.txt:1100–1119`). Otto already binds passing runner evidence to the exact commit and command context (`src/otto/hostctl/fleet_landing.py:229–249`).
- **Recommendation:** Preserve these guarantees inside tools. Capture repository/dependency revisions, check command, environment and authoritative base. Require affected evidence to be refreshed after integration or relevant changes.
- **What it would cost or lose:** Some repeated verification and metadata. Avoid requiring unrelated checks to rerun merely because any file changed.
- **Confidence:** High.

**#5 — Enforcement: A policy enforced by one optional launcher is not a system-wide limit.**

- **Reasoning from first principles:** More instructions cannot repair a control that callers can bypass through an ordinary supported route.
- **Evidence:** `ops/launch_review.sh:18–24` enforces review-call caps. `ops/d19_watch.py:43–49,68–86` launches Astra directly and can launch again after further requests. This verifies a bypass mechanism; it does not independently establish the summary’s exact “23 calls.”
- **Recommendation:** Put budget reservation, model policy and launch accounting behind the actual shared execution boundary, covering managers, workers, reviewers and supervisors. Reserve capacity/budget before concurrent launches; reconcile actual usage afterward.
- **What it would cost or lose:** Central integration work and conservative reservations when costs are uncertain. Honest hard ceilings may temporarily refuse otherwise useful work.
- **Confidence:** High.

**#6 — Over-simplification: A dollar budget cannot replace delegated authority.**

- **Reasoning from first principles:** Permission to spend does not determine permission to change scope, publish, deploy or alter protected resources.
- **Evidence:** `06:55–57` replaces authority ceremony and per-task admission with project approval and budget. Existing admission also protects exact reviewed task revisions, and dispatch rechecks that revision immediately before launch (`src/herzchen/domains/work/module.py:501–537`; `src/herzchen/fleet/dispatch.py:126–136`).
- **Recommendation:** Replace repetitive human admission with a project mandate: allowed outcomes, repositories, effects, spending and reserved decisions. Let managers authorize tasks within it. Retain revision checks and explicit approval for changes outside the mandate.
- **What it would cost or lose:** A small authorization model remains. This sacrifices some apparent simplicity but removes the human bottleneck without deleting its useful protections.
- **Confidence:** High.

**#7 — Under-trusting agents: The worker interface must support diagnosis and recovery, not merely editing.**

- **Reasoning from first principles:** Trusting agents requires giving them enough capability to complete ordinary work without bouncing problems upstairs.
- **Evidence:** The declared Claude worker profile allows `task`, `check`, `done`, omits `ask`, and caps turns at eight (`src/otto/agents/claude_adapter.py:35–40`). Its built-in tools exclude shell commands (`src/herzchen/fleet/hosts/claude.py:25–27`). The proposed four-tool workflow therefore requires a substantive capability change.
- **Recommendation:** Prove a complete worker journey: inspect, diagnose, edit, check, ask, receive an answer and continue. Provide bounded diagnostic execution or a sufficiently capable check interface. Make turn allowances appropriate to the task.
- **What it would cost or lose:** More execution capability increases the importance of workspace isolation and resource limits.
- **Confidence:** High on the interface gap; medium on the best replacement.

**#8 — Causal diagnosis: Instructions fixed a real failure; the evidence does not make every failure an instruction defect.**

- **Reasoning from first principles:** Correcting the wrong layer creates supervision overhead without improving delivery.
- **Evidence:** The manager explicitly followed a stop-and-reschedule pacing rule (`data/main-full.txt:5989`). After correction it canceled the wake-up and launched three tasks immediately (`data/mgr1-digest.txt:119–134`). Conversely, the missing installed client prevented dispatch independently of manager judgment (`ops/requests.md:1810`).
- **Recommendation:** Diagnose failures as contradictory guidance, unavailable capability, stale state, execution failure or judgment error. Fix the relevant layer. Reject `06:48`’s assertion that inability to run with Haiku necessarily means the instructions are wrong.
- **What it would cost or lose:** Diagnosis takes more effort than adding another rule. Cheap managers remain the default hypothesis, not a guaranteed architectural property.
- **Confidence:** High.

**#9 — Communication: One message interface is sensible; delivery, authority and resolution still need distinct meanings.**

- **Reasoning from first principles:** A warning being written is different from its recipient being awakened, understanding it or resolving it.
- **Evidence:** `06:33,70` proposes generic messages and files. Existing manager guidance explicitly warns that final text or a local Markdown file is not submission and requires delivery evidence (`otto/skills/otto/references/manager.md:93–102`). Turning off hourly review left the owner told that nothing would notify them of completion (`data/main-full.txt:8939–8944`).
- **Recommendation:** Use one interface with message identity, recipient role, related task, reply linkage and resolution state. Provide delivery/wake adapters, deduplication and deadlines for required replies. Authenticate owner decisions; a `kind: decision` field must not confer authority.
- **What it would cost or lose:** The transport remains more complicated than writing files. Keep those details out of normal briefs.
- **Confidence:** High.

**#10 — Runaway reviews: Risk-based review still needs a stopping rule independent of available money.**

- **Reasoning from first principles:** A project can spend its entire budget on locally reasonable reviews without converging on delivery.
- **Evidence:** `06:58` replaces call caps and fixed trees with budget plus risk policy. The D19 watcher can repeat reviews after SEND BACK (`ops/d19_watch.py:68–86`). Its instructions also encode questionable doctrine—such as rejecting timers—as mandatory review criteria (`:29`); deadline removal was explicitly ordered in `ops/requests.md:1534`.
- **Recommendation:** Give each review a specific uncertainty to resolve. Separate blockers from improvements; re-review changed risks rather than reopening everything. When the same issue recurs without new evidence, require a supervisor decision to simplify, defer or stop. Preserve genuine blockers even when a round limit is reached.
- **What it would cost or lose:** Some worthwhile refinements will be deferred, and the supervisor must exercise judgment.
- **Confidence:** High.

**#11 — Guarantee to retain: Batch integration should remove repeated work, not remove qualification.**

- **Reasoning from first principles:** Throughput matters only when the integrated result remains trustworthy.
- **Evidence:** A landing gate requeued roughly 130 times and SESSIONFD waited over 17 minutes for one file’s slot (`ops/requests.md:1640–1642`). A later batch landed 18 tasks with no new suite failures and stages 0–1 passing (`:1678`). Stage 2 subsequently hung on canon (`:1807–1810`).
- **Recommendation:** Use focused task checks and batch integration where appropriate. Preserve qualification of the relevant integrated user path, exact candidate identity, failure attribution and recovery. Delegate integration execution to the manager or its worker; the successful experiment depended on orchestrator-operated integration (`:1669,1680`).
- **What it would cost or lose:** Batches create rebase and attribution work. The archive supports a throughput benefit, not a controlled speedup estimate or universal batching rule.
- **Confidence:** High.

**#12 — Verification strategy: Test briefs and supervision against observed behavior, not only plausible scenarios.**

- **Reasoning from first principles:** The cheapest control is the one that catches consequential mistakes without making every action a review ceremony.
- **Evidence:** `06:44,71` proposes five behavioral scenarios but supplies no evaluated results. Supervision is not entirely untried: Otto already configured four Haiku helpers per check-in (`ops/STATUS.log:36`), and Astrid’s pacing correction had an observable effect.
- **Recommendation:** Trial the following methods with recorded catches, false alarms, delay and total cost:

| Method | What it would catch | Cost or limitation |
|---|---|---|
| Behavioral replay of real incidents | Bad cadence, obsolete policy, wrong-baseline choices | Small model-call suite; canned success does not prove live competence |
| End-to-end canary after setup changes | Missing client, unusable tools, broken ask/resume and completion delivery | Requires representative environment and cleanup |
| Self-report plus sampled artifact checks | Unsupported “done,” stale snapshots, concealed gaps | Cheap sampling misses unsampled defects |
| AI supervisor reading exceptions and recent changes | Repeated mistakes, unexplained waits, poor sequencing | Model cost, false nudges and possible supervisory loops |
| Targeted manager peer review | Cross-project conflicts and inconsistent assumptions | Interrupts another manager; peers may share blind spots |
| Outcome-based qualification | A compliant process delivering a broken user journey | More expensive and environment-dependent |

- **What it would cost or lose:** An initial experiment and measurement effort. Do not start with both universal hourly AI sweeps and duplicate orchestrator sweeps.
- **Confidence:** Medium; these are proposed trials, not demonstrated improvements.

**#13 — Over-structuring: Keep a small compulsory core; make the rest guidance.**

- **Reasoning from first principles:** Every compulsory field or ritual consumes attention and creates another way to appear compliant without making progress.
- **Evidence:** `retro/03-minimal-structure.md:46–63` calls its difficulty rubric judgment rather than formula, then assigns numeric scores and automatic escalation. The same document says not to build a numeric formula before calibration (`:130`). Otto’s generic worker guide carries detailed Events, accounting and Evidence-product rules (`otto/skills/otto/references/worker.md:12–31`).
- **Recommendation:** Require outcome/scope, current inputs, next responsibility and evidence/gaps. Deliver domain instructions only when relevant. Keep the owner’s tiers, but classify using the actual difficult invariant and calibrate from outcomes. Treat checklists and numeric thresholds as configurable aids.
- **What it would cost or lose:** Less uniformity and more judgment. Templates remain useful for inexperienced or newly rotated agents.
- **Confidence:** High on the contradictions; medium on the minimum sufficient brief.

**#14 — Over-enforcement: “Enforce it or delete it” discards useful judgment guidance.**

- **Reasoning from first principles:** Scope discipline, elegance and sensible escalation cannot all be reduced to deterministic predicates.
- **Evidence:** `06:44` demands enforcement or deletion. Yet the owner explicitly wanted the orchestrator to judge direction, efficiency and unnecessary work (`data/user-messages.txt:343`). The current proposal also asks managers to decide what to split and accept (`06:16`).
- **Recommendation:** Separate hard constraints, mechanically observable obligations and judgment guidance. Enforce the first; check the second; assess the third through outcomes and selective review. Prototype turn-end warnings in observation mode before making them blocking.
- **What it would cost or lose:** No promise of complete machine enforcement. Judgment errors remain possible, but fewer legitimate actions are blocked by brittle rules.
- **Confidence:** High.

**#15 — Architecture: Prove a useful operational slice before making Git storage or layer consolidation the foundation.**

- **Reasoning from first principles:** Neither fewer modules nor a portable store is itself a management outcome. A large migration can reproduce the previous program’s distance from usable delivery.
- **Evidence:** `06:54,73` proposes merging Herzchen and making Git storage foundational. The archive ends with a failed stage-2 check and unresolved integration work (`ops/requests.md:1819–1824`). Its false-landing incident shows that a branch and a log line alone do not establish completed shared state (`:218–220`).
- **Recommendation:** First run one project through manager dispatch, worker execution, ask/reply, verification, publication and recovery from interruption. Reuse existing reliable parts. Test remote concurrency, wake-up and durability requirements before selecting the base store. Consolidate modules where it removes demonstrated maintenance burden.
- **What it would cost or lose:** Architectural cleanup and broad portability arrive later; some temporary adapters remain.
- **Confidence:** High on sequencing; medium on the eventual architecture.

**#16 — Owner control: Reducing compulsory intervention must not restrict voluntary steering.**

- **Reasoning from first principles:** The tool should remove status chasing while preserving the owner’s ability to inspect, redirect, pause and change constraints.
- **Evidence:** `06:38,47` limits the owner to approval, decisions and digest, treating anything else as failure. The owner legitimately changed worker models for available credits (`data/user-messages.txt:353`), changed delivery arrangements (`:381,395`) and stopped hourly review (`:405`).
- **Recommendation:** Define success as *no unnecessary owner intervention*. Offer optional drill-down, steering and pause controls through the same interface. Apply policy changes explicitly to affected future or active work instead of relying on refreshed prose alone.
- **What it would cost or lose:** A slightly broader interface and explicit policy-change handling.
- **Confidence:** High.

**The best end state**

A thin management system around capable agents.

The owner sets an outcome, delegated scope, acceptance requirements and budget. The manager owns task selection, dispatch, integration and acceptance within that mandate. The orchestrator handles cross-project priorities, exceptions and judgment; it does not become the integration operator.

One durable task/run record connects intent, current responsibility, dependencies, actual execution and evidence. Tools record their own effects. Status and handoffs derive from those records, with timestamps and explicit unknowns.

A small execution boundary enforces scope, model policy, capacity and spending. Workers receive relevant knowledge and enough diagnostic capability to finish their work. Exact revisions and check provenance remain tool guarantees.

One message interface supports questions, corrections, decisions and escalation. It reliably wakes recipients and tracks unresolved replies. Completion events wake managers automatically; managers still decide what to dispatch. An independent monitor detects missing starts, interrupted runs and overdue dependencies.

Turn-end checks catch obvious contradictions without preventing legitimate waiting or handoff. Semantic claims receive sampled verification. Relevant user journeys receive actual qualification.

Briefs are tested against replayed incidents and a small live canary. Supervisors inspect exceptions and samples; their value is measured before adding recurring sweeps.

Build and evaluate this on one real project before restructuring Otto. Measure verified completion time, avoidable owner interventions, unattended stalls, false alarms, rework and total supervision cost—not merely task counts or rule compliance.

**Questions to answer before building**

1. What single real project will demonstrate success, and which user-visible outcomes must be verified?
2. Which decisions and effects can managers authorize independently, including integration, publication and accepting verification gaps?
3. Which environments must work first, and what facilities actually persist, wake agents and observe interrupted execution there?
4. What maximum unattended delay is acceptable for failed starts, unanswered questions and stalled work?
5. What measured improvement would justify keeping a new control—and what result would make you remove it?
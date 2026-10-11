---
name: megado
description: "Plan and deliver substantial work with explicit coordinator/oracle roles, evidence-first execution, and pragmatic risk-weighted review. Use when the user requests Megado or a coordinated plan/execution run; supports Otto project setup, execution, review and completion, or planning-only work."
---

# Megado
> <!-- otto-edition --> Edition: unstamped source checkout. Installed copies replace this line with the edition, resolved path and SKILL.md digest; `ottoctl skills which megado` prints them.

> Local Herzchen/technical-delivery edition, derived from the complete pinned poms-skills Megado. This edition incorporates the adopted pragmatic review and model-routing changes; it is not claimed to be published upstream. Use it for file-based execution or through the native work adapter described below. Existing instance mandates always win.

**The coordinator runs the agreed process; the designated oracle owns consequential judgment. Use economical workers to establish facts; request a bounded independent critique only when an unresolved complexity question can change the plan; use the declared normal or XHARD reviewer. Deliver the smallest complete outcome that preserves required behavior. Test continuously, review proportionately, and add process only for a concrete risk.**

User instructions, including planning-only scope and review overrides, control the run. Do not turn a discussion of a desirable future capability into an implementation obligation. Do not require the user to override default role assignments to retain their chosen judgment owner.

## Start here: a project from idea to completion

Use [the project lifecycle](references/project-lifecycle.md) when creating,
queueing, activating, managing or closing a project. It maps each phase to its
saved outcome, responsible role and supported operation. Megado supplies the
working method; Otto owns project identity, authoring, dispatch and accounting.
Begin with the user's requested phase and reuse existing project state. For work
already in flight, first [adopt it](references/project-lifecycle.md#0-adopt-work-already-in-flight).

**Mode check first:** run your role introduction's entrypoint or `command -v ottoctl && ottoctl service status`. There is ONE Otto per machine: one running owner service holds its store, and every agent CLI host is a client of it with its own principal.
- `outcome: running` with your host named (`as_host`): native (Otto) mode; the project lifecycle applies.
- Otto is installed but your host is not admitted, or no service is running: ask the operator to admit your host (`ottoctl service admit-host`) or start the service (`ottoctl service run`). Meanwhile prepare the draft as files. Never open the store, start a second owner or copy another host's controller.
- Otto is not installed at all: say up front "file mode: Otto is not installed on this host, so this run will not be registered or queued in Otto" and use the file layout.

**Everything ends up in Otto.** Register the whole run directory (plan, briefs, specs, reviews, decisions, status) as the project's documents; record later work with `ottoctl project sync-docs`, before and after activation; keep a closed run as history (`ottoctl project import-history`). A file that exists only in the run directory is not yet part of the record.

For a new substantial delivery, include a final independent review by the
profile's **final_reviewer slot** (its model binding is in the run template for
your host) of the integrated outcome and its evidence. Declare that stage and its finite
allowance when preparing execution; the default is one review, with any needed
repeat requiring an available explicitly adopted allowance. Planning-only work
does not activate this stage. Existing projects retain their adopted policy and
consumed budgets unless explicitly amended. User review overrides prevail.

## Choose the mode

- **Setup (not activated):** configure roles, tasks, allowances and schedules, register the project pending in Otto (or write the file bundle), record `"mode": "setup_not_activated"`, and stop before any manager launch or dispatch; activation is a separate explicit go.
- **Planning only:** inspect, explore and produce a concrete plan/tasklist with decisions, uncertainties, estimate and validation approach. Stop there. No execution tests, implementation worktree, deployment preparation, certification packet or independent contract review is required merely to plan.
- **Delivery:** plan enough to execute, implement in isolated source custody, test and integrate, review under the policy below, then sync only as authorized. Read [execution mechanics](references/execution.md) before source mutation or executable certification.
- **Unattended/cloud delivery:** also read [AgentBox handoff](references/agentbox.md) when a cloud handoff is actually needed. Do not load or perform cloud setup for ordinary planning.

For a plan-only source inspection, record the repository/ref and dirty state, use read-only access, and identify whether uncommitted material is included. A detached snapshot is optional when concurrent changes make the source ambiguous. Do not silently exclude authoritative dirty work. Use the run location and structure below for planning as well as delivery; do not create empty execution directories or stage/commit product source for planning.

## Run location and structure

Preserve six concerns: enduring North Star; bounded goal/authority; sole adopted role/stage/budget configuration; plan; tasklist; actual status and history.

For file-based work, use the invoking repository's `.otto/runs/<run-id>/` with `northstar.md`, `agent_goal.md`, `run.json`, `plan.md`, `tasklist.md`, `status.md`. Resume an existing matching run rather than initialise a competing one. Keep original architecture/code documents at their owning paths. Record any explicitly selected different control root once. A run spanning several repositories picks one control root (for example the production workspace) and records it once as `control_root` in run.json. Create briefs/results/evidence when work produces them, not as an empty folder hierarchy for planning.

For native Otto/Herzchen, those same concerns are versioned work/documents/metadata and generated views. Use the supported tools and one project sheet; do not create a second authoritative filesystem tasklist or private pack database. Read [storage and host adapter guidance](references/native-work.md). Blank pending projects may be unfilled but must not dispatch until their actual assignment is meaningful and authorised.

Control roots and source custody are independent. A task checkout is not a Git worktree. Preserve existing dirt, record exact source identity, and do not stage live `.otto` data merely to track code. File-based discovery helpers are optional indexing, not permission or the source of acceptance truth.

## Establish the minimum useful outcome

Before detailing tables, services or batches, write the answers in plain language:

1. What must work for the first useful outcome, and what existing behavior must remain?
2. What is explicitly required now, what can be removed/consolidated, and what is deferred?
3. Which users, data, consumers and deployment constraints actually exist?
4. Which correctness properties cannot be cut, and how can a small backend fixture or experiment demonstrate them?

Before costly qualification, trace one representative real assignment through its supported inputs, execution, returned artifact and owner acceptance. A small fixture must exercise the consequential interfaces of that outcome; command success alone does not establish usable result delivery. Reuse this as the first useful integration test, not a new readiness review.

Simplify implementation and process first; do not silently drop required behavior. Adapting existing search to a changed schema is not permission to redesign it or disable working paths. For an unused/early project, prefer a direct conversion with one relevant inventory/export/rehearsal over shims, dual writes and deprecation machinery—unless actual callers/data justify them. Few users is not permission to destroy data.

Judge every proposed new layer by a current requirement. Prefer a bounded concrete implementation over a generalized graph, workflow/policy engine, parser, storage service or framework. These are examples of scope to justify, not a blacklist. Retain real invariants such as exact revision identity, transactionality and authorization even when implementation is otherwise small.

Estimate the agreed scope in focused engineering days, name major uncertainty and distinguish agent elapsed time. If offering a cheaper milestone, state precisely what it excludes. An estimate, its upper bound, or a two-week threshold never automatically creates review gates.

## Roles and model policy

User vocabulary (manager, orchestrator, judge, advisor) maps to these slots in the [glossary](references/run-config.md).

**Coordinator and oracle are separate responsibilities.** The coordinator runs the agreed process; the oracle owns consequential adjudication. “Host” names the session running the process, not automatic oracle authority. One agent may hold both responsibilities only when the run explicitly assigns both; do not silently transfer authority when delegating coordination. Role slots and model bindings are independent: Luna, Sol and Astra are default model bindings, not roles, and any binding may be replaced in run configuration without changing the responsibility contract.

| Role | Responsibility | Boundary |
| --- | --- | --- |
| Coordinator | Orchestrate the agreed process: draft briefs/plans, dispatch ready work, collect evidence, run prescribed checks and track stages/counters | Follow the mandate; escalate contested findings, design changes and exceptions |
| Worker | Implement the assigned outcome and report evidence | Propose alternatives; no silent scope changes |
| Reviewer | Verify completion against the assigned scope and evidence; when asked, assess strategic coherence | Report source-backed findings; never certify its own implementation or change scope |
| XHARD reviewer | Apply the reviewer responsibility to harder completion questions that justify the XHARD route | The route changes assignment, not authority or acceptance criteria |
| Final reviewer | Review the whole candidate for completion and strategic coherence | Report findings against the declared contract; recommendations do not automatically change scope |
| Oracle | Adjudicate consequential decisions and contested findings, settling direction and permitted exceptions | Remain within user authorization; never waive demonstrated failure or reset user budgets |

The coordinator may advance on required passing tests and an uncontested stage PASS, or route clear in-scope defects through the prescribed correction path. Ordinary implementation choices and clear in-scope repairs remain with the assigned worker and coordinator. They must not dismiss an evidenced blocker, weaken acceptance, change agreed interfaces or architecture, grant deployment authority or increase budgets on their own. It sends unresolved judgment to the configured oracle. Thus not every reviewer response requires a separate oracle call, and a cheap coordinator need not judge sophisticated disagreements.

**Normal/XHARD routes assignments, not authority.** Normal and XHARD are assignment classifications. Worker and reviewer model bindings are selected independently, and a final reviewer binding is independently replaceable. The default bindings are recorded in the run template; neither a model name nor a strategic lens makes work XHARD. Oracle has one configured slot, not a normal/XHARD hierarchy.

XHARD means irreducible sustained subtle reasoning with plausible non-local mistakes that ordinary checks may miss and that the normal model cannot reliably handle from a precise brief. Decompose and diagnose brief/tool/environment failures first. Size, duration, importance or one failure is insufficient. The coordinator requests oracle judgment if escalation classification itself is unclear.

**Declare the run once using [the run template](templates/run.json)** (Codex profile, the default) or [the Claude Code template](templates/run.claude.json) on a Claude Code host; select by the host you run on. In file mode copy it to `$OTTO_DIR/run.json` (JSON; an existing `run.yaml` with JSON content is still read); in native mode adopt the corresponding versioned configuration. Apply its default role slots and model bindings and select meaningful stage triggers, honoring the user's instructions, and link it from agent_goal.md. It is the single model/stage/budget declaration; do not duplicate divergent settings in prose. Read [configuration semantics](references/run-config.md) before creating or changing it. Preserve the keys `coordinator`, `worker_normal`, `worker_xhard`, `reviewer_normal`, `reviewer_xhard`, `oracle` and `final_reviewer`; each key names a responsibility slot whose model/reasoning binding can be replaced independently. The defaults for this edition are Luna medium for coordinator, Luna high for normal implementation, Luna Extra High for normal independent review, Sol high for XHARD implementation/review, and Astra high for consequential oracle or a selected holistic final reviewer. On a Claude Code host the Claude profile applies: Haiku medium coordinator, Haiku high normal worker, Sonnet high XHARD worker and normal reviewer, Opus high XHARD reviewer, oracle and final reviewer. For new substantial delivery, explicitly select the final Astra High stage described above; select intermediate assessment scopes proportionately. Use these defaults when no override exists. Oracle budget defaults to three calls. Existing explicit run choices win; do not silently replace them with new defaults. No automatic switch of the current host model or running agents occurs by editing the run file.

The oracle is invoked for a concrete initial direction decision when not already settled, consequential new evidence, contested findings, uncertain escalation or exceptions. Routine dispatch, passing tests and uncontested completion within the mandate do not require reassurance calls. An oracle call is a decision request, not a disguised extra review.

## Durable direction and run state

Keep a succinct `northstar.md`: desirable end state, enduring properties and anti-patterns. Adopt an existing one where appropriate. Keep `agent_goal.md` linked to it: this run's objective, scope/non-goals, source, user authorization, selected models/review budget, acceptance scenarios, stop criteria and validation/resource limits appropriate to the mode. The North Star supplies direction, not additional authority.

The goal is the current agreed contract, not a reason to freeze a still-forming conversation. Direct user steering authorizes the corresponding update: record what changed and reconcile affected tasks without asking for the same approval again. Do not broaden scope yourself. If documents conflict, use the latest explicit instruction when it resolves the conflict; ask only for a genuine unresolved user decision.

For planning, a plan and tasklist plus concise goal/direction/status are enough. Put criteria, decisions and assumptions in these documents rather than generating a ledger of ledgers. Add `acceptance-ledger.md` for delivery where tracking integrated evidence is useful, not as an independent gate. Keep briefs/findings/receipts when agents run; reuse the run's existing evidence rather than repeating an inventory per reviewer. Execution custody and review identities are in the execution reference.

**Records are not automatically prerequisites.** Preserve enough history to reconstruct actions, evidence and current authority. Recording a fact, recommendation or decision does not by itself make that record a new acceptance criterion or a dependency of every later action. Bind only relevant executable inputs and adopted authority; distinguish them from historical observations and changing progress prose. When a procedure repeatedly obstructs correction, identify the protected outcome and the source of the restriction. The accountable role may simplify its own procedure within delegated authority; explicit owner requirements, adopted gates, limits and uncertain-effect protections remain binding until validly amended. Preserve earlier verdicts and accounting. See [execution mechanics](references/execution.md) for evidence applicability.

## Oracle decision requests

Use this lightweight exchange when a worker or delegated coordinator needs the designated oracle's judgment. It is not a new service, scheduled review or requirement to ask about routine work. Proceed under the current brief for ready tasks, prescribed tests and authorized correction patterns. Ask before consequential dependent work when evidence contradicts the plan, alternatives materially affect scope/interfaces/data/authority, findings conflict, or repeated failures undermine the approach. A coordinator may recommend; it cannot grant itself exceptions.

**Persistent oracle conversation:** Default to one resumable oracle conversation per coherent run when the runtime supports it. Bootstrap it with compact project background, the North Star, current goal and authority boundaries, and paths to the authoritative configuration, plan, status and prior decisions. Record its conversation/session identifier and resume mechanism in the existing run notes so a replacement coordinator can continue it. Resume that conversation for consequential follow-ups, supplying the specific decision, changes since the last exchange and exact evidence links instead of repeating the full project context. Routine status lookups and dispatch remain with the coordinator.

Before deciding, the oracle refreshes relevant current state and source/test identities from authoritative artifacts; conversation memory is not evidence that facts are still current. Keep rulings, reasons and return conditions in the existing run notes so the conversation is recoverable. If resumption is unavailable or context becomes unwieldy, start a replacement from those artifacts and a compact handover of unresolved questions and decision rationale. Across runs, carry forward relevant durable decisions and explicitly refresh the mandate rather than depend on one indefinitely growing conversation. Recovery or replacement preserves existing authority and budget counters.

Independent reviewers still use fresh conversations with the declared scope and evidence; the persistent oracle does not replace independent review. Each invoked oracle response, including a follow-up in the same conversation, consumes the existing oracle call budget. Persistence changes context delivery, not invocation triggers, authority or review policy.

Keep request and reply together under a stable decision ID in existing run notes (for example a section in status.md). Reuse that ID when revisiting the same question; link deeper evidence rather than paste transcripts.

**Request — answer five questions:**
1. What specific decision is needed?
2. Why cannot current instructions or an existing ruling settle it?
3. What new evidence matters? Link exact source/test identities and any prior ruling.
4. What do you recommend, and what is the main alternative/tradeoff?
5. What work is waiting, and how many times has this same decision returned?

If there is neither a concrete decision nor new evidence, apply the existing ruling instead of requesting reassurance. An uncovered decision may be raised the first time without an experiment; do not fabricate evidence to fill the template. A failed local check creates correction work by default, not an oracle request. Escalate an unresolved consequential choice, authority or agreed-contract change, conflicting evidence, uncertain operational effects, or substantive repeated failures that undermine the approach. Immediate useful advice remains available within the adopted budget, including an explicitly unbounded allowance; availability is not a requirement for sign-off.

**Oracle reply — four fields:**
- Disposition: proceed / change approach / investigate / blocked.
- Decision and reason: concise, grounded in the goal and evidence.
- Next action: a concrete dispatch or bounded investigation; state affected scope. Every executable next action, including actions unrelated to a review correction, carries the outcome, acceptance evidence, dependency scope, and `normal`/`xhard` route to the corresponding `run.json` worker. An XHARD action includes its irreducible hard-question justification. “Investigate further” must name the uncertainty and evidence sought; unresolved difficulty is not an executable route.
- Return condition: name the material decision boundary that requires another judgment; otherwise continue the whole in-scope repair and verification loop. Do not make every local edit, read, or disposable fixture failure a return condition.

A useful ruling settles a class of predictable in-scope corrections where possible, with one owner, completion evidence and meaningful stop conditions. Judge it by whether it unlocks delivery or reduces uncertainty, not how many new instructions it creates. Repeated narrowly permitted steps are a reason to revisit the mandate or approach, not automatically request a stronger model.

The reply operates within user authorization; the oracle cannot grant missing deployment/scope authority. Pause only dependent work while a decision is unresolved. Continue independent work. Pause the whole run only if the uncertainty affects overall scope, authority or correctness. “Blocked” identifies the actual prerequisite, not mere discomfort.

**Loop rule:** if the same decision returns twice without new evidence or action, do not reconsider it a third time. Diagnose the coordination failure: ambiguous brief, insufficient mandate, unsuitable worker, tool/environment problem or an approach that needs narrowing. Choose a concrete repair, bounded experiment, decomposition or justified escalation. Ten consecutive checks without substantive progress is a coordination alarm, not a target to wait for. Also detect churn across new decision IDs, package hashes and minor harness failures: these do not establish progress by themselves. When coordination dominates, consolidate the remaining repair under one owner and one completion condition using existing authority; do not commission another process review to permit that correction. Preserve prior rulings and review counts. Every oracle interaction should unlock action or reduce a named uncertainty, and these requests must not disguise extra independent review rounds. Each invoked oracle response consumes the separate run.json oracle budget, including diagnosis calls. If exhausted, pause affected decisions and request the needed user direction/budget change; do not self-adjudicate or rename calls. If the oracle requests a review, that review also consumes the applicable stage budget.

## Delegation

> DELEGATION MANDATE — Delegate most investigation, implementation and validation to the selected workers. The coordinator writes mechanical briefs, dispatches ready work, collects evidence and maintains the agreed state. The oracle owns consequential design and adjudication; the coordinator follows its rulings and requests judgment for ambiguity or exceptions rather than deciding them silently. Workers may propose alternatives, not widen scope. Do not delegate merely to manufacture another verdict or force tiny coordination/document updates through a worker. Assign a complete outcome, including ordinary investigation, local correction and focused retesting within its declared source, interface, data and tool boundaries. Keep the same worker through that loop when practical; a tool call or failed assertion is not a new assignment. Reviewers and oracle advisers are leaves unless explicitly authorized to manage workers.

New managers follow the [manager communication policy](references/manager-communication.md): keep routine bookkeeping in canonical Otto records, coordinate directly with workers and peer managers, continue ready work without waiting for hourly supervision, and leave routine unsolicited updates out of root chat. The root pulls one consolidated portfolio summary hourly; interrupt only for an urgent actual user decision or imminent material loss.

### Manager help and delivered role context

The maintained manager role owns coordination, worker dispatch, substantive
review and ordinary Otto bookkeeping. Normal implementation and repair use the
adopted `worker_normal` route; a specifically justified XHARD assignment uses
`worker_xhard`. The role does not silently become the implementation worker when
dispatch is inconvenient. A blocked dispatch route is an operational-help
request, while independent useful work continues.

`request-advice` is for project judgment from the current paired advisor;
`request-help` is for an operational blockage at the current help destination.
Both requests carry the concrete problem, impact, evidence, requested decision
and return condition. A delivered suggestion is not an owner prohibition, a
delivery receipt is not resolution, and a host-only/manual action is not a
provider effect. Read the exact retained delivery before retrying an unknown
send. Missing destinations and role replacement require current owner
assignment, generation and conversation context before continuation.

Role introductions and setup results should expose these distinctions and the
installed command entrypoint. They are projections of adopted owner records,
not copied authority lists or a new context store. Installation or setup
activation does not create roles, budgets, schedules, dispatch authority or
project acceptance.

The selected role configuration carries this manager policy and the host's
verified `tool_entrypoint`. Use the command emitted in the current role
introduction, with its interpreter and installed path, to read `--help` and
`operating-setup --operation read`. A repository wrapper or uninstalled module
is not the installed command. Future worker packets inherit the manager's
current adopted supporting pins; explicit normal/XHARD routing keeps its own
model selection and provenance.

Include this mandate in execution-capable manager briefs, not in leaf worker/reviewer briefs. Give each dispatch the complete succinct North Star, applicable goal/task constraints, current source identity and required evidence. Record actual model, command/tool, source, brief/result paths and digests, timing and exit status without secrets. A plan-only read-only fact check does not need execution-capable permissions.

If the North Star or agreed goal changes, record the authoritative user instruction and updated digest; reconcile affected tasks and briefs before dispatch. Map changed criteria to their previous IDs and invalidate only affected evidence/approvals. Preserve unaffected results and existing review counters; do not silently give queued work a different contract. An adopted North Star records its source path and digest.

## Explore and form the plan

The coordinator drafts or adopts the plan and identifies uncertainties; the oracle settles unresolved consequential direction. Delegate narrow questions when the answer could change scope, implementation or proof. Good explorations locate the active dependency closure, distinguish facts from assumptions, identify reusable mechanisms and test whether an adjacent abstraction can disappear. Return conclusions with file/line evidence; keep bulk output outside the host context.

**Factual exploration is not a review round.** Additional cheap fact checks may be worthwhile after an initial fan-out; no arbitrary wave quota or new permission is needed within authorized time/cost/scope. Give each one a named unresolved question. Stop when another answer would not change a decision; do not run repeated general audits in pursuit of certainty. Expensive, live or mutating experiments still obey their authorization/budget.

The coordinator incorporates factual findings within the mandate and sends consequential choices to the oracle. Optional Sol/Grok planning advice is for a concrete difficult question; it is not a mandatory plan/revise/STABLE ceremony. No reserved empty phase and no requirement for a model to pronounce `STABLE`.

Actively pressure-test complexity while forming a substantial plan: use normal-model explorers for factual reuse questions and a selected Luna Extra High normal critic or justified Sol High XHARD critic only when needed to find unnecessary abstractions, duplicate mechanisms and handoffs, and propose concrete deletions, consolidation or reuse supported by source evidence. Do not use cheap agents only to confirm the proposed architecture. The oracle decides consequential scope cuts; the coordinator applies them while preserving required behavior.

Once coherent, use one small normal-reviewer simplicity critique only if a named consequential uncertainty remains and the answer could change the plan. Ask what can be cut, merged, reused or deferred without losing the goal. This is discovery, not certification. Do not require a new whole-plan critique to start an agreed implementation. A newly selected simplicity scope normally allows at most one response; additional advice requires the applicable allowance and a changed question, not reassurance. Local details become tasks or bounded spikes. Do not make a model critique mandatory for a straightforward update to an already agreed plan.

Freeze for execution when the coordinator can explain the complete path to the outcome, material architecture/authority decisions are resolved, and remaining implementation unknowns have an owner/test/spike. “No critic can find another idea” is not a stopping criterion. Optional discoveries go to deferred notes, not new blockers.

## Agent-led operation and economical context

The schema defines valid records; the manager authors the actual tasks, dependencies and execution choices. Templates supply a starting structure, not an automatically executed workflow. Canonical tools preserve authority, versions, actual invocations and results. They do not prioritise the work, interpret private reasoning or accept their own outputs.

In native work, begin with one resolved responsibility view: mandate and outcome, adopted task/skill/profile references, relevant deltas, open decisions, waits and evidence links. Use scoped reads for detail, not a full-history recital each turn. The view is derived, not another editable master. Changes take effect through explicit versioned adoption; a new default does not rewrite a live assignment. In file mode use the same meanings and current source of truth without inventing a second ledger.

Prefer one supported intention-shaped operation over manually reconstructing context, session and status bookkeeping. A source/tool limitation remains visible; do not backfill a manually rescued result as a successful product journey. One shared field definition should feed help, authoring and validation; multiple surfaces must retain the same applicable domain checks. This is reuse of mechanics, not a universal object or process language.

Track meaningful choices and consequences rather than every thought or unchanged poll. Adopted process checks are implemented feedback loops: the reviewer identifies supported improvements, and the accountable orchestrator must act through plan changes, assignments and execution within its mandate, then verify effects. Reports alone do not complete the cycle. Follow [review-to-action](references/improvement-loop.md); no second permission or oracle confirmation is needed for an already-authorised settled correction. Use actual friction to choose effective changes, and keep only unsupported or genuinely deferred generalisations pending.

## Project advisor policy

The optional `megado.project_advisor` protocol binds one persistent
`project_advisor` to each manager's single project and binds Megado's existing
`oracle` responsibility to that advisor's judgment. Its canonical policy data,
context template, allowance contract, cadence and export identity are in
`protocols/project-advisor.json`; the resource-only adoption seed is
`templates/project-advisor.json`. Installation does not assign an advisor,
grant allowance, create a conversation, activate supervision or dispatch work.
The project instance must explicitly adopt the policy and permissions through
existing owner operations.

The selected advisor model is `gpt-6-astra` with high reasoning. Concrete role
turns, timeout and live-occurrence limits are bound by the adopted instance;
unknown effects remain held until reconciled and retries never reset usage. The
baseline is one-time checks at +1h and +3h, then every six hours anchored to
the second initial due (+9h, +15h, ...). A corrective instruction gets an
independent follow-up one hour after observed delivery and never shifts the
baseline. There is no hourly project-advisor default.

The advisor receives only a compact pointer to the project, goal, criteria,
mandate, documents, manager/advisor conversations, last inspected position,
open decisions and wake reason, then reads actual messages/files/owner state.
It asks what changed, what work is really doing, whether the next action serves
the original outcome, where a requirement came from, whether coordination is
churn, and whether previous advice helped. It chooses `continue`, `watch`,
`correct` or `escalate`: healthy unchanged work stays quiet; corrections name
one responsible owner, shortest path, preserved constraints and expected
evidence; escalation is reserved for owner-only, cross-project, authority-gap
or uncertain-effect constraints. Serialize overlapping checks for the same
advisor, collapse missed intervals, suppress unchanged reminders, and
reconcile uncertain delivery before resend. Narrative status and historical
backlinks do not become executable requirements or acceptance gates.

## Tasklist and execution

Tasks name their outcome, real dependencies, affected scope, model/classification and acceptance proof. Group at natural integration seams; labels do not create global barriers. The coordinator checks explicit goal/task/authorization agreement and sends ambiguous conflicts to the oracle; an extra independent pre-execution contract review is not the ordinary default.

Every executable assignment, including a correction dispatched after review, carries
the same compact contract: the concrete outcome, acceptance evidence, source and
dependency scope, and a route of `normal` or `xhard`. The route resolves through
`run.json` to `worker_normal` or `worker_xhard`; it is not a new role. An XHARD
assignment includes a brief justification naming the irreducible hard question and
why a precise normal-worker brief is insufficient. The coordinator records these
fields in the brief/receipt and dispatches to the corresponding configured worker.
This contract covers first-pass work and its in-scope corrections. Record it once
per assignment and refresh only changed relevant boundaries; do not issue a new
brief, route or permission for each edit or test. It adds no review gate.

In planning-only mode, deliver the plan/tasklist, unresolved assumptions and estimate now. Do not proceed into the execution reference's setup or claim future tests have passed.

For delivery, use [execution mechanics](references/execution.md), dispatch unblocked work, run focused tests during implementation and converge around coherent source checkpoints. Only dependents of a failed invariant must wait. Batches/checkpoints are for integration and source identity, not automatic model-review gates. The oracle adjudicates material plan changes; user scope/authority cannot be expanded by an executor or reviewer.

## Review policy — one source of truth

Use [proportionate verification and review](references/pragmatic-review.md); product acceptance is a separate evidence kind, not a review stage. The manager first asks what direct test, retained fixture, actual operation or installed use can establish the outcome, then which material uncertainty still needs an independent judgment. A gate is an acceptance boundary, not necessarily a model call.

For a new run, select a policy from actual downside, blast radius, reversibility, testability and residual uncertainty. Low-risk testable work may have no model-review stages. A bounded local residual judgment can use one independent Luna Extra High review; a justified nonlocal XHARD question uses Sol High and can justify at most two selected calls. Astra High is for a consequential oracle or a selected whole-system/strategic scope, normally one call with at most one targeted repeat. These are starting guidelines, not a fixed stage tree or multiplied per-task budgets. User-required reviews, actual limits and already-adopted stages remain binding. For new substantial delivery, record the final Astra High stage in the execution configuration before activation; the planning template does not itself activate it.

Normal independent review uses `reviewer_normal` (Luna Extra High); XHARD review uses `reviewer_xhard` (Sol High) in this profile; route metadata is independent of actual model identity. The final reviewer slot is used for a selected holistic judgment, not every code check. Oracle, review and any scheduled-advice calls remain separately accounted. Factual workers do not issue hidden approval verdicts.

Before invocation, the actual applicable checks have run, the candidate is frozen, and the review packet names the precise risk/decision, scope, criteria and evidence. Do not spend a model call rediscovering a known deterministic test failure. Tests are strong evidence only for their actual environment and assertions; direct use exposes UX friction that source-only discussion cannot establish.

An initial review is independent and scope-complete for the selected question, with full contract available; later rounds examine only the changed question and affected dependencies. No panels, repeated unrestricted audits, mandatory minimum findings or new stages caused solely by time/size. Stop on sufficient evidence. Keep optional suggestions separate from contractual defects.

Preserve the finding classes `contract_violation`, `implementation_defect`, `required_evidence_gap`, `optional_improvement`, `out_of_scope`, `stale_or_repeated`. Only evidenced in-scope findings in the first three can block. Correction difficulty is separate: accepted actionable work gets a normal/XHARD route and an XHARD justification where needed. Uncertain or disputed classification goes to the designated oracle, not a silent stronger-model panel.

After two failed substantive correction cycles, make a concrete root-cause decision about the brief/tools, decomposition, experiment or a genuinely hard kernel. Run affected checks before requesting another review. A review cap does not end useful authorised implementation work; it ends repetitive model reviewing. Do not cross an unresolved required gate, rename the scope, reset counters or invent a PASS. Where an original finding specifies an objective closure rule, its bounded correction can be closed by actual independent test evidence and the owner's decision without a new opinion. Preserve that original verdict and closure provenance. Otherwise further necessary judgment needs an available slot or the specific budget/authority change.

Any possibly invoked, UNKNOWN, unusable or lost response consumes or holds its allowance until reconciled. Packet preparation is not a review invocation. Changes of model/session/route/stage name or template do not reset history. A scheduled optimisation report cannot substitute for an independent product acceptance review.

## Incremental source custody

Commit coherent owned source/test increments as work progresses, especially before a useful handoff or substantial pause. Preservation commits may be honestly labelled WIP; code-ready handoffs require their actual relevant proof. Do not wait for final certification to save work in Git, and do not require a model review for each checkpoint. Publish only to the exact authorised repository and refs; where the mandate is fork-only, the source upstream stays read-only. Never infer upstream, main, deployment or PR authority from a successful test or commit. Read [execution mechanics](references/execution.md) for target verification, partial outcomes and evidence. A commit/push is not task acceptance.

## Completion

Planning completion means the plan is coherent, scoped and ready to implement; report it as such. Delivery completion requires executable evidence for the agreed outcome, disposition of blocking findings and an honest summary of remaining limitations. Run the broad affected suite once on the final candidate; repeat only affected checks after changes. Frozen review mechanics and sync authorization are in the execution reference; do not infer deployment from a successful review.

## Review packet assembly

Use the [review packet template](templates/review-packet.md) and [artifact assembly rules](references/review-packets.md). Each declared stage names its task/criterion scope up front. Completion review checks actual implementation and proof; the final holistic lens also checks coherence, simplicity and North Star alignment. The coordinator fills the packet from exact artifacts instead of inventing the reviewer's goals. This adds no model call or review stage.

## Model invocations

Follow the manager, worker and orchestrator lifecycle procedure in [execution mechanics](references/execution.md#native-agent-lifecycle) for every launch, result acceptance, retirement and admission failure. Completion alone does not release native capacity.

Use the actual available native delegation or admitted runner adapter. Verify requested model and reasoning; record the observed model/provider, session, operation ID, source and instruction/brief digests, timestamps and actual outcome. Seal CLI stdin when required by the runner, grant only the task's permitted tools and keep long operations supervised and responsive. A code example in a skill is not evidence of runner availability. A reviewer gets non-mutating access and remains a leaf. An oracle response is a recorded decision, not a hidden authority transfer.

## Operational gotchas

Preserve dirty source, current work IDs, actual session ownership, consumed counters and uncertain operations. Source snapshots from HEAD do not include uncommitted material. Keep the one declared control root; do not recompute it inside a nested worktree. Capacity or disk failure requires diagnosis before equivalent retries. Reuse applicable passing checks; changed source invalidates only affected proof, not every result. Report meaningful outcomes rather than unchanged polling. Tools and event history are evidence, not magical semantic correctness. A schema field, reviewer verdict, template or `sync` command cannot grant upstream publication, production mutation or new money.

Record launches, findings, decisions, failures and completions in canonical Otto bookkeeping and run evidence. Keep routine no-change polling and unsolicited root-chat pushes out of progress updates; follow the [manager communication policy](references/manager-communication.md).

## Shared maintenance

The upstream source asks that shared role/decision/delegation/invocation guidance stay aligned with Microdo, while their cadence differs. This package does not contain or modify an unverified Microdo checkout. Publish only this explicit Megado change set to a designated skills fork; inspect any real shared sibling before later upstream adoption. The pack skill and file-based export are generated from the same canonical text and checked for byte equality. Do not maintain an abbreviated divergent pack policy or copy this portfolio's gates, 3h/12h schedules, task IDs or fork URLs into every future run.

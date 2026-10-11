# Project lifecycle in Otto

## Enter at the right phase

“Explore an idea” means draft/planning work; “queue it” saves pending work;
“build it” authorizes execution within the agreed scope. Resume an existing
matching project instead of creating another identity. A project may stay a
draft indefinitely. Do not demand a complete delivery contract to capture an idea.

Megado provides the method. Otto provides canonical projects, documents,
assignments, results and reviews. In native mode the project sheet and its
versioned documents are authoritative. A checkout is an editing surface, not a
second project database. In file mode use the existing run layout in SKILL.md
and report explicitly that the draft has not been registered or queued in Otto.

## Find the actual tools first

Read the installed Otto skill (the sibling skill, [manager reference](../../otto/references/manager.md))
and your current role introduction. Use that role's exact installed entrypoint
and its `--help`, `status`, identity and effective-context reads
(`ottoctl manager --help`, `ottoctl whoami`). Never substitute another project's
controller path or another actor's credentials. Sample identities and paths in
command guides are examples, not your binding.

Creation, document check-in, enrollment and queue edits are owner operations.
In one Otto there is one running owner service; your host performs these as its
OWN principal through it: `ottoctl project register` (an inert draft with the
whole run directory), `ottoctl project sync-docs`, `ottoctl project activate`.
A manager's execution client does not expose them. If your host is not admitted
yet, the operator admits it (`ottoctl service admit-host --host <kind>
--client-home <your OTTO_HOME>`); until then prepare the same draft bundle as
files and name the missing admission. Never open the store, start a second owner
or copy a previous controller script as a new writer. Continue independent
planning.

## 0. Adopt work already in flight

Use this before step 1 when boards, branches, open agent sessions or served trees
already carry the work.

1. Inventory existing trackers: boards, branches, open agent sessions, served trees.
2. Record their exact source identities: commits, served tree, paused branches.
3. After any interrupted or rejected tool call, verify the actual effect (for
   example `git log`) instead of assuming it was undone.
4. Freeze the old tracker as history; do not keep editing it.
5. Carry every open item into the one tasklist with a `carried-from` note.
6. Diff old to new: every old open item is carried, done (with evidence) or
   dropped with a reason.

## 1. Explore and save a draft

Start with a title, the user's brief and the relevant repository or repositories.
Keep research, open questions and decisions with that same draft. Capture only
what is known; a pending identity or a local draft does not start agents, create
execution tasks or grant budgets. Use an existing blank project/template when
the authoring surface exposes one. Retain the project identity after creation
and use it for later updates. If the creation outcome is uncertain, inspect the
original operation before trying again.

## 2. Make the plan executable

Specify the desired outcome, scope/non-goals, dependencies, acceptance evidence,
source ownership and meaningful tasks. Each executable task has a normal or
XHARD route; explain the irreducible hard question for XHARD. Reuse existing
capabilities and record decisions from research rather than copying transcripts.

Resolve material uncertainty through focused exploration or a bounded complexity
review when warranted. The manager incorporates findings; planning critics do
not activate the project or silently expand it. For planning-only requests,
return the plan, remaining questions and effort estimate here.

Before delivery, bind the manager, workers, reviewers and any advisor/oracle;
select the available CLI/model defaults and finite allowances. Include one final
independent gpt-6-astra high review for new substantial delivery unless the user
chooses otherwise. Bind its scope to the integrated outcome and exact acceptance
criteria. This instruction proposes policy; the owner must adopt it through the
normal configuration path before any invocation. Do not silently add it to an
existing run or reset earlier use.

## 3. Register and queue pending work

Validate the bundle using the actual authoring schema, check in its documents,
and export/read back their exact content and refs. Reuse a partially registered
project and finish only missing operations. Report registration separately from
queueing and activation.

When queueing is requested, the owner enrolls the existing project in the
intended portfolio and updates the canonical predecessor/successor links using
current revisions. Verify the intended order and reciprocal links, plus the
adopted orchestrator direction that governs progression. A reminder's copied
list is not the canonical queue. Pending projects have no active providers or
execution pools merely because they were saved. An unqueued draft need not
acquire a predecessor or portfolio assignment.

## 4. Activate and hand off

The orchestrator checks the predecessor's actual terminal disposition and the
current project plan, subtracts already completed overlap, and adopts the
compatible installed code, skills and role context. Only then activate the
required tasks, assignments, allowances and initial manager through supported
owner operations. Verify the real manager identity and effective instructions.
A changed skill file alone does not update a live role's pinned resources.

Keep the original launch handle. Distinguish preparation, dispatch, native start
and captured result; inspect an uncertain launch rather than repeating it.
Return concrete missing setup to its owner. Do not call a queued project running
until its actual execution start is observed.

## 5. Execute, review tasks and resolve blockers

The manager uses the installed `run-worker` route and its current task bindings.
Orchestrators and coordinating workers use their own admitted canonical launch
route. All execution-capable roles receive the recipe in their adopted context;
leaf reviewers remain non-mutating and do not delegate implementation. Link
children to the real parent, project and task and retain results/artifact refs.
Use returned handles with `worker-status`/`command-status` or the corresponding
admitted follow/result commands; do not poll a turn indefinitely when it must
yield for its own completion to settle.

For each result, read `review-input` and the actual artifact, then perform the
configured assessment and ordinary task finish. A successful worker is not an
accepted task. Reviewers propose concrete corrections, classified normal/XHARD,
with evidence and acceptance checks. The manager decides disposition, enters
accepted work through normal planning, and delegates it through the same worker
path. Preserve original findings, candidate identity and consumed allowances.

Use `request-help` for an operational blockage and `request-advice` for project
judgment when these routes are configured. Include impact, evidence, responsible
owner, requested action and the condition for resuming. Verify delivery; a saved
report is not proof that the owner was notified. If delivery is unavailable,
surface the blocker through the available owner channel and name the limitation.
Continue independent ready work; do not wait for an hourly observer to discover
a known actionable block.

## 6. Final Astra review and corrections

Run the relevant integration checks and freeze the actual candidate. Assemble
one bounded packet using [the review packet](../templates/review-packet.md):
original goal, criteria, source identity, installed behavior where required,
real results, prior findings, known limitations and deferred work. Request the
adopted independent Astra High final review through the canonical review route;
verify actual model/reasoning and account for the invocation separately from
advisory checks and oracle decisions.

Ask whether the complete user journey works, requirements have evidence,
integration and instructions agree, and unnecessary complexity can be removed.
The reviewer separates contractual defects/evidence gaps from optional ideas.
It proposes corrections; the manager owns their planning and execution. Neither
reviewer nor manager may fabricate a PASS from an unavailable response.

Apply accepted corrections through ordinary tasks and workers. Recheck affected
behavior. If further independent judgment is required, use an available adopted
allowance and review the changed scope; do not reset budgets or rerun an
unrestricted audit. Preserve UNKNOWN outcomes until reconciled. An objective
closure rule already authorized by the review may be discharged by its specified
evidence and accountable decision. A final PASS is acceptance evidence, not
project closure or permission to publish.

## 7. Close, verify and advance

Resolve blocking findings, finish accepted tasks and invoke the supported
project close with truthful acceptance, publication, remote and runtime
dispositions. Discover the exact JSON shape with `finish-project --help`.
Verify `project_completion_recorded=true`, `settlement_pending=false` and the
terminal canonical lifecycle via `project-lifecycle-read`. Retain pending
settlement handles; do not repeat the finish merely because its reply is slow.

Report what was delivered, verification, artifact locations and material
limitations. Publication/deployment follows only the user's actual authority.
The orchestrator advances the canonical successor only after the predecessor's
required disposition and installed handoff are genuine. Retire project-owned
agents/schedules through their supported lifecycle; preserve unrelated work.
Pause a portfolio observer only at its configured final queue target.

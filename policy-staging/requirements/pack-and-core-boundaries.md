# Pack and core boundaries: Megado project advisors

This is the intended design, not a claim of implemented scheduling or delivery.
It refines the [work-management philosophy](agent-work-management-philosophy.md).
Keep the implementation small and reuse existing assignments, reports, due
records, host adapters and conversations.

## Responsibility comes before machinery

The **orchestrator** coordinates across projects: creating projects, allocating
managers and resolving cross-project priorities or authority conflicts.

Each **manager** has one active **project advisor**, dedicated to that manager's
project. The manager owns delivery and routine decisions. The advisor supplies
stronger judgment, answers difficult project questions and periodically checks
whether the approach is working. Within its owner-delegated mandate, it chooses
concrete corrections for the manager to execute; it does not merely forward
questions to another advisor. Required independent review remains separate.

`project_advisor` is a useful reusable responsibility, not a new service. In
Megado, the existing oracle responsibility can bind to this advisor rather than
creating a second project-level oracle. The native role bindings need deliberate
implementation; do not silently relabel today's cross-project orchestrator.

## What belongs where

| Layer | Owns | Megado example |
| --- | --- | --- |
| Core Otto | Project/manager/advisor relationships, current assignments, context references, scheduled responsibility admission and message routing. | Resume the assigned advisor and deliver its decision to the current manager. |
| Herzchen and existing owner ports | Durable assignments, reports, decisions, revisions and receipts. | Store the intervention and its observed outcome without another ledger. |
| Host/runtime | Actual timers, conversation creation/resumption and message transport. | Wake the existing advisor conversation and report delivery truthfully. |
| Megado pack | Work policy, role instructions, model/budget choices, judgment questions, cadence and review rules. | Check progress at +1h and +3h, then every 6h; follow an intervention after 1h. |
| Project instance | Goal, acceptance criteria, permissions, selected policy, assigned people/agents and actual progress. | Which project and manager this advisor serves, and what completion means. |

Core Otto understands an authorized responsibility that is due, not a special
Megado workflow. A pack supplies policy; installation alone grants no authority
and activates no schedule. Use one adopted configuration, not competing editable
copies in prompts, files and owner state.

## Start together; retain context

When deploying a manager under this policy, assign its advisor and initialize a
persistent advisor conversation. Send an introduction with the project goal,
acceptance criteria, mandate, manager conversation reference and documentation
paths. Tell the manager how to reach that advisor. Resume the same advisor for
both scheduled checks and difficult questions. Reassignment explicitly updates
the relationship; an old conversation ID must not select a stale manager.

The advisor gets a small context pointer: project and conversation references,
authoritative document locations, last inspected message/event position and
outstanding decisions. It uses ordinary tools to read messages, worker results,
files and tests itself. A “since the last check” view is a convenience, not a
prerequisite or a substitute for reading enough surrounding conversation to
understand the work. Do not generate an exhaustive evidence package every time.

Detailed introductions, experience-based questions, correction examples and
low-noise follow-up rules live in the [advisor playbook](project-advisor-playbook.md).
The project plan records the readiness dependency; this boundary document stays
focused on reusable responsibilities.

## What the advisor asks

- What changed in delivered behavior or evidence since the last check?
- What are the manager and workers actually doing, and why?
- Does the next action advance the original outcome?
- Is a blocker an original requirement, a real defect, or a restriction the
  agents introduced themselves?
- Are repeated checks, fragmented handoffs or unnecessary escalation delaying
  progress? Does the manager have enough context and authority to proceed?
- Was the previous correction implemented, did it help, and does new evidence
  require changing the advisor's own direction?

Healthy progress needs no corrective message. For a real issue, choose a bounded
action, name its owner and expected evidence, send it, then check its effect.
Acknowledgement is not implementation; one hour is a follow-up point, not an
automatic repair deadline. Keep routine coordination local. The advisor should
usually settle project questions and equip the manager to act; escalate upward
only for a genuine cross-project conflict, owner-only decision or capability or
authority gap it cannot resolve within its mandate. Never conceal a real blocker
merely to keep escalation rare.

## Minimal execution support

Reuse one-time and recurring due records and the existing host integration.
Follow-ups reference the actual intervention; they do not reset the baseline
cadence. Serialize checks for the same advisor, combine overlapping reasons,
retain a small inspection cursor, and do not resend unchanged instructions.
Reconcile uncertain delivery, collapse missed intervals after downtime, and stop
checks when the project finishes or supervision is withdrawn.

Build one real wake → advisor inspection → manager instruction → follow-up path
first. Then add the cadence and pack configuration. No new workflow engine,
warning-detector platform, issue database, transcript warehouse, or approval
stage is needed. Existing pieces still require production wiring and a focused
end-to-end test; their presence in source is not proof that the loop runs.

## Keep supervision from becoming certification machinery

The pack teaches the advisor to distinguish product guarantees from invented proof
procedures and to select complete repairs within mandate. Core enforces semantic
authority/assignment/recipient/effect boundaries, not wording in mutable progress
reports. Adopted instructions and permissions remain genuine bound inputs.
Qualify one candidate route in a bounded campaign; retain runtime checks on every
effect without creating a new model review for each occurrence. Prior or unknown
attempts are preserved. A blocked effect does not stop independent useful work.
Preserving an event or linking a report does not create a dependency or approval
gate. Core records explicit assignments, authority, evidence and actual effects;
it must not infer new requirements from narrative text or a historical backlink.
The pack teaches the advisor to assess the procedure itself, trace requirement
provenance and choose complete corrections. The project instance explicitly
adopts any consequential amendment through existing records. No new policy engine,
record type or compulsory advisor sign-off is required for this distinction.

These are required implementation behaviors, not proof that current Otto already
enforces them; see the [advisor plan](../.otto/runs/otto-project-advisor-20260930/plan.md).

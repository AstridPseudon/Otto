---
name: otto
description: "Use Otto's installed tools for identity, directions, agent delegation, project coordination and recovery."
---

# Otto

Otto owns shared records and operations. Packs such as Megado define how work
is planned and reviewed.

Use your role introduction's exact installed entrypoint. Check its help and,
where supported, `whoami` and `effective-context`. A host that is a client of
the one owner service answers `ottoctl service status`, `ottoctl whoami` and
`ottoctl projects` through its own lane. Use your own binding; never
borrow an identity or open the live database. If no binding was delivered,
use [Orchestrator setup](orchestrator-setup/SKILL.md) and the installed nonsecret `~/.otto/orchestrator-connection.json` for cold orchestrator discovery and enrollment; other roles request their binding from the responsible owner.

Read the guide relevant to your work:

- [Identity and directions](references/identity-and-directions.md)
- [Orchestrator](references/orchestrator.md)
- [Canonical queue](references/orchestrator.md#canonical-queue) for finite
  owner enrollment/publication, shared root/continuation/observer reads and holds
- [Orchestrator setup](orchestrator-setup/SKILL.md) for first-use enrollment and scoped client status
- [Manager](references/manager.md)
- [Worker](references/worker.md)
- [Evidence workflow](../../../herzchen/packs/evidence_resource_pack/skill/SKILL.md)
- [Recovery](recovery/SKILL.md) for interrupted or unknown operations
- [Retained Events operator views](references/observability.md) for bounded
  history presets and the honest initial Usage surface
- [Command details](../../../../docs/manager-journey-commands.md) for delegation,
  results, artifacts and closure
- [Host onboarding](../../../../docs/host-onboarding.md): join the one owner
  service with `ottoctl`, add a new agent CLI, register and activate a run
- [Project onboarding](../../../../docs/project-onboarding.md) for the maintained
  title-plus-brief create/find/reopen entry and its inert effect boundaries

Keep project, assignment, occurrence, result and transport handles distinct.
Inspect an uncertain original operation before retrying. Process exit, captured
result, parent consumption, task acceptance and project completion are separate.
Missing usage is unavailable, not zero; never replay work to repair telemetry.
When a retained qualified accounting facet is present, the Usage readback also
exposes physical-span deduplication, historical agent/task/project attribution,
coverage, and separate provider-reported money and versioned decimal price
estimates. It never derives tokens or money from text, duration, allowance, or
account percentages. Static rates are estimates with retained provenance, not
billing facts; actual billed status requires an attributable billing receipt.
Shared, conflicted, unsupported, unpriced, and unknown spans remain visible.
Use the original snapshot and bounded continuation/detail reads; a missing
accounting facet remains an honest availability gap and preserves legacy
attempt/result readers.

Hosts should include this index, the relevant role guide, selected pack guidance
and exact tool/binding refs in adopted role context. Verify effective context and
actual use. Installing a skill does not update existing assignments or budgets.
Use Megado's lifecycle guide for Megado projects; its review policy is not a
universal Otto requirement.

When a task needs durable claims, exact citations, managed payload checkout,
or deliberate retention, consult the adopted Evidence workflow. Use its
maintained commands and exact pins; do not require a new evidence document for
routine messages and do not infer deletion authority from project completion,
pack discovery, disable/remove, or a local materialization's absence.

## Retained Events observability

Use the existing `events` CLI family for Overview, Timeline, Agents,
Tasks/reviews, Blockers, Usage, Recovery, and selected bounded detail. Every
view is read-only and retains authorized project/date scope, coverage, lag,
snapshot, and keyset continuation. A view never executes recovery, repair,
backfill, or historical mutation advice.

## Project onboarding

Read the current [project onboarding guide](project-onboarding.md). An issued
finite onboarding client uses `python -m otto.portfolio.onboarding_bound_cli`
with its exact private host-issued descriptor. It never selects an actor or
opens Store. The generic portfolio CLI requires host-injected capabilities;
its help alone does not authenticate a caller. Production protected
owner-authoring remains its separately admitted root route. Managers use their
own delivered manager client and request owner authoring when needed; never
borrow a root descriptor. Installation and discovery do not adopt resources.
The current role's canonical BASE, selected pack and effective-context readback
are required before treating new guidance as delivered.

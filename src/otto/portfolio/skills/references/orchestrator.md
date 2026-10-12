# Orchestrator

A chat does not acquire an Otto assignment merely by existing. First read
`~/.otto/orchestrator-connection.json`, the installed nonsecret connection
locator, and use its exact client entrypoint with `discover` or unbound `status`.
If unregistered, follow [Orchestrator setup](../orchestrator-setup/SKILL.md):
request finite scope, retain the request, and await authorized owner admission.
Requests do not grant authority. Assigned identity and adopted project
supervision are separate; revoked clients cannot act.

Read your identity, effective context and portfolio mandate. Maintain the
canonical queue. For an owner-issued **same existing root** direction capability,
use its installed client `direction-read` with no project selector. `direction-draft`
takes JSON `content` and `expected_revision` and saves only. `direction-update`
takes `content`, `expected_direction_ref` and `expected_binding_ref`, using the
exact pins returned by the read and an explicit stable `--request-key`.
It derives the existing BASE and all current supervision joins on the owner lane,
then adopts them atomically. It holds while native obligations remain. After a
successful update the owner performs normal runtime requalification and issues
the current binding; inspect the retained result and fresh `direction-read` before
claiming future instruction adoption. Retain the original handle after timeout.
Ordinary scoped project clients do not gain this owner capability. Adding strategic
project references to a directive does not transfer supervision, register or
activate projects, or allocate budgets.

## Issued project-supervisor directive

When your own installed client help and issued policy include
`supervisor-direction-read`, use it with the exact supervised `--project-id`.
This reads the **manager responsibility's controlling direction**, not your
own orchestrator instruction adoption or the project-level direction binding.
Those surfaces can be unbound independently. The returned `subject_ref`,
binding, latest/effective/adopted document refs and current manager head are
the pins for this route. If this read reports first binding or missing BASE,
stop at the stated hold; this facade cannot create the missing binding.

`supervisor-direction-draft --request-key KEY --request JSON` takes exactly
`content` (the complete instruction document, preserving its constraints and
supporting refs) and `expected_revision` from that read. The canonical JSON
payload is bounded to 65536 bytes. Draft saves only; it is not adoption or
delivery. After drafting, read again and submit
`supervisor-direction-adopt-and-continue` with exactly `document_ref` from
the draft and fresh `expected_binding_ref`, `expected_direction_ref`,
`expected_manager_ref`, `expected_manager_generation`, `expected_schedule_id`.
The latter direction pin is the read's `latest_ref`. Use a distinct stable
request key for each distinct operation; retain UNKNOWN handles without resend.

This operation requires the existing manager to have settled. It atomically
adopts the bound direction and corresponding manager BASE, records its canonical
application and prepares one same-session continuation. It preserves active
workers on their immutable contracts and adds no allowance. Its delivery is
`prepared-not-started`. Start only the returned current schedule using your
existing `manager-start` with `{"schedule_id":"<returned-current-schedule>"}`.
Read retained completion and actual manager acknowledgement before claiming
consumption. The worker-result route selects this current manager head, and
merges a delayed original result into that one unstarted continuation.

This route is available only after normal owner deployment and explicit issuance
of these three operations to your existing own policy. It grants neither the
main-root direction capability nor generic `project-authoring`, package CRUD,
first binding, new supervision, activation or direct native messaging. A CLI
name or source test alone does not prove an installed handler or issued access.

Maintain the canonical queue. Registration, enrollment, queueing and activation are separate
until the installed interface explicitly combines them; recover partial setup
using the existing project.

## Canonical queue

Use the installed owner-authenticated `project-queue` command family. The host
binds one portfolio, its current root and one current DAT document locator.
Prefer the accepted locator through the owner's existing bootstrap `queue_ref`;
otherwise the portfolio has one deterministic queue document. No local sequence
or per-project transition document is an alternative authority.

`project-queue --operation read --consumer root` reads the current queue revision,
ordered project identities, continuation/pause rule and current Work lifecycle,
readiness and acceptance. Continuation uses `--consumer continuation`; existing
observers use `--consumer observer`. All three resolve that same locator on each
read. Direction/BASE and reminder prompts carry the locator plus policy rather
than a copied sequence or final project ID. Missing, inaccessible or conflicting
data is a hold. A current read does not prove terminal acceptance or activation
eligibility; use the existing final-disposition and setup readback separately.

The exact owner grant is required even for reads. Native manager or worker
credentials do not grant this host-owned operation. Request the bound owner
route if unavailable; never open Store or borrow another role's client.

For first adoption only, the owner seeds the authorized already-enrolled order
with `--operation seed --request-key KEY --order JSON --rule continue|pause`.
Seed cannot overwrite an existing queue. Order contains 1..32 distinct canonical
Work project identities; the DAT body is bounded to 8192 bytes. Existing private
DAT ownership, immutable revisions and CAS are reused. Actual transport limits
still apply to the complete envelope.

Queue-after uses `--operation after --request-key KEY --order JSON
--expected-revision REV --predecessor-ref JSON --project-ref JSON --rule RULE`.
Copy the exact prefix, revision and rule from read; the predecessor must be its
tail, and the new project must be current, pinned, inert and pending. The owner
validates the portfolio/root and distinct identities before enrollment. Preview
of existing WRK enrollment validates assignment/default pins before effects.
Already matching enrollment is reused; foreign enrollment is rejected.

Enrollment and publication commit separately. `queued=true` requires canonical
readback of both. A partial result retains child keys, receipts and exact input.
First reconcile a lost/UNKNOWN transport reply with its original handle; do not
resend an unknown effect. A committed publication is recovered by its immutable
revision and current prefix readback without another write. After an explicitly
reconciled absent publication, unchanged input/key reuses committed enrollment.
Changed input conflicts with the retained enrollment/publication digest. A
known stale CAS instead requires current queue/project readback and a new pinned
publication request; successful enrollment remains. No automatic retry or
activation occurs.

Source guidance and fixtures do not install this capability or migrate live
Direction/BASE, continuation bindings or hourly/six-hour observer prompts. Their
owner must adopt the locator, update those existing consumers through authorized
routes and verify an extension is observed without changing a second list. Keep
historical transition revisions. Unmigrated required consumers remain incomplete.

Before activating a successor, verify predecessor completion, the current plan,
accepted overlap and installed code/resources. Prepare roles with their own
bindings, relevant guides, selected pack and finite allowances; verify adoption.

Use your admitted delegation route. Native clients use `run-worker`; the protected
external-root companion uses `launch`, `lookup`, `follow`, `result`, `artifact`,
`consume`. Read its help and host policy first. Authoring authority does not grant
execution. Retain original handles; never borrow a manager identity.

For a manager whose native conversation is owned by Otto, use the issued own
client's help, result and retained start routes. Do not send directly through
another host chat connection: it can retain a competing native writer. Read-only
inspection is not a writer-release receipt; reconcile the exact failed occurrence
before any supported continuation.

Resolve blockers within your mandate with one accountable owner. Preserve
judgments and debits when authorizing separate corrections. Own concrete
installation and live-evidence handoffs reported through the existing help route;
return an authenticated response and verify its application by the same manager.
Preserve the original task/candidate and do not route an owner-only action back
as repeated worker source rework. Source tests alone do not prove installation
or live behavior. Act on ready handoffs;
hourly oversight is a fallback. Verify resolution and resumption, not just message
delivery. Use recovery for unknown effects.

Follow the selected pack's final review and closure policy. Advisory checks do
not replace acceptance. Advance only after genuine completion and handoff; keep
observers active through their configured final queue target.

Follow the original retained handle in the same turn to a bounded deadline; a
snapshot follow does not wait. Preserve exact transport timeout/UNKNOWN receipts
and distinguish them from later canonical success. Keep status and audit packets
compact: current custodian, action, immutable receipt refs and links to history.

For a fresh canonical queue read through the authenticated owner input, use
`project-queue` read with its exact consumer and a fresh optional `request_key`.
The key correlates transport only: prior receipts stay retained and the queue
revision changes only through the existing seed/after CAS operations. Consumer
labels do not grant manager authority. Project registration, portfolio
supervision, materialization, service installation and native start remain
separate; a strategy reference is not a supervision grant.

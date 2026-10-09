---
name: otto-recovery
description: "Recover an existing Otto project, manager, worker, native session, or reminder after interruption using maintained owner-bound commands; do not use for creating replacement state."
---

# Otto recovery

Use this workflow after an app, host, agent, command, native session, or
reminder interruption; for a pending/unknown response; or when an existing
project, checkout, worktree, chat, assignment, or Due occurrence must be
located and continued.

## Route

1. Read the exact installed command from the current role introduction. Use
   its read-only `help`, `status`, `operating-setup --operation read`, or
   `execution-control --operation read` surface first.
2. Find the existing project with `projects` or the bounded
   `find-and-continue` read, supplying an existing project, retained checkout,
   or retained session locator. Multiple, missing, moved, and held matches are
   reported; nothing is selected by filesystem crawling.
3. Inspect the exact retained occurrence or command handle with
   `execution-control --operation recover`, `worker-status`, `command-status`,
   or the applicable `read-help` command. A pending, unknown, offline, or
   mismatched effect stays held until its retained receipt/readback is
   reconciled.
4. Resume only the same eligible occurrence through the maintained
   `execution-control --operation resume` / `startup` path. Startup reconciles
   retained reminder bridge effects before Due evaluation; it does not recreate
   schedules or replay uncertain mutations.
5. Verify the returned result, current assignment/generation/session, next
   actor, reminder state, and acceptance/settlement separately. A host-only
   inspection is not a provider effect, task acceptance, or project close.
6. If custody cannot be resolved, use the supported authorized reassignment or
   replacement operation and its current owner assignment/generation. Do not
   copy an old conversation, create a new request key, or silently rebind a
   location.

The detailed route matrix is in [recovery-routes.md](references/recovery-routes.md).
Timing in retained receipts is observational: UTC phase timestamps and
same-process monotonic durations are used when available. Offline,
clock-discontinuity, and absent phases remain explicit gaps; no elapsed time is
invented across a restart or host boundary.

## Reminder startup composition

The trusted owner supplies `reminder_schedule_ids` as a bounded list of
**canonical Due schedule IDs**, its `reminder_attention` owner port, and an
authenticated `reminder_host_executor`. A native client cannot supply or
replace these ports. Existing `host_schedule_bridge` links a canonical Due
record to its external automation ID; an automation ID alone is not a Due
record or admission proof. Missing mapping stays unconfigured/unknown.

`execution-control --operation startup` and explicit `resume` use this
composition to reconcile a retained host effect by exact readback before
evaluating eligible missed Due slots. Lost responses do not repeat the host
mutation; pause, mismatch, unavailable readback, and uncertain effects hold
reminder admission. `reminder_admission` is separate from native recovery
`admission`, so an unrelated native occurrence remains diagnosable.

Read the pure bounded reminder projection with
`execution-control --operation reminder-read --schedule-id <canonical-due-id>`.
Only an owner-known ID in the current project is accepted. Without owner-known
IDs startup explicitly reports `not-configured`; with IDs but missing ports it
reports an unavailable bridge and held reminder admission. These results do not
claim that an automation was recreated or that a host wake occurred.

A configuration timestamp such as `observed_at` proves only configuration
readback. Wake remains unknown unless an explicit wake observation exists.
Current desktop automation cards/config files do not provide that observation;
an authenticated host readback integration is required for autonomous reminder
reconciliation. A manually observed heartbeat must retain its original host
receipt and cannot be retroactively promoted into canonical Due admission.

The owner integration step is explicit: read the existing canonical Due record
and its retained host bridge; bind those exact Due IDs on the server; supply
the existing `DurableAttention` owner port and `DeterministicHostExecutor` with
authenticated host read/update callbacks and the owner's `acknowledge_host`
callback. If a bridge must be authored, use existing `schedule`/`prepare_host`
operations with lifecycle owner, current version, and authorized scope; do not
create or update it as part of a recovery read. Leave external schedules
unconfigured/unknown until that association is actually retained.

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

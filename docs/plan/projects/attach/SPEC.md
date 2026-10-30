# Spec: attach

## Commands
- `otto attach advisor | orchestrator | manager --project <name> | worker --task <id> [--force]`, run from inside the outside session's working folder.
- `otto detach [--note <text>]`.
- `otto whoami`: prints the resolved identity and seat.

## Attaching
1. **Resolve the seat** from the role and project or task. Refuse an unknown seat, or a role the pack doesn't allow at that rank.
2. **If `otto run` holds the seat,** ask it to stop that session at a settled point (or now, with `--force`), and wait until the process has exited. If the exit can't be confirmed, **fail visibly**; never overlap.
3. **If another outside session holds it,** refuse without `--force`. With `--force`, mark the old binding stale.
4. **In one transaction:** set `host = external`, record a new binding id, and write the event.
5. **Write `.otto/agent`** (the agent id and binding id) in the working folder.
6. **Write `.otto/handover.md`,** and print it:
   - the role guide;
   - the skill names, with their paths;
   - the mandate or task brief;
   - the current work (open tasks, pending messages, the last checkpoint);
   - "check `otto inbox` at the start of every turn".

## Acting as the seat
- **Every CLI call** resolves its identity through `--as`, then `OTTO_AGENT`, then `.otto/agent`. A binding id that isn't current is refused, so a stale window can't act.
- **The inbox is pull-only:** `otto inbox` lists pending messages, and `otto ack <id>` (or replying) acknowledges one, using the same operation keys as v1.
- **Reminders** (check-ins, consultations) are queued into the inbox instead of being delivered.
- **The idle-manager check** skips external seats.

## Detaching
1. **Write the handover note,** from `--note` or a prompt.
2. **In one transaction:** set `host = otto`, end the binding, and write the event.
3. **`otto run` starts a fresh session** for the seat, with the role guide, the handover note and the current work, and delivers any pending inbox messages once it settles.

## Tests
Use v1's harness: the fake RPC process plus a crash hook between the stop and the binding transaction.
- a takeover race: two `attach` calls at once give exactly one holder;
- a stale window is refused;
- a crash mid-attach leaves either the old holder or the new binding, never both and never neither, after restart reconciliation;
- detach restarts a supervised holder, and pending messages are delivered once.

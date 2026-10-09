# Recovery route matrix

This reference routes roles through the existing owner-bound commands. It is
guidance, not an approval gate and not a second recovery state machine.

| Route | Inspect first | Continue only after exact readback | Held condition |
| --- | --- | --- | --- |
| Organisation/orchestrator | `projects`, `find-and-continue`, `status` | `execution-control --operation startup` or an authorized reassignment | ambiguous project/session, stale custody, missing owner destination |
| Project/manager | `operating-setup --operation read`, `execution-control --operation read`, `worker-status`, `read-help` | `execution-control --operation recover` then `resume`, `manager-continue`, or the retained help continuation | unknown send, active old native work, paused Due, missing/mismatched host readback |
| Worker | `worker-status`, `command-status`, retained result/assignment evidence | same occurrence resume through the assigned manager/owner route | no current assignment/generation, missing terminal capture, unavailable host |
| Reminder | `execution-control --operation reminder-read --schedule-id <canonical-due-id>` | startup reconciliation then existing Due coalescing | absent host observation, paused schedule, lost update response, clock gap |

For a project with several retained locations or chats, report cardinality and
state for every bounded match. Reassignment is an existing owner operation and
must retain assignment history and generation. A source/worktree locator is
not permission to scan or relocate the filesystem.

Keep these distinctions in every report:

- read-only diagnosis versus an effectful recovery/resume command;
- host/manual transport or readback versus provider/native work;
- observed host wake versus admitted Due occurrence;
- returned transport versus owner settlement, task acceptance, or project close.

Reminder IDs come from owner composition, not request JSON. The canonical Due
ID maps to the external automation through `host_schedule_bridge`. An absent
bridge is unconfigured/unknown. Startup returns separate `reminder_admission`
and native `admission`; a reminder hold does not prevent read-only native
diagnosis. Exact host configuration readback can settle a retained update, but
its generic observation timestamp is never a wake timestamp. Use explicit wake
fields and retain unknown when none exists.

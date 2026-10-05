# Manager assessment commands

`manager_ctl.py manager-assessment` forwards six finite operations to the existing
`OttoAssessment`/Herzchen assessment owner. The retained assigned manager records
its inspection and acceptance; this command never starts a model, worker, advisor
or reviewer. `assessment.invocation` is the existing domain accounting record,
not a native model invocation. Source and evidence must already have admitted
owner refs; importing files and proving their provenance remain existing owner
operations.

Before assessment, the owner may admit the bounded local bookkeeping allocation
through `manager_ctl.py manager-assessment-pool`. The trusted controller binds
that operation to the owning run's local-only assessment policy: exact pool,
capacity, cumulative allowance, current project, and allowed task/criterion
pairs. The CLI supplies none of those policy values, so it cannot create an
arbitrary budget or consume a provider allowance. It is ordinary LIMIT
accounting for owner assessment records and has no provider capability.

Every call requires `--task PA01..PA06`, `--expected-task-ref '<exact ref JSON>'`,
`--expected-assignment-ref '<exact manager assignment ref JSON>'`,
`--expected-generation N`, `--request-key KEY`, `--operation OP`, and
`--arguments '<JSON object>'`. The service supplies the actor and project from
its maintained current state. It rechecks the project/task revisions, manager
assignment revision, generation, principal, role and owner grant on every call.
An existing scope must bind the exact current task. A project-level scope is not
silently converted into a task acceptance gate.

| Operation | Arguments |
| --- | --- |
| `declare-scope` | `scope_ref` (new, unpinned `assessment.scope` target), `criterion_refs` (existing exact criterion refs), `protocol` |
| `freeze-input` | `scope_ref`, `candidate_ref`, `criterion_refs`, `source_refs`, `evidence_refs`, `packet` (manager inspection notes) |
| `select-candidate` | `scope_ref`, `candidate_ref`, `criterion_ref`, `rationale` |
| `assess` | `scope_ref`, `candidate_ref`, `criterion_ref`, `input_ref`, `verdict` (`PASS`, `REWORK`, `UNKNOWN`), `limit_pool_ref`, `protocol_result`, optional `findings` |
| `accept` | `result_ref`, `candidate_ref`, `criterion_ref`, `evidence_refs`, `rationale` |
| `coverage` | `{}` |

All references pin current revisions, except the new scope target and the
standard stable `limit` pool ref. Arrays contain 1..64 refs. Freeze consumes the
candidate, criteria, source and evidence refs explicitly. Assess and accept
recheck the entire frozen input and the candidate's semantic source pins.
Evidence at acceptance must have been consumed by that input. The existing
owner rejects non-PASS results, open findings, changed replay inputs and an
incorrect designated approver. New declared scopes require review and normal
task completion gates. Coverage distinguishes assessed results from actual
accepted decision refs.

`assess` uses the existing limit owner, reserving and settling one unit per
assessment. Supply the exact stable pool ref issued by the trusted policy. The
command rejects any pool outside that policy, does not override units or grant
another provider turn, and does not accept an arbitrary budget. Logical-key
replay does not consume another unit. Use a distinct key for each criterion and
operation; after an uncertain response, inspect retained exact request state
before retry.

Example acceptance of a previously inspected, current PASS result:

```sh
python manager_ctl.py manager-assessment --task PA06 --operation accept \
  --request-key manager-pa06-C09-accept-v1 \
  --expected-task-ref "$current_task_ref" \
  --expected-assignment-ref "$current_manager_assignment_ref" \
  --expected-generation 1 \
  --arguments "$acceptance_arguments"
```

`acceptance_arguments` is JSON with the five fields listed in the
table. Use the returned decision ref in ordinary `completion-gate --gate-ref`
and `complete-task --gate-ref`. Acceptance does not mark a task completed or
fabricate execution evidence. The provisional gate can return UNKNOWN when it
cannot verify native result evidence; the normal completion transaction still
checks the authenticated result/attempt or DAT evidence chain. Complete a task
after its retained manager turn returns so its adopted active task pin remains
valid through settlement.

The service's nested IPC allowlist includes `manager-assessment` and the finite
read-only `advisor-decision-state`. Both run on the existing serialized owner
thread during an authorized manager native wait. Provider-bearing commands
remain deferred; owner custody and UNKNOWN/no-overlap fences are unchanged.

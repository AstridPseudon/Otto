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

Every maintained-client call requires `--task J01..J04`, `--operation OP`,
`--request-key KEY`, and `--arguments '<JSON object>'`. The client derives the
expected current task ref, manager assignment ref, and generation from the
canonical run state; the service supplies the actor and project from its
maintained current state. It rechecks project/task revisions, manager assignment
revision, generation, principal, role, and owner grant on every call. An existing
scope must bind the exact current task. A project-level scope is not silently
converted into a task acceptance gate.

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
PYTHON=/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python
CLIENT=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-manager-journey-20261005/controller/manager_ctl.py
"$PYTHON" "$CLIENT" manager-assessment --task J04 --operation accept \
  --request-key manager-j04-C08-accept-v1 \
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

For focused local verification, use the pinned interpreter and the candidate
checkout's unittest suite; pytest is not required:

```sh
PYTHONPATH=src "$PYTHON" -m unittest \
  tests.test_manager_bootstrap_recovery \
  tests.test_manager_service_continuation \
  tests.test_workspace_write_native_attribution -q
```

# OTT-03 bounded safe responsibility handoff

Date: 2026-09-14. This packet covers only the remaining safe responsibility handoff target-lookup obligation. It does not claim whole OTT-03, G-OTTO, G-FINAL, or programme acceptance. The later live host/Astrid boundary is reported as EX-HOST only.

## Custody and inputs

- Checkout/cwd: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-handoff-worker`.
- Allowed writes: `src/otto/portfolio/`, `tests/otto/`, and `work/ott-03-handoff-worker-receipt-20260914/`. No shared Herzchen/foundation checkout, upstream, sealed packet, control DB, or other worker checkout was modified.
- Accepted base: commit `a09532940e500de6b9ef43f8a6f5c710f6c6e0aa`, tree `eb4369a03513ffab83df58be45b3283a0ce17b3c`.
- Bounded implementation commit: `f3ccc1d0bd96576259783ac2279d0027d3ab895f`, tree `87b52a06365ebfa19c465e3ada2941204363068e`.
- Accepted Otto parent: `b3840b7c4eeaca0590bf9b0def4fd69492b358cd`, tree `7a8253653451659904fa495aeb1ba325df087086`.
- Accepted Herzchen source: `b68d8f59712275229c24757664ca30d807d39e4a`, tree `ee1614fc37fdd096fb9640702e124e28a391d170`; accepted wheel SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Final Otto wheel: `work/ott-03-handoff-worker-receipt-20260914/dist/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `44ecacb2f3b479edb94fa4871a3f7d4aa672509961e55b12252d606d7cb2c4d7`.
- P01 guidance: commit `5482198b004375310d4fec33204e8fb71763a369`; profile SHA-256 `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`.
- Python: `3.11.16`; preserved disposable venv: `work/ott-03-handoff-worker-receipt-20260914/venv`. Installed package origins are recorded in `installed-origins.json`; only the accepted Herzchen wheel and final Otto wheel were installed as product packages, with pytest as the test runner.
- Requested execution route: model `gpt-5.6-luna`, reasoning `high`, write mode `isolated-checkout-owned-paths`. The exact process IDs, start/end, environment, command text, session observation, and exit codes are in `execution-receipts.json` and JSONL form in `execution-receipts.jsonl`.

## Public target-resolution investigation

The installed accepted Herzchen wheel exposes these relevant public APIs:

- `ResponsibilityAssignments.assign`/`create(scope, role, principal, ..., manager, logical_request_key, actor)` returns the typed `ResponsibilityAssignment`; `get`/`resolve(target)` reads it; `reassign(target, principal, ..., reason, expected_generation, logical_request_key, actor)` preserves the assignment identity while incrementing generation and appending history; `fence(target, generation)` validates the generation. The typed value has `ref`/`assignment_ref`, `scope`, `role`, `principal`, `generation`, `history`, `status`, and `payload`; the accepted payload also carries the initial `manager` attribution.
- `ProjectSheet.export`/`read`/`view(project)` is a fresh selected authored/observed projection and joins assignment observations for task scopes. It is not a safe manager-target lookup for this project handoff.
- `WorkGraph.get`/`resolve` and `list(project=..., kind=...)` are fresh work-record reads. They do not resolve a manager assignment from a name and are not used as an assignment scan.
- The actual `assign_roles` path calls the accepted finite `assignments_port.assign` four times for parent, manager, and executor assignments. It returns each assignment `ref` and its `work.assignment.create` receipt; the manager entry is additionally returned as `manager_assignment_ref`.
- Before this increment, Otto's `handoff` request had `project_ref`, `from_manager`, `to_manager`, `evidence_refs`, `consumption_refs`, `parent_obligation`, and `safe_handoff`, but no finite handoff dispatch or canonical assignment target. The accepted public assignment API has lookup and reassign, so no new Herzchen capability was required. The smallest backward-compatible Otto addition is optional validated `manager_assignment_ref`; the real finite binding requires the typed reference returned by `assign_roles` and rejects omission before mutation. Legacy generic test ports remain backward-compatible.

## Implementation boundary

`FiniteWorkOperations` now dispatches `work.responsibility.handoff` only through the injected finite `assignments_port`. It resolves the supplied `wrk.assignment` with public `get`, checks the authority, manager role, project scope, current principal and manager attribution, then passes the observed generation to public `reassign`. It never guesses from `from_manager`, scans private SQLite, adds a generic query, or retains a second assignment writer.

The exact request context is represented by a deterministic URL-safe JSON token in the accepted assignment `history.reason` field because `ResponsibilityAssignments.reassign` has no arbitrary payload extension. The durable assignment history/event effect therefore retains the typed project, evidence, consumption, parent-obligation and manager-assignment references without a side ledger. The returned handoff includes the decoded typed context, assignment value, canonical receipt, and exact event IDs. The accepted Herzchen reassign operation changes the typed `principal` to the replacement and preserves its historical payload `manager` attribution; Otto exposes both current `manager` (typed principal) and `stored_manager` to avoid rewriting authoritative generated state.

Same-key replay compares the durable typed context and delegates the identical canonical request to `reassign`, returning the original assignment/result linkage and receipt with no new event. Changed manager, evidence, consumption, or parent input returns `replay_conflict` before mutation. Unknown, wrong-role/wrong-scope, foreign, stale, or wrong-`from_manager` targets reject before mutation. Handoff reports `executable=false` and explicit false activation/dispatch/budget/task/session side-effect fields.

## OTT-03 surface matrix

The full matrix, including all accepted prior surfaces, the bounded handoff row, consumer retention, and the later EX-HOST boundary, is in [surface-matrix.json](surface-matrix.json).

| Surface | Result in this packet |
|---|---|
| Pending create/read/edit | Preserved; prior accepted behavior remains covered. |
| Revisit/prerequisite | Preserved attention-only/no-dispatch behavior. |
| ProjectSheet admission | Preserved canonical ProjectSheet path. |
| Parent/manager/executor assignment | Preserved; manager typed ref now returned explicitly. |
| Content document create/link | Preserved canonical content path. |
| Authoring open/reopen/occupied/replay | Preserved accepted owner/bootstrap path. |
| Atomic pending create-and-open | Preserved accepted XHARD increment and prior evidence byte-for-byte. |
| Safe responsibility handoff | Supported with typed target lookup, generation fence, canonical reassign, durable context, replay/conflict/rejection/restart proof. |
| Live host/Astrid launch/session/AST | EX-HOST, later/out of scope; not claimed. |

## Observed proof

The installed harness in [handoff-observations.json](handoff-observations.json) creates a pending project plus parent, assigns parent/manager/executor through `assign_roles`, and hands off using the actual returned manager assignment reference. It records before/action/fresh-after/replay/conflict/rejection states. The action is one `work.assignment.reassigned` event; assignment identity is unchanged, generation is 1→2, principal is `manager-old`→`manager-new`, history is preserved and extended, and all typed refs are retained in the durable history token. The project remains pending with no task, manager column, budget, dispatch, activation, or session change.

After Store close/reopen, fresh `WorkGraph.get` and `ResponsibilityAssignments.get` return the same project and assignment identity, generation, replacement principal, history, and receipt/event linkage. Identical retry is `replayed` with equal assignment/context/receipt/event IDs and a 0-event delta. Changed same-key manager/evidence/consumption/parent cases are typed `replay_conflict`, each with a 0-event and unchanged-receipt delta. Wrong manager, unknown target, and wrong-role target reject with 0-event deltas.

Consumer retention remains finite serialized command/read clients plus `HerzchenBindingConfig`; focused scans exclude Store, WorkGraph, ProjectSheet, ContentCommandHandler, ResponsibilityAssignments, AuthoringSessionService, DB paths, and arbitrary callables.

## Validation

- Source prior matrix: command in `execution-receipts.json` label `source-31`, 31 passed, exit 0.
- Source final focused campaign: label `source-34`, same prior 31 plus three handoff tests, 34 passed, exit 0.
- Installed prior matrix: label `installed-31`, `PYTHONPATH` and `PYTHONHOME` unset, 31 passed, exit 0.
- Installed final focused campaign: label `installed-34`, both path variables unset, 34 passed, exit 0.
- Installed real harness: final label `installed-harness-final`, exit 0; observations written to `handoff-observations.json`.
- All test commands use Python 3.11.16, the preserved venv, and `pytest -c /dev/null` because repository configuration is not loadable in the disposable environment. No broad unrelated suite was run.
- `git diff --check` passed before commit. Historical XHARD result/matrix/observation files were not modified.

## Unresolved later boundary

Only EX-HOST remains later/unclaimed: live host/Astrid launch, session, and AST-managed behavior. This packet claims neither that boundary nor whole OTT-03/G-OTTO acceptance.

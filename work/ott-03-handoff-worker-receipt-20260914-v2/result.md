# OTT-03 bounded continuity correction and acceptance-matrix continuation

Date: 2026-09-14. This supplement covers only the bounded safe responsibility handoff continuity correction in the Otto candidate. It does not accept OTT-06, EX-HOST, G-OTTO, live host/Astrid behavior, or the whole programme.

## Custody and pins

- Checkout/cwd: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-handoff-worker`.
- Writes were limited to owned Otto source/tests and `work/ott-03-handoff-worker-receipt-20260914-v2/`. No shared Herzchen/foundation checkout, upstream, sealed packet, control DB, or other worker checkout was modified.
- Accepted base: `a09532940e500de6b9ef43f8a6f5c710f6c6e0aa`; historical bounded source commit: `f3ccc1d0bd96576259783ac2279d0027d3ab895f`; historical evidence commit: `15cb3155cf81a3e4eb30cb86819363dc41849498`.
- Current corrected source commit: `23727a15f1d2300ca617082570545f787c2d082a`, tree `2336691fb729c8e1e447e26af2633a5b706abd5f`. The current corrected evidence commit is the v2 evidence commit containing this supplement; its exact commit/tree and artifact hashes are captured by the final git receipt and `artifact-sha256.json`.
- Accepted Herzchen source: `b68d8f59712275229c24757664ca30d807d39e4a`; accepted wheel SHA-256: `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Current Otto wheel: `work/ott-03-handoff-worker-receipt-20260914-v2/dist/otto_local_candidate-0.0.0-py3-none-any.whl`; SHA-256: `b7ca895ba6ea492efd9cf38162e9cbe35a700e17f70fcf9e43ebdd93fa14bdd5`.
- Python: `3.11.16`; preserved disposable venv: `work/ott-03-handoff-worker-receipt-20260914/venv`. Installed origins and package pins are in `installed-origins.json`.
- Requested route: model `gpt-5.6-luna`, reasoning `high`, write mode `isolated-checkout-owned-paths`. Exact command argv, cwd, environment, start/end, process ID, session observation, exit code and test count are in `execution-receipts.json` and JSONL form in `execution-receipts.jsonl`.

## Continuity finding and public API boundary

The pre-correction installed probe is retained in `continuity-before.txt`. It showed: manager `old` assigned at `rev-1`; `old → new` succeeded at generation 2; the valid `new → third` request using returned `rev-2` was rejected as `stale_manager_assignment` because Otto compared the current principal with both the current principal and the historical payload `manager=old`; retry of the first request was already a zero-delta replay.

The accepted Herzchen public surface is sufficient. `ResponsibilityAssignments.assign`/`create` returns typed `ResponsibilityAssignment` values; `get`/`resolve` performs the canonical typed lookup; `reassign` accepts `expected_generation`, `reason`, `logical_request_key` and `actor`, preserves assignment identity, increments generation and appends history; `fence` validates a generation. Typed fields used here are `ref`/`assignment_ref`, `scope`, `role`, `principal`, `manager` in the payload, `generation`, `status`, `history` and `payload`. `ProjectSheet.export`/`read`/`view` is a projection and not the manager-target resolver. `WorkGraph.get`/`resolve`/`list` are fresh work-record reads, not name scans.

`assign_roles` calls the accepted finite `assignments_port.assign` path and returns role assignment refs/receipts, including the manager’s `manager_assignment_ref`. Otto’s pre-existing handoff keys were project, from/to manager, evidence, consumption and parent references; the smallest safe API addition is the optional, validated `manager_assignment_ref`. The real finite binding requires this typed `wrk.assignment` reference and uses only `assignments_port.get` then `assignments_port.reassign`; it adds no generic query, private SQLite access, manager-name inference, side ledger or second writer.

The correction validates manager role, project scope, current status (`queued` or `reassigned`), current principal equal to `from_manager`, and passes the observed current generation to public `reassign` for every fresh handoff. Historical payload `manager` remains informational and is exposed as `stored_manager`; it no longer gates a later current owner. Each context includes the logical request ID and is retained in the accepted assignment history reason because the public reassign model has no arbitrary payload extension. Replay context is selected by request ID from that durable history. A latest exact retry requires current principal equal to the stored replacement. An older exact request can replay Herzchen’s original receipt after a later valid handoff only when its exact durable context is present in assignment history; the public replay call returns the original result without reverting the newer current assignment.

## Continuity proof

`tests/otto/test_handoff_continuity.py` and the installed `handoff_harness_v2.py` exercise real accepted wheels and public ports. The harness records before/action/fresh-after/restart/replay/conflict/rejection observations in `handoff-observations.json`.

- Returned manager refs are `rev-1`, `rev-2`, `rev-3`; the assignment ID is unchanged and generations are `1`, `2`, `3` with principals `old`, `new`, `third`.
- The second handoff retains project, evidence, consumption and parent references, historical `stored_manager=old`, the full assignment history, and exact `work.assignment.reassign` receipt/event linkage.
- After Store close/open, fresh `WorkGraph.get` and `ResponsibilityAssignments.get` see the same project and assignment identity, generation 3, principal `third`, history length 3, and both original receipts.
- Exact retry of the second request is `replayed`, equal to the original result/receipt, and adds zero events. Retrying the first request after the second is also `replayed`; its returned original result is generation 2, while the fresh current assignment remains generation 3/principal `third` and no event is added.
- Changed same-key manager, evidence, consumption and parent inputs are typed `replay_conflict` with zero event delta. A fresh stale old-target request and wrong `from_manager` reject as `stale_manager_assignment`; unknown and wrong-role targets reject before mutation. All rejection states retain the generation-3/third assignment.
- Handoff returns `executable=false`, `activation=false`, `dispatch=false`, `budget_reserved=false`, `task_created=false`, and `session_created=false`; the pending project has no task or activation side effect.

## Test campaigns

- `source-existing-34.txt`: preserved selection, 34 passed, exit 0.
- `source-final-35.txt`: preserved selection plus `test_handoff_continuity.py`, 35 passed, exit 0.
- `installed-existing-34.txt`: same preserved selection with `PYTHONPATH` and `PYTHONHOME` unset, 34 passed, exit 0.
- `installed-final-35.txt`: installed accepted Herzchen wheel plus current Otto wheel, both path variables unset, 35 passed, exit 0.
- `installed-harness-v2.txt`: installed sequential continuity harness, exit 0; JSON observations written to `handoff-observations.json`.

All campaigns use the preserved Python 3.11 venv and `pytest -c /dev/null` because repository configuration is not loadable in the disposable environment. No broad unrelated suite was run. The prior evidence directory and its historical files remain untouched.

## Complete OTT-03 acceptance matrix

The complete current matrix, retaining the original nine rows and adding the requested continuation rows, is [surface-matrix.json](surface-matrix.json). Supported/proven rows identify whether proof is from this Otto candidate or prior accepted Herzchen/XHARD evidence. Pending rows remain explicit and are not converted into acceptance claims.

| Row | Current disposition |
|---|---|
| Pending create/read/edit | Supported/preserved; candidate tests plus accepted WorkGraph persistence. |
| Revisit/prerequisite | Supported/preserved; attention-only and no dispatch. |
| ProjectSheet admission | Supported/preserved through the accepted ProjectSheet port. |
| Parent/manager/executor assignment | Supported/proven; typed refs and manager ref returned. |
| Content document create/link | Supported/preserved through accepted content ports. |
| Authoring open/reopen/occupied/replay | Supported/preserved in the accepted owner/bootstrap composition. |
| Atomic pending create-and-open | Supported in retained XHARD increment; prior evidence remains historical and unchanged. |
| Safe responsibility handoff | Supported/proven by the current bounded correction and v2 installed harness. |
| Live host/Astrid launch/session/AST | Pending EX-HOST; not claimed. |
| Shipped help/default blank starter | Supported/proven in the Otto candidate. |
| Selected-template create/edit/reopen | Supported/proven in the Otto candidate; no clone side effects. |
| Pending read/edit/reopen after restart | Supported/proven with fresh readers and restart observations. |
| No-auto-action for revisit/satisfied prerequisite/template cloning/protocol edits | Supported/proven for bounded data paths; no workflow language or auto-action claimed. |
| Parent-manager-executor assignment plus sequential safe handoff | Supported/proven; rev-1/rev-2/rev-3 and generation 1/2/3 evidence retained. |
| Durable doc links/custom metadata | Supported/preserved; candidate tests cover typed links and sparse unknown metadata. |
| Create-and-open partial/repeat outcomes | Supported/proven in the retained owner/bootstrap increment; regression campaign remains green. |
| Later OTT-06 real-agent/two-project rehearsal | Pending later OTT-06; not claimed. |

Remaining pending rows are only live host/Astrid/AST (EX-HOST) and the later OTT-06 real-agent/two-project rehearsal. This supplement claims neither OTT-06, G-OTTO, live host/Astrid, nor whole-program acceptance.

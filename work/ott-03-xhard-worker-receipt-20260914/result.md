# OTT-03 XHARD owner/bootstrap bridge result

Date: 2026-09-14. Outcome: the requested owner/bootstrap create-and-open gap is closed by implementation commit `b3840b7c4eeaca0590bf9b0def4fd69492b358cd`, tree `7a8253653451659904fa495aeb1ba325df087086`. This is not a claim of broader OTT-03 program acceptance, host/Astrid cutover, or closure of the historical safe-handoff row.

## Custody and accepted inputs

- Exact route: `gpt-5.6-sol`, reasoning `high`, write mode `dangerously-bypass-approvals-and-sandbox`, PTY session `31782`, thread `01a0a0b2-0857-79c2-8c7d-07776d142c41`.
- Exact cwd: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-xhard-worker`.
- Launch receipt: `work/ott-03-xhard-launch-receipt-20260914.json`, SHA-256 `15939fea1175a72640248c3fc8ae0b7c9c71f8c89f1efb4624014b55ae92ea2e`.
- XHARD brief: `work/ott-03-xhard-brief-20260914.md`, SHA-256 `6efc3d8f6e8628a7c86ba8a1f298e126746f403acc6247f5c85e4c4300be07db`.
- XHARD input manifest: `work/ott-03-xhard-input-manifest-20260914.json`, SHA-256 `d6ab6dff48170365855232e14670b6173eb5be76df24715341462e24879f23ea`.
- Accepted Herzchen wheel: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-consumer-separation-worker/work/gf01-consumer-writer-separation-worker-receipt-20260914/dist/herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- No shared Herzchen/foundation checkout, upstream, sealed packet, or file outside the allowed Otto source/test/result scope was modified.

## Implementation boundary

`PortfolioOwnerBootstrap` is the trusted owner object. It alone retains the accepted Store, WorkGraph, ProjectSheet, ContentCommandHandler, ResponsibilityAssignments, and AuthoringSessionService facades. Its owner-only bridge invokes `AuthoringSessionService.create_and_open` and constructs exactly one fixed callback to `ProjectSheet.create_pending`. The callback is never accepted from or returned to a consumer.

The consumer `FiniteWorkOperations` receives only seven `SerializedCommandClient` values, one `SerializedReaderClient`, and `HerzchenBindingConfig`. The new serialized bridge advertises exactly `create_pending_and_open`. The underlying authoring consumer port still does not advertise owner-only `create_and_open`. No Store, service instance, DB path/descriptor, transaction, generic writer method, arbitrary Callable, pickle, or callback transport crosses the boundary.

The bridge reserves the deterministic ProjectSheet project identity for logical key `<request_id>:project`, binds the exact planned revision plus the full logical request into the authoring digest, and verifies the created identity before any configured owner materializer runs. If the accepted identity contract ever differs, the check fails closed through the foundation's saved-project/not-opened recovery path rather than returning a mismatched open result.

## First real installed proof

The installed observation ran as PID `57050` from `2026-09-14T16:28:43.663940+00:00` to `2026-09-14T16:28:43.741268+00:00`, with `PYTHONPATH` and `PYTHONHOME` unset. Imports resolved to the final venv's installed `otto` and `herzchen` packages.

The success observation was:

- before: 0 events and no create/open or project receipt;
- action: `outcome=created`, `open.status=opened`, one durable `work.project` at revision `rev-1`, one durable `authoring-scope` at revision `rev-3`, open and project receipts, and five exact event IDs;
- fresh-after: after closing and reopening the Store with the exact registered descriptors, the pending payload, authoring checkout, project link, receipts, and event list were equal;
- identical replay: `outcome=replayed`, the same project ref/session ID/receipts/event IDs, and 5→5 events;
- same-key changed title: typed `replay_conflict`, 5→5 events, and byte-for-value equal receipt observations;
- actor occupation: `open.status=actor_occupied`, no project ref or receipt, and 5→5 events.

The materialization-failure observation was:

- before: 0 events;
- action: actual foundation status `saved_project_edit_not_opened`, exactly one durable pending project linked from the released authoring scope, one materializer call, and six events;
- identical replay: `outcome=replayed`, `open.status=saved_project_edit_not_opened`, equal receipts, no second materializer call, and 6→6 events;
- recovery reopen: the same durable project opened successfully, without a second project receipt or project mutation; events advanced only for authoring actor/open, 6→8.

The full exact records, receipts, payloads, revisions, event IDs, and before/action/fresh-after snapshots are in `durable-observations.json` (SHA-256 `bf5b8bebbb42a8a30042b0c4b33a1343c2ec955d47c0d8a2945c1c3e8074f070`). The persisted proof DBs are retained beside it, with hashes recorded in `execution-receipts.json`.

## Validation

Python was `3.11.16`. The prior focused selection was run before implementation propagation and remained `25 passed`. The final source and installed campaigns each ran the same prior 25 tests plus the six new owner/bootstrap tests:

- source: shell PID `56948`, pytest PID `56952`, `2026-09-14T16:27:16Z`–`16:27:17Z`, exit 0, `31 passed`;
- installed: shell PID `56959`, pytest PID `56963`, `2026-09-14T16:27:24Z`–`16:27:24Z`, exit 0, `31 passed`, with both Python path variables unset.

Both used `-c /dev/null`. The only warning was pytest's expected inability to create `/dev/.pytest_cache`; it did not affect test execution. No broad unrelated suite was run.

Fresh Otto wheel: `work/ott-03-xhard-worker-receipt-20260914/dist/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `e82a61179602667ebfa11e82279ec8b4af4edfbb8b39c951d8163fca0109a5d6`. It was built by PID `56902` from a `git archive` of implementation commit `b3840b7` and installed into the preserved venv at `work/ott-03-xhard-worker-receipt-20260914/venv`.

Installed origins:

- Otto: `work/ott-03-xhard-worker-receipt-20260914/venv/lib/python3.11/site-packages/otto/__init__.py`;
- owner bridge: `work/ott-03-xhard-worker-receipt-20260914/venv/lib/python3.11/site-packages/otto/portfolio/owner_bootstrap.py`;
- Herzchen: `work/ott-03-xhard-worker-receipt-20260914/venv/lib/python3.11/site-packages/herzchen/__init__.py`;
- packages: `otto-local-candidate==0.0.0`, `herzchen-contracts==0.1.0`, `pytest==9.1.1`.

Exact command strings, process IDs, timestamps, exit codes, hashes, origins, and route fields are in `execution-receipts.json`. The complete per-surface decision is in `surface-matrix.json`.

## Lineage

1. Accepted OTT-02 base: `d0e9b8dca0e0d455c059b09014f191cacd69a925`, tree `f8987e3cb3b4e66a0dbcd29a8dff354f486ca207`.
2. Prior OTT-03 source/test composition: `6a7213e776800ce8b3dd14864e285d94071fb551`, tree `c3436462d01cea016a5a63a015a0f71cda756c11`.
3. Accepted partial/evidence base: `c7c9cff4bf2780e4bb74db028bb6ad29d0d6d03c`, tree `4f7c369c155f7338559bf351b0f82e30bc4523fb`, direct parent `6a7213e`.
4. This continuation implementation: `b3840b7c4eeaca0590bf9b0def4fd69492b358cd`, tree `7a8253653451659904fa495aeb1ba325df087086`, direct parent `c7c9cff`.
5. Accepted foundation remains external and unchanged: commit `b68d8f59712275229c24757664ca30d807d39e4a`, tree `ee1614fc37fdd096fb9640702e124e28a391d170`, wheel SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
6. P01 guidance remains commit `5482198b004375310d4fec33204e8fb71763a369`; accepted profile SHA-256 `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`.

Historical `6a7213e`/`c7c9cff` result and v5 manifest files were not rewritten. Their 25-test proof and original concrete callback gap remain truthful historical evidence; this continuation adds the missing trusted owner bridge and closes that specific gap.

## Unresolved and deliberately unclaimed

- Safe responsibility handoff remains the pre-existing concrete gap: the accepted finite reader/port has no bounded lookup mapping Otto's handoff request to the current assignment target. No handoff state or private lookup was fabricated here.
- Live host/Astrid launch/session/AST behavior remains outside this worker at EX-HOST.
- Global OTT-03 acceptance and downstream gates are not claimed here. The required XHARD owner/bootstrap surfaces themselves have no unresolved row.

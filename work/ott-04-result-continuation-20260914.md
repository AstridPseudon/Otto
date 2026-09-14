# OTT-04 continuation result — 2026-09-14

Status: the two bounded product-proof gaps from terminal commit `6e2a4002622887356417c1d66211ed58c47c36c6` are closed in the fresh owned increment. The historical 53-source/53-installed campaign and its honest incomplete result remain unchanged.

## Custody and route

- Continuation implementation commit: `e69d90f995ff58ed3306e48c1fba28562d608972`, tree `27846383db6ec3757996c93430d2c2f69159aa93`.
- Historical base preserved: `6e2a4002622887356417c1d66211ed58c47c36c6`, tree `afd46c1aad61239815b1351afb03be73146b8721`.
- Accepted Herzchen: commit `b68d8f59712275229c24757664ca30d807d39e4a`, tree `ee1614fc37fdd096fb9640702e124e28a391d170`, wheel SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Fresh Otto wheel: SHA-256 `8e3ad556abb80f6125f79813ceff40203e37e9562223359842c91243f0238642`.
- Manifest SHA-256: `65dc2f0476043a91ea8e9f86657794b25fef30e7946bab4cd13daa33f178d89f`.
- P01 profile SHA-256 remains `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`.
- Requested route was `gpt-5.6-luna`, reasoning `high`; no review/oracle/AST work was invoked. Launch/session custody is in `work/ott-04-continuation-launch-20260914/launch-receipt.json`.

## Gap A — real durable-host due-record binding

`StoreDueRecordPort` and `due_record_contribution()` are owner-side only. The trusted host supplies the exact Herzchen `DomainHandler` issued by `Store.register_domain_handler`; Otto sees only finite `read_due`/`save_due` methods. No Store, SQLite path, connection, generic writer, callback engine, or descriptor crosses the consumer boundary.

The real disposable Store mutation persists the complete due record as the public command payload and links its event and receipt atomically. The fresh observation proves:

- durable-host capability is available and explicitly distinct from awaited mode;
- recipient, instruction, profile, anchor, interval/due state, last-covered slot, invocation identity, stop state, outstanding wait decision, in-flight request, owner, return condition, and final result survive close/reopen;
- the three-hour interval coalesces two missed slots into one request;
- replay with the same logical key returns the original result with event delta `0`;
- same-key changed input is rejected with event delta `0`;
- stale expected version is rejected with event delta `0`;
- restart resumes the exact in-flight request and completion is recorded once; no relaunch or invented session ID occurs;
- the real attention notification is emitted through `ContextPacketService.notify_amendment`, read through `list_attention`, and linked to the returned event/receipt.

Raw source and installed observations, including exact receipt and event IDs, are in:

- `work/ott-04-continuation-20260914/real-observation-source.json`
- `work/ott-04-continuation-20260914/real-observation-installed.json`

## Gap B — existing public amendment/attention composition

The fresh real composition uses accepted public `WorkGraph`, `ProjectSheet`, `ResponsibilityAssignments`, and `ContextPacketService` operations. A manager-selected amendment changes the task plan, `last_batch.manager_action` next dispatch, assignment route view, and open owner attention. It preserves the current principal/owner, namespaced usage/budget observation, and running input pin. All required view changes and all preservation checks are true in the raw observation.

Review handling remains distinct from implementation: `handle_review()` reports `implemented_improvement: false`; only `apply()` with `manager_decision: implement` invokes the three public mutations. The real event list contains no `work.assignment.dispatched` event; responses report `dispatch: false` and `automatic_action: false`. If one view were unavailable, `ImprovementPropagation` would return `incomplete-propagation`; the exercised real path is complete.

## Validation and boundaries

- Affected source file: `tests/otto/test_continuity.py` — 8 passed, 0 failed, return code 0.
- Installed focused selection: the two new real product tests — 2 passed, 0 failed, return code 0.
- Installed invocation had both `PYTHONPATH` and `PYTHONHOME` unset; same-process origins are recorded in `work/ott-04-continuation-20260914/logs/installed-real-selection.txt`.
- Historical campaign remains 53 source / 53 installed and was not rerun or overwritten.
- Fixture-only mechanics remain labeled as fixture-only. Awaited mode remains current-host-call and non-durable. No OTT-06 real-agent rehearsal was run, and no agent launch, scheduler, callback transport, private SQL writer, private inbox, or side ledger was added.
- No unresolved shared-capability gap remains for either bounded surface.

Machine-readable summary and counts:

- `work/ott-04-continuation-20260914/continuation-result.json`
- `work/ott-04-continuation-20260914/test-counts.json`

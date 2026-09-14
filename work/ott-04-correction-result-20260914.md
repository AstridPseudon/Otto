# OTT-04 correction result — 2026-09-14

Correction scope is green. The historical implementation/evidence was preserved; this correction only changes the owned Otto source/test paths and adds new versioned evidence.

## Custody

- Base before correction: `fc800b36864f48acf0c1a12096756c5585ffb76f`, tree `f24088ee07dce958c8ba82460cac45bca4b110f5`.
- Correction source/test commit: `aa4428b46d1d30a68d5f4c04ad325be462c3ea53`, tree `c475416642310b0b667d0012c09a878e10c5cd77`.
- Preserved historical commits: implementation `e69d90f995ff58ed3306e48c1fba28562d608972`, evidence `ac85ba906cbc5b7a56638bd735a924c6aae2b5a3`, EX-HOST supplement `f44547e7f24c19823dd187e33f52599a81e1af32`, catalog assessment `fc800b36864f48acf0c1a12096756c5585ffb76f`.
- Accepted Herzchen commit/tree: `b68d8f59712275229c24757664ca30d807d39e4a` / `ee1614fc37fdd096fb9640702e124e28a391d170`; accepted wheel SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Fresh Otto wheel SHA-256: `4d0e409a9008bee32498418b3911ab1df26f4acd00f23ae200dd1e44e0f8c439` (`work/ott-04-correction-20260914/dist-final/`).
- Route: `gpt-5.6-luna`, reasoning `high`; launch/session receipt is `work/ott-04-correction-launch-20260914/launch-receipt.json`.

## Owner boundary correction

`StoreDueRecordPort` no longer retains `_writer` or an owner handler. `issue_store_due_record_port()` creates a trusted owner engine behind Herzchen’s accepted `command_facade` service and returns only a `SerializedCommandClient`-backed client with exactly `read_due` and `save_due` endpoints. The owner engine performs public `get_identity`, `get_receipt`, and `mutate` calls; the consumer object exposes no Store, handler, connection, DB path, generic writer, or callback.

The installed raw observation records `has_writer=false`, `has_store=false`, no connection, no DB transport path, and the exact endpoint set.

## Amendment composition correction

`issue_store_amendment_port()` now ships the owner-side composition. `_AmendmentOwnerEngine` constructs and invokes accepted public `ProjectSheet.apply`, `ProjectSheet.pin_assignment_route`, `ResponsibilityAssignments.get`, and `ContextPacketService.notify_amendment` APIs. `SerializedAmendmentPort` is a finite client with only `apply_amendment` and `read_views`; it is no longer callback-backed.

The installed real proof shows manager-decision-gated propagation of plan/task, next dispatch, open attention, and assignment route; preservation of current owner, usage/budget, and running input pins; before/action/fresh-after views; real receipts/events; and no dispatch or automatic action. The client audit records `has_callback=false` and `has_store=false`.

## Historical replay correction

Request A creates version 1; legitimate request B advances the live identity to version 2. Replaying A returns its historical version 1 payload and `rev-1` result reference with event delta zero, while a fresh `read_due` returns live version 2. Same-key changed input raises typed `InputChangedError` with zero event delta. A stale expected version raises typed `StateConflictError` with zero delta. These observations use public Store receipt/result references and are in the raw JSON artifacts.

## Validation

- Source affected file: 8 passed, return code 0.
- Installed focused real-product selection: 2 passed, return code 0, with `PYTHONPATH` and `PYTHONHOME` unset and same-process origins captured in `logs/installed-focused-final.txt`.
- Historical 53-source/53-installed campaign and prior raw observations were preserved; no broad unchanged suite was rerun.
- No remaining original OTT-04 boundary is unresolved in this correction scope. Fixture-only ports remain explicitly mechanical coverage, and OTT-06 agent rehearsal was not run.

Raw evidence: [correction summary](</Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott04-worker/work/ott-04-correction-20260914/correction-result.json>), [installed observation](</Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott04-worker/work/ott-04-correction-20260914/observation-installed.json>), [installed origins/tests](</Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott04-worker/work/ott-04-correction-20260914/logs/installed-focused.txt>).

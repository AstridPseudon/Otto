# OTT-03 selected-template create-and-open continuation

Date: 2026-09-14. Outcome: the formerly pending selected `WorkTemplate` create-and-open row is implemented and proven for this bounded Otto candidate. This receipt makes no OTT-06, G-OTTO, EX-HOST, live Astrid, or programme-completion claim.

## Pins and scope

- Accepted baseline: commit `74645e6aeb0f9dbd9d992aefc542c91e80624f94`, tree `684e4b6f9cb306e426f547aee208b4770ec450c5`.
- Accepted source parent: commit `3237701d21470380cbe471880d793449b5f40d9b`, tree `669d3af0e65bea36f4349f6374c4d7073f3a605a`.
- Product/tests: commit `14510f49514587ecda265fb3e38c632f9ebe3179`, tree `2d213ad75bb3a730bfed8c31eff9c4d2597ec4df`.
- Immutable Herzchen source: `b68d8f59712275229c24757664ca30d807d39e4a`.
- Immutable accepted Herzchen wheel SHA-256: `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Fresh Otto wheel: `dist/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `578c72f042a915510dc4dd1a10d78f82350231ac5029d2bf10f7a55b2febdf19`.
- Model/reasoning: `gpt-5.6-sol`, `high`; cwd and write mode are recorded in `lineage.json` and every execution receipt.

The sealed `work/ott-03-handoff-worker-receipt-20260914-v2` directory and the historical `work/ott-03-template-amendment-receipt-20260914` directory were not edited. This is the new versioned v3 evidence directory.

## Implementation result

`OttoPortfolio.create_pending` now accepts optional JSON `template_parameters` alongside the selected JSON template resource. The consumer-facing bridge remains one finite `create_pending_and_open` endpoint. Its new named fields are JSON mappings only; no Store, database descriptor, SQL, generic writer, callback, pickle, or arbitrary callable is transported.

The trusted owner reconstructs the accepted `WorkTemplate`, calls public `validate_template` and `render_template`, and only then enters the existing `AuthoringSessionService.create_and_open` lifecycle. After occupation is durably admitted, the owner creation callback creates the reserved pending project and calls accepted `ProjectSheet.command_port.instantiate_new_template`. The ProjectSheet application transaction applies template project fields and typed tasks. Its resulting revision is linked into the authoring scope. External owner materialization then follows the unchanged lifecycle.

The result contains the real authoring scope, structured handle, checkout, session ID, current project record, typed task records, and canonical open/project/template receipts. Selected template resource and invocation parameters are present in the canonical authoring request value and in persisted Otto request metadata. Exact replay bypasses the callbacks; changed resource or parameter input conflicts before any new mutation.

Blank/default requests retain the prior request payload and five-event lifecycle. The selected successful path adds exactly the accepted `work.project-sheet.applied` event and template receipt, for six total events.

## Test campaigns

All commands, argv arrays, UTC start/end timestamps, process IDs, return codes, model, reasoning, cwd, environment, write mode, and output paths are in `execution-receipts.json` and `execution-receipts.jsonl`.

- Source focused: `18 passed`, return code 0, from `2026-09-14T18:02:11.414659+00:00` to `2026-09-14T18:02:12.315229+00:00`; `PYTHONPATH` was the committed `src`, `PYTHONHOME` unset.
- Installed focused: `18 passed`, return code 0, from `2026-09-14T18:02:12.343350+00:00` to `2026-09-14T18:02:12.993993+00:00`; both `PYTHONPATH` and `PYTHONHOME` were unset.
- Source all Otto-owned tests: `47 passed`, return code 0, from `2026-09-14T18:00:54.141626+00:00` to `2026-09-14T18:00:55.519869+00:00`.
- Installed all Otto-owned tests: `47 passed`, return code 0, from `2026-09-14T18:00:56.332869+00:00` to `2026-09-14T18:00:57.244584+00:00`; both Python path variables were unset.
- Installed selected observation: final return code 0, from `2026-09-14T18:01:30.981606+00:00` to `2026-09-14T18:01:31.175996+00:00`, with both Python path variables unset.

The installed environment used Python 3.11.16. `installed-origins.json` proves both Otto and Herzchen came from `/private/tmp/ott03-template-open.o3HzxD/venv/lib/python3.11/site-packages`; `source-origins.json` separately proves the source campaign selected this checkout's `src/otto` while using the installed accepted Herzchen package.

The first observation-harness execution returned 1 because the evidence script attempted `IdentityRecord.to_dict()`, which that public value does not define. Its exact traceback is retained in `installed-selected-observation-failed.txt`. The evidence serializer was corrected without changing product source, and the final installed observation returned 0. This was an evidence-harness defect, not a product failure.

## Raw selected observation

The complete raw result, events, receipts, counts, fresh records, and fresh scope are in `selected-create-open-observation.json`. Its concise observed values are:

- outcome/open: `created` / `opened`;
- project: `ott03-selected-open-observation:work.project:project-15384ab8984c18eb304d1af79bc4@rev-2`;
- typed task: `ott03-selected-open-observation:work.task:task-6dd8626381ab90945b4436b894b2`;
- template: `pack:work_template:ott03.observed.selected-open@observed-v1`;
- session: `session-56053d6970295d65b0a2c8c3`;
- fresh title: `Observed selected project`; fresh scope checkout state: `open`;
- created event delta: 6; event types: `authoring.actor.open`, `authoring.open`, two `authoring.metadata`, `work.project.created`, `work.project-sheet.applied`;
- exact replay zero delta: true; changed resource/parameters each: `replay_conflict`, zero delta true;
- invalid resource: `invalid_template_resource`, zero delta true;
- inert flags for dispatch, manager launch, budget reservation, session-created task, and execution: all false.

The capability and coverage decision is explicit in `capability-coverage-matrix.json`: the formerly pending selected create-and-open row is now supported. There is no unresolved named product issue within this bounded continuation.

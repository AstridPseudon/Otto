# OTT-03 selected-template amendment

Date: 2026-09-14. This packet corrects only selected-template applicability in the bounded Otto candidate. It does not modify or replace the v2 continuity evidence, and it does not claim G-OTTO, EX-HOST, live Astrid, OTT-06, or programme completion.

## Lineage and custody

- Checkout: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-handoff-worker`.
- Exact starting commit/tree before edits: `528aa4dea810584d5c1794df6bd602f8c89abde7` / `5ed5ad9d2be4764286376867d49d91f9131e2ee3`.
- Historical v2 source/evidence lineage retained: source `23727a15f1d2300ca617082570545f787c2d082a` / tree `2336691fb729c8e1e447e26af2633a5b706abd5f`; evidence commit `528aa4dea810584d5c1794df6bd602f8c89abde7` / tree `5ed5ad9d2be4764286376867d49d91f9131e2ee3`.
- Current amendment source commit/tree: `3237701d21470380cbe471880d793449b5f40d9b` / `669d3af0e65bea36f4349f6374c4d7073f3a605a`.
- Current accepted Herzchen source: `b68d8f59712275229c24757664ca30d807d39e4a`; accepted wheel SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Current amendment Otto wheel: `work/ott-03-template-amendment-receipt-20260914/dist/otto_local_candidate-0.0.0-py3-none-any.whl`; SHA-256 is recorded in `installed-origins.json` and `artifact-sha256.json`.
- Writes were limited to owned Otto source/tests and `work/ott-03-template-amendment-receipt-20260914/`. The v2 evidence directory, prior v1 evidence, accepted Herzchen source, foundation packet, control DB and other checkouts were not edited.
- Preserved Python 3.11 venv: `work/ott-03-handoff-worker-receipt-20260914/venv`. Requested route: `gpt-5.6-luna`, reasoning `high`, write mode `isolated-checkout-owned-paths`.

## Public API investigation and implementation

The installed accepted Herzchen wheel exposes `ProjectSheet.command_port.instantiate_new_template(template, parameters=None, project=None, logical_request_key=None, actor=None)`. The accepted typed resource is `herzchen.packs.templates.WorkTemplate(id, revision, parameters, seed, source_ref=None)`, with `validate_template` and `render_template` public validation/rendering helpers. `instantiate_new_template` renders the seed, applies template-defined project fields through the accepted ProjectSheet batch path, and creates typed `work.task` records without dispatch.

For an explicit JSON template mapping, Otto validates `id`, `revision` or `version`, `parameters`, and `seed`, constructs `WorkTemplate`, and calls public `validate_template`/`render_template` before creating anything. It creates the project through the existing finite WorkGraph command with the complete template request bound in canonical metadata, then passes that typed project reference to `sheet_port.instantiate_new_template`. This preserves the accepted public ProjectSheet writer and makes changed template resource data participate in canonical same-key conflict detection. Default blank and string-label compatibility remain on the ordinary pending-create path.

The selected result returns the fresh project record, current project ref, typed task refs/records, `template_ref`, `template_revision`, project and batch receipts, event IDs, and explicit inertness fields. Invalid resources fail before project creation. The consumer retains only finite command/read clients and typed values; no Store, SQL, side ledger, generic writer, callback or template execution crosses the boundary.

The existing trusted owner bridge accepts only `create_pending_and_open(title, outcome, metadata)` and performs its accepted authoring transaction around ordinary project creation. It has no atomic endpoint accepting a typed WorkTemplate. Selected `create_and_open` therefore returns `canonical_selected_template_create_and_open_unavailable` before mutation and is explicitly pending in the amendment matrix. Blank/default create-and-open remains unchanged and is covered by historical v2 evidence.

## Real selected-template proof

The source and installed harnesses use the accepted wheel and real finite public ports. `selected-template-observations.json` is the installed observation record; the source counterpart is `selected-template-observations-source.json`.

- Before state has zero events. Selected creation returns `created`, template `pack/ott03.selected.template@template-rev-7`, a durable pending project, template-defined title/outcome/custom fields, and one typed `work.task` containing typed content. The canonical create and ProjectSheet batch produce two events with linked receipts.
- Edit changes the same project to `rev-3`; reopen returns the same project identity. Fresh restart reads retain the selected task and edited project fields.
- Exact same-key replay returns `replayed` with the same project/task identity and receipts and adds zero events.
- Changed same-key template parameters return canonical `replay_conflict` with zero event delta and unchanged receipt.
- Missing/invalid template resources return `invalid_template_resource` before any project/event is created.
- Selected create-and-open returns `canonical_selected_template_create_and_open_unavailable`, no project ref, and zero events. This is a named capability gap, not a product success claim.
- Pending remains inert: `executable`, `activation`, `dispatch`, `budget_reserved`, `task_created`, and `session_created` are false.

## Campaign receipts

- `source-final-36.txt`: retained 35-test v2 selection plus the selected-template test; 36 passed, exit 0.
- `installed-final-36.txt`: same campaign against the accepted Herzchen wheel and current Otto wheel, with `PYTHONPATH` and `PYTHONHOME` unset; 36 passed, exit 0.
- `source-template-harness-final2.txt`: source real-port harness, exit 0.
- `installed-template-harness.txt`: installed real-port harness, exit 0.
- An earlier harness wrapper setup/import attempt is retained as a failed diagnostic receipt; the final source and installed harnesses pass after making the harness self-contained. It is not a product failure.

Every campaign receipt records exact argv, model, reasoning, cwd, write mode, environment, start/end, process ID, session observation, exit code and output path in `execution-receipts.json` and `execution-receipts.jsonl`. Installed origins, Python version and wheel hashes are in `installed-origins.json`; all amendment artifact SHA-256 values are in `artifact-sha256.json`.

## Matrix and boundaries

The amendment matrix is [surface-matrix.json](surface-matrix.json). It corrects only selected-template applicability and points to the unchanged complete v2 matrix for all other OTT-03 surfaces. The selected-template create/edit/reopen, task/content, replay/conflict, invalid-resource and inertness rows are now proven in this Otto candidate. Selected create-and-open is explicitly pending at the existing owner bridge boundary.

No claim is made for G-OTTO, EX-HOST, live Astrid, OTT-06 real-agent/two-project rehearsal, or whole-program acceptance.

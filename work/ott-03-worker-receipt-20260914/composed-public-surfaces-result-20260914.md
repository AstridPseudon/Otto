# OTT-03 composed public-surfaces result supplement

Date: 2026-09-14. This is a dated result supplement for the correction from accepted finite-port source `acb1a59a4ebba30415258f1de7a2dbc0d60f3068` / tree `6d71b91d17d3197aafc929d4fe74db2bcf31207`. The prior finite-port proof remains historical and unchanged: `finite-port-correction-result-20260914.md`, SHA-256 `0726bda601c57bf7ecfa95531ea3bc40072669e43852d4589b79bd96dc9724be`.

## Inputs and custody

- Current worker commit: `6a7213e776800ce8b3dd14864e285d94071fb551`; tree `c3436462d01cea016a5a63a015a0f71cda756c11`.
- Immutable v5 amendment: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/ott-03-consumer-assembly-brief-v5-20260914.md`, SHA-256 `e5455511372a8bb59038f0827f375c358b1c1f1ba734ed856ee8f570f5d1463c`.
- Immutable launch manifest preserved at `work/ott-03-worker-receipt-20260914/manager-input-manifest.json`, SHA-256 `25977fd81f942e2e25856917390de3a05762f4f187f227451865f94b6839f731`.
- Versioned v5 manifest at `work/ott-03-worker-receipt-20260914/manager-input-manifest-v5.json`, SHA-256 `d4b8d41673949bab6ae93ff78ebd4f8c8107b2abf75bf3341a00f5258bc936d8`.
- Exact P01 profile remains `profiles/otto/operating.md`, SHA-256 `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`; its content was not changed. P01 commit `5482198b004375310d4fec33204e8fb71763a369` is not an ancestor of base `d0e9b8dca0e0d455c059b09014f191cacd69a925`.
- Accepted Herzchen wheel: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-consumer-separation-worker/work/gf01-consumer-writer-separation-worker-receipt-20260914/dist/herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.

Requested route was gpt-5.6-luna with `model_reasoning_effort=high` and bypassed approval/sandbox write mode. The local shell does not expose a model identifier. This worker did not invoke Astrid, modify shared Herzchen/foundation/map/control DB, or perform host transfer.

## Implementation and finite-port proof

The owned adapter retains exactly `port`, `reader`, `binding`, `sheet_port`, `content_port`, `assignments_port`, and `authoring_port`. Trusted bootstrap constructs Store/WorkGraph/service objects; Otto receives only each public `command_port` and the common read-only reader. A source scan found no `self.store`, `self.graph`, writer/service retention, raw SQL, sibling-source import, or arbitrary callback in the Otto adapter. The test asserts the exact retained attribute set for a composed adapter.

The actor is converted through `HerzchenBindingConfig(authority, credential_ref)` to an authenticated Herzchen actor. Logical request keys and payloads are retained in canonical WorkGraph metadata or command envelopes. Replay conflicts are returned as typed `replay_conflict` results; malformed/protected edits reject before the canonical call.

## Per-surface matrix

| Surface | Result | Evidence / boundary |
|---|---|---|
| Pending create/read/edit/reopen | Supported | WorkGraph `create_pending_project`, `get_record`, `get_receipt`, `list_events`, `revise`, and Authoring `open`; sparse unknown metadata round-trips. |
| Revisit/prerequisite | Supported | WorkGraph `set_readiness`; canonical receipt/event; `dispatch=false`, no activation. |
| ProjectSheet admission | Supported | `ProjectSheet.command_port.apply`; choice/frame/recipient/route/authority are canonical sheet fields; result is deliberately `executable=false` and does not activate. |
| Parent/accountable manager/executor | Supported as bounded assignment records | `ResponsibilityAssignments.command_port.assign` creates separate durable `parent`, `manager`, and bounded `executor` records with typed parent ref; identical replay creates no new events. A structural project-parent link is not fabricated because accepted WorkGraph rejects projects as children. |
| Content document | Supported | `ContentCommandHandler.command_port.build_create_document` plus `execute`; typed `dat.content.document` ref and canonical receipt/event. |
| Document association | Supported | `ContentCommandHandler.command_port.build_link` plus `execute`; typed `document-association` ref and canonical receipt/event. |
| Authoring open/reopen | Supported | `AuthoringSessionService.command_port.open`; durable session and `open` receipt; identical replay preserves session; occupied actor/scope is explicit; recovery fields are reported as `not_requested` unless the owner returns a pending recovery result. |
| Create-and-open | Explicitly blocked, no mutation | Installed `AuthoringSessionService.create_and_open(*args, create_project: Callable[..., Any], **kwargs)` requires an owner callback. Its finite command port exposes `open` but not `create_and_open`. Retaining the service or injecting an arbitrary callback violates GF01; sequential create-then-open can leave an orphan project on occupancy. Otto returns `canonical_create_and_open_finite_endpoint_unavailable` with `open.status=unsupported`. |
| Safe handoff | Not claimed | `ResponsibilityAssignments` exposes `reassign`, but the accepted finite reader/port has no bounded public lookup that maps Otto’s manager/evidence/consumption/parent-obligation request to the current assignment target. No fake handoff state is written. |

The create-and-open and safe-handoff rows are concrete accepted-public-capability boundaries, not inferred global unavailability. Full host/Astrid launch/session/AST behavior remains outside this worker and deferred at EX-HOST.

## Tests and campaigns

Source campaign, from the checkout, with accepted Herzchen imported from the installed pinned wheel:

```text
env -u PYTHONHOME PYTHONPATH=$REPO/src $VENV/bin/python -m pytest -c /dev/null -q $REPO/tests/otto/test_intake_roles.py $REPO/tests/otto/test_adapters.py $REPO/tests/otto/test_host_adapter_usage.py
shell PID 55385; pytest PID 55389; 2026-09-14T16:09:14Z–2026-09-14T16:09:15Z; return code 0; 25 passed.
```

Installed campaign was run from `/tmp`, with both `PYTHONPATH` and `PYTHONHOME` unset:

```text
env -u PYTHONPATH -u PYTHONHOME $VENV/bin/python -m pytest -c /dev/null -q $REPO/tests/otto/test_intake_roles.py $REPO/tests/otto/test_adapters.py $REPO/tests/otto/test_host_adapter_usage.py
shell PID 55396; pytest PID 55409; 2026-09-14T16:09:21Z–2026-09-14T16:09:22Z; return code 0; 25 passed.
```

The first installed invocation without `-c /dev/null` returned 1 because the repository pytest configuration was parsed with an incompatible `tomllib` module in that environment; the explicit no-config installed campaign above returned 0. No source path was injected in that campaign. Installed origins were:

```text
otto: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-worker/work/ott-03-installed-venv-20260914/venv-composed-final-6a7213e/lib/python3.11/site-packages/otto/__init__.py
herzchen: /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-worker/work/ott-03-installed-venv-20260914/venv-composed-final-6a7213e/lib/python3.11/site-packages/herzchen/__init__.py
otto-local-candidate==0.0.0; herzchen-contracts==0.1.0; Python 3.11.16
```

Fresh candidate wheel: `work/ott-03-worker-receipt-20260914/installed-composed-wheel-20260914/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `c33724df8197aef927102bdfb28fc4804ae5344df0ac4c0c9ac791fadf4ebd6d`.

Fresh venv: `work/ott-03-installed-venv-20260914/venv-composed-final-6a7213e`.

The installed canonical campaign used a disposable SQLite fixture only as trusted Store/bootstrap wiring. Public observations were: pending create 0→1 event; identical replay 1→1; changed same-key conflict 1→1; authoring open 1→3 (actor/open receipts), replay 3→3 with the same session; content create 3→4; document link 4→5; ProjectSheet admission 5→6 with `executable=false`; parent/manager/executor assignments 6→9. Assertions inspected Store `get_identity`, `get_receipt`, and `list_events` only; no SQL was used.

## Final custody

Source/test changes are committed in `6a7213e776800ce8b3dd14864e285d94071fb551`. `git diff --name-status` is empty after commit. Generated wheels/venvs and pre-existing historical receipts remain as dated untracked evidence in the worker worktree; no tracked source outside `src/otto/portfolio/` or `tests/otto/test_intake_roles.py` was changed.

This supplement does not claim OTT-03 acceptance, gate completion, host transfer, Astrid cutover, or OTT06 rehearsal. The create-and-open callback gap and safe-handoff target-lookup gap remain for owner review.

# OTT-03 installed-origin proof supplement — 2026-09-14

This is a dated evidence supplement after the completed v5 custody amendment. It does not rewrite the sealed v5 manifest or custody commit, and it is not a gate or acceptance claim.

## Source and immutable inputs

- Candidate source HEAD: f66ab70b8d3f772975e384760b96bafb1e957f4a
- Candidate source tree: 3620ea3a42873b5851aaf7da27db93dbde862c60
- Historical product increment retained: c93349aeb2353ae1b4cfb0b30d4bcf14d381eae0
- v5 custody amendment remains separate and unchanged.
- Immutable launch evidence: work/ott-03-worker-receipt-20260914/manager-input-manifest.json
- Immutable launch manifest SHA-256: 25977fd81f942e2e25856917390de3a05762f4f187f227451865f94b6839f731
- v5 current-input manifest remains: work/ott-03-worker-receipt-20260914/manager-input-manifest-v5.json
- P01 profile remains exact at profiles/otto/operating.md, SHA-256 9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726.

The source archive used for the wheel was made with git archive of f66ab70, so untracked result/receipt files were not included in the package.

## Wheel and disposable environment

Build command, executed outside the candidate checkout:

    BUILD_DIR=$(mktemp -d /tmp/otto-ott03-wheel-build.XXXXXX)
    DIST_DIR=$(mktemp -d /tmp/otto-ott03-wheel-dist.XXXXXX)
    git -C Otto-ott03-worker archive f66ab70b8d3f772975e384760b96bafb1e957f4a | tar -x -C "$BUILD_DIR"
    env -u PYTHONPATH -u PYTHONHOME /opt/homebrew/bin/python3.11 -m pip wheel "$BUILD_DIR" --no-deps --no-build-isolation -w "$DIST_DIR"

Build return code: 0. Built artifact:

    work/ott-03-worker-receipt-20260914/otto_local_candidate-0.0.0-py3-none-any.whl

Otto wheel SHA-256: 51afd6b2f70b836f921d63e8485087007dcc139728719b0929658a088884d0cf.

Accepted Herzchen wheel installed without rebuilding or source injection:

    /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-consumer-separation-worker/work/gf01-consumer-writer-separation-worker-receipt-20260914/dist/herzchen_contracts-0.1.0-py3-none-any.whl

Accepted Herzchen wheel SHA-256: 2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc.

Fresh environment:

    work/ott-03-installed-venv-20260914

Python: 3.11.16. Otto and Herzchen installation return code: 0. Pytest installation return code: 0. PYTHONPATH and PYTHONHOME were unset for all installed-origin commands.

Installed metadata:

- otto-local-candidate 0.0.0 at work/ott-03-installed-venv-20260914/lib/python3.11/site-packages
- herzchen-contracts 0.1.0 at work/ott-03-installed-venv-20260914/lib/python3.11/site-packages
- pytest 9.1.1 at work/ott-03-installed-venv-20260914/lib/python3.11/site-packages

Import origins observed from /tmp:

- otto: work/ott-03-installed-venv-20260914/lib/python3.11/site-packages/otto/__init__.py
- herzchen: work/ott-03-installed-venv-20260914/lib/python3.11/site-packages/herzchen/__init__.py
- pytest: work/ott-03-installed-venv-20260914/lib/python3.11/site-packages/pytest/__init__.py

## Installed test run

Exact test command from outside the checkout:

    cd /tmp
    env -u PYTHONPATH -u PYTHONHOME PYTHONDONTWRITEBYTECODE=1 work/ott-03-installed-venv-20260914/bin/pytest -q \
      Otto-ott03-worker/tests/otto/test_intake_roles.py \
      Otto-ott03-worker/tests/otto/test_adapters.py \
      Otto-ott03-worker/tests/otto/test_host_adapter_usage.py

Observed output: 18 passed in 0.14s. Pytest return code: 0. The test files are candidate test inputs, but imported otto/herzchen packages resolved from the fresh venv origins above.

## Installed public API probe

The installed OttoPortfolio import was exercised from /tmp with a deterministic disposable canonical-port fixture implementing only the public execute/read port contract. It returned one pending ref fixture/work.project/installed-fixture-1@rev-1, receipt fixture-receipt-1, open.status=not_requested, executable=false, and preserved an unknown field. This is facade contract evidence only: the fixture is not Herzchen persistence and no durable product record is claimed.

The exact accepted Herzchen wheel was introspected from installed imports, with no sibling source path or sys.modules injection:

- WorkGraph is present at herzchen.domains.work.module. Observed public operations include create_pending_project, create_project, create_task, get, list, link_parent, link_dependency, observe_readiness, state_view, revise, set_lifecycle, set_readiness, and withdraw.
- ProjectSheet is present at herzchen.domains.work.sheet. Observed operations include create_pending, create_pending_project, apply, apply_project_sheet, read, export, finish, link, link_parent, link_dependency, instantiate_template, bind_route, and adopt_existing_effort.
- ProjectBatches is present at herzchen.domains.work.batches. Observed operations include create_pending, create_pending_project, apply_batch, apply_project_sheet, create_project, activate_project, observe_readiness, set_readiness, retry_materialisation, append_report, and choose_next_action.
- ContentCommandHandler is present at herzchen.content.commands. Observed public operations include build_create_document, build_append_revision, build_link, build_unlink, execute, and read.
- The direct symbol herzchen.content.commands.link_document is unavailable as an exact capability: the installed module reports no such attribute. The canonical installed document-link builder is build_link on ContentCommandHandler; no alternate direct alias was fabricated.
- ResponsibilityAssignments is present at herzchen.domains.work.assignments. Observed operations include assign, assign_responsibility, get, reassign, fence, dispatch, append_result, append_report, record_result, and report.
- AuthoringSessionService is present at herzchen.authoring.sessions. Observed operations include create_and_open, open, read, autosave, record_content_edit, finish, cleanup, release, wait, and recovery/fence validation methods.
- IdleCloseService is present at herzchen.authoring.idle with close_if_idle, check, record_content_edit, and last_content_edit.

This probe establishes installed module and endpoint availability only. No endpoint was invoked against a real writer/store, no raw SQL was used, and no product persistence or live session qualification is claimed. The earlier injected representative remains fixture evidence and is not reclassified.

## Limitations and custody

The installed run proves candidate package origins and public endpoint presence for the accepted wheel. It does not prove an Otto-to-Herzchen WorkGraph composition, a durable pending project, document/link persistence, assignment persistence, authoring checkout materialisation, live host launch, or AST behavior. The current Otto facade still requires an injected canonical operation port; absent bindings remain explicitly unavailable.

EX-HOST remains an intended boundary for host identity/receipt/session behavior, not delivered host cutover. Astrid consumer cutover, Runtime changes, controller transfer, publication, license/output grants, control DB writes, remote writes, and acceptance remain out of scope.


# SLIM: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17 19:55 UTC | SL0 | merged 81abf5c | +410/-4 | `tests/test_slim_ledger.py` (1 passed) | files: `.project/PROJECT.md`, `.project/ledger.md`, `.project/tasklist.md`, `scripts/slim_ledger.py`, `tests/test_slim_ledger.py`; measured 47,920 baseline and 11,980 threshold, 99 portfolio modules plus 38 controller modules; no deletions.
2026-10-17 20:05 UTC | SL4 | merged 9fdc4be | +22/-781 | `tests/test_usage_contract.py` (9 passed); `src/otto/portfolio/tests/test_observability_views.py`, `tests/test_portfolio_status.py`, `tests/test_host_startup_composition.py` needs the gate (AF_UNIX bind denied) | retired proof-only Events modules and wrappers; no controller files deleted; ledger regenerated. Files listed in SL4 evidence below.

### SL4 worker evidence

- Retired `src/otto/portfolio/events_candidate_proof.py` (148 lines) and `src/otto/portfolio/observability_contract.py` (387 lines), their package exports, and test-only wrappers `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` (95 lines) and `src/otto/portfolio/tests/test_observability_contract.py` (102 lines). Exact source deletion: 535 portfolio lines; proof-test deletion: 197 lines.
- Updated `src/herzchen/usage/contract.py` so its current Events seam identifies only `src/herzchen/kernel/history.py` and maintained `src/otto/portfolio/observability_views.py`. `src/otto/portfolio/tests/test_observability_views.py` now checks that the retired proof symbols are absent from the package API; `tests/test_usage_contract.py` checks the current seam list.
- Regression evidence: before removal, the new view/API check failed because `CandidateProofError` was exported, and the new Usage seam check failed because it listed the historical contract. After removal: `tests/test_usage_contract.py` passed (9 passed, 11 subtests); `src/otto/portfolio/tests/test_observability_views.py` passed 5 tests and 7 subtests, with its real Store/reader socket test needing the gate (sandbox denied AF_UNIX bind).
- Retained route checks needing the gate: `tests/test_portfolio_status.py` (10 failures at owner setup due sandbox denied AF_UNIX bind); `tests/test_host_startup_composition.py` (2 passed; host-start test needs the gate due sandbox denied AF_UNIX bind). No assertions were changed. Controller files were not deleted: the ledger's static zero-import counts did not establish absence of runtime entrypoints.
- Production/source scan across `src`, `install/controller`, `tests`, and `docs` found no remaining live import or entrypoint references to either deleted module. Pinned paths remain only inside immutable historical qualification records (`install/controller/prepared/.../runtime-manifest.json` and `src/herzchen/kernel/tests/d02-evidence/`); those records were preserved. Changed files: `.project/PROJECT.md`, `src/herzchen/usage/contract.py`, `src/otto/portfolio/__init__.py`, `src/otto/portfolio/events_candidate_proof.py` (deleted), `src/otto/portfolio/observability_contract.py` (deleted), `src/otto/portfolio/tests/test_d05_events_candidate_proof.py` (deleted), `src/otto/portfolio/tests/test_observability_contract.py` (deleted), `src/otto/portfolio/tests/test_observability_views.py`, `tests/test_usage_contract.py`.

## Questions for the orchestrator

# PINALL resume: integration culprits and D19 restore

Handle both sets of instructions before reporting.

## Integration regression instructions

# PINALL: new test failures found by the orchestrator's integration run (18 Oct)

Your lab was merged with the other checked labs onto canon/main 8edc104a in this order: SESSIONFD INVARIANTS ACTIVATEWHILE PINALL OWNERCLAIM MCPPATH DEADLAUNCH CODEXOWNER BOOTLAND FILEAUTH RELAYSAFE SAVEPATH PROOFDOC LINECHECK STOPATOM STATUSOBJ ASSESSCAP STATINDEX EVENTPAGE CITECAN ROSTERPIN OPPRE PARITYFIX ASKDISP TESTREAP CMDTMPDIR ROOTFILE INTEG-PROCLIFE-PL1.
Bisecting over that merge sequence, these tests first fail at YOUR merge (they pass at the merge before it), and they pass on canon/main:

- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_authentic_append_preserves_both_unknowns_and_global_dispatch_guard
- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_duplicate_restarts_and_changed_input_rejects
- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_every_exact_pin_is_required_and_type_sensitive
- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_fresh_disposition_requires_new_report_without_creating_callback
- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_missing_or_positive_transport_evidence_is_never_dispositioned
- tests/test_manager_preprovider_disposition.py::ManagerPreproviderDispositionTests::test_stale_valid_readback_does_not_reuse_disposition_pins
- tests/test_manager_preprovider_disposition.py::ManagerUnsupportedCliDispositionTests::test_exact_rejection_is_append_only
- tests/test_manager_preprovider_disposition.py::ManagerUnsupportedCliDispositionTests::test_positive_or_missing_effect_evidence_rejects
  (full output of the integrated run: ~/Developer/otto-program/ops/integ/runs-head/test_manager_preprovider_disposition.py.txt; bisect log: ~/Developer/otto-program/ops/integ/bisect-test_manager_preprovider_disposition.log)

Rebase your lab onto canon/main first (the integrated labs will be on it after the orchestrator's push), reproduce the failure there, and fix your change so these tests pass without weakening them, adding time limits, or patching product code from tests. Then run your check and these files, commit, and report.

This is in addition to the D19 SEND BACK in ops/reviews/D19-PINALL.md.sendback (remove the added timeouts and sleep 60).


## Astra D19 send-back

# D19 decision (Astra for the orchestrator, 2026-10-18): tests/test_capacity_holds.py, tests/test_capacity_pool.py, tests/test_claude_manager_admission.py

Decision: SEND BACK

- `tests/test_capacity_holds.py`: The empty-group expectation now releases capacity while retaining the custody fence (`tests/test_capacity_holds.py:170`, `tests/test_capacity_holds.py:172`). This is explicitly requested by the row and authorized at `ops/requests.md:1386`. The surviving-member check remains (`tests/test_capacity_holds.py:185`), so premature release still fails. Product behavior matches at `src/otto/portfolio/execution_host.py:862`.
- `tests/test_capacity_pool.py`: Invalid pins now raise instead of silently succeeding (`tests/test_capacity_pool.py:443`, `tests/test_capacity_pool.py:450`, `tests/test_capacity_pool.py:453`, `tests/test_capacity_pool.py:528`), as required by mandatory registration. Profiling preserves the owner-thread assertion without replacing a product method (`tests/test_capacity_pool.py:487`, `tests/test_capacity_pool.py:508`). However, the added `process.wait(timeout=5)` at `tests/test_capacity_pool.py:418` violates the no-time-limits rule (`PLAN.md:486`).
- `tests/test_claude_manager_admission.py`: The exited-child expectation changes from unknown with stream diagnostics to explicit registration failure, terminal failed settlement, and no capacity hold (`tests/test_claude_manager_admission.py:420`, `tests/test_claude_manager_admission.py:425`). This follows registration now rejecting the child before stream parsing (`src/otto/agents/claude_cli.py:381`). The added no-input and absent-group checks remain regression-sensitive (`tests/test_claude_manager_admission.py:265`, `tests/test_claude_manager_admission.py:267`). However, new five-second waits (`tests/test_claude_manager_admission.py:387`, `tests/test_claude_manager_admission.py:396`) and the expiring live-group fixture (`tests/test_claude_manager_admission.py:380`) introduce timing dependencies.

Restore:
Replace the three newly added `process.wait(timeout=5)` calls at `tests/test_capacity_pool.py:418` and `tests/test_claude_manager_admission.py:387`, `tests/test_claude_manager_admission.py:396` with `process.wait()`.
Replace `['sleep', '60']` at `tests/test_claude_manager_admission.py:380` with `[sys.executable, '-c', 'import signal; signal.pause()']`, retaining `start_new_session=True`, explicit SIGKILL cleanup, and every subsequent assertion. Keep the authorized assertion reversals and owner-thread observation.

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

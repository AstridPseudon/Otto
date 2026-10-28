# ROSTERPIN: new test failures found by the orchestrator's integration run (18 Oct)

Your lab was merged with the other checked labs onto canon/main 8edc104a in this order: SESSIONFD INVARIANTS ACTIVATEWHILE PINALL OWNERCLAIM MCPPATH DEADLAUNCH CODEXOWNER BOOTLAND FILEAUTH RELAYSAFE SAVEPATH PROOFDOC LINECHECK STOPATOM STATUSOBJ ASSESSCAP STATINDEX EVENTPAGE CITECAN ROSTERPIN OPPRE PARITYFIX ASKDISP TESTREAP CMDTMPDIR ROOTFILE INTEG-PROCLIFE-PL1.
Bisecting over that merge sequence, these tests first fail at YOUR merge (they pass at the merge before it), and they pass on canon/main:

- tests/test_rosterpin.py::RosterPinTests::test_unrelated_unadmitted_sheet_task_preserves_admitted_a_launch
  (full output of the integrated run: ~/Developer/otto-program/ops/integ/runs-head/test_rosterpin.py.txt; bisect log: ~/Developer/otto-program/ops/integ/bisect-test_rosterpin.log)

Rebase your lab onto canon/main first (the integrated labs will be on it after the orchestrator's push), reproduce the failure there, and fix your change so these tests pass without weakening them, adding time limits, or patching product code from tests. Then run your check and these files, commit, and report.

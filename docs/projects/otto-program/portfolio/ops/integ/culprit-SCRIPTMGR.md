# SCRIPTMGR: new failure in integration round 2 (18 Oct)

Merged onto canon/main 82b1976 after PINALL, INTEG-PROCLIFE-PL1, MCPPATH, DEADLAUNCH, ROSTERPIN, PARITYFIX, this test passes at the merge before yours and fails at your merge:
- tests/test_perch.py::SeededFaultRunTests::test_each_seeded_fault_fails_its_assertion_kind
  The seeded fault 'staging-at-rest-clean' is no longer caught: every assertion reports pass (tests/test_perch.py:2330). Output: ~/Developer/otto-program/ops/integ/runs-head/test_perch.py.txt; bisect: ops/integ/bisect-r2-perch.log.
Your scripted manager must still let each seeded fault fail its own assertion kind. Rebase onto canon/main (round 2's first six tasks will be there), reproduce, fix without weakening the seeded-fault test or adding time limits, run tests/test_perch.py whole, commit and report.

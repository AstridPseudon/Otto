# LABPIN: new failures in integration round 3 (18 Oct)

Merged onto canon/main 3d91a35, your lab breaks these tests; they pass on canon/main itself (checked 19:4xZ):
- tests/test_hostctl_serve.py: 4 tests, including EscalationTests::test_manager_escalates_the_orchestrator_answers_and_the_manager_applies_it and ManagerLoopTests::test_manager_dispatches_normal_and_xhard_workers_and...
- tests/test_reworkwire.py::test_conflicting_done_reworks_exact_worker
Outputs: ~/Developer/otto-program/ops/integ/runs-head/test_hostctl_serve.py.txt and test_reworkwire.py.txt (run on the round-3 head); bisect logs ops/integ/bisect-r3-*.log.
Rebase onto canon/main, reproduce, fix your change (not the tests), run both files whole plus tests/test_fleet_custody.py, commit and report.

# OBSOWNER: new failures in integration round 3 (18 Oct)

Merged onto canon/main 3d91a35, your lab breaks these tests; they pass on canon/main itself (checked 19:4xZ):
- tests/test_hostctl_serve.py: 4 tests, the same escalation and manager-loop tests LABPIN also broke (both were green on canon)

Outputs: ~/Developer/otto-program/ops/integ/runs-head/test_hostctl_serve.py.txt and test_reworkwire.py.txt (run on the round-3 head); bisect logs ops/integ/bisect-r3-*.log.
Rebase onto canon/main, reproduce, fix your change (not the tests), run both files whole plus tests/test_fleet_custody.py, commit and report.

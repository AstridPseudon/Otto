# XFERMAP: new failures found by integration round 5 (18 Oct, on canon a70b3f2)

Bisecting the round-5 merge sequence, these tests first fail at YOUR merge and pass on canon/main:

- tests/test_supervisor_direction_client.py::ExecutionApplicationTests::test_parent_finishes_while_child_keeps_command_status_and_result_custody
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_supervisor_direction_client.py.txt)
- tests/test_bounded_project_host.py::BoundedProjectHostTests::test_five_projects_share_slots_and_A_settles_while_B_waits
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_bounded_project_host.py.txt)

Rebase onto canon/main, reproduce, fix your change (not the tests: no weakening, no time limits, no product patches from tests), run these files whole, commit and report.

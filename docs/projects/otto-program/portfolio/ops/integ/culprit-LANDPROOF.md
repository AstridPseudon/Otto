# LANDPROOF: new failures found by integration round 5 (18 Oct, on canon a70b3f2)

Bisecting the round-5 merge sequence, these tests first fail at YOUR merge and pass on canon/main:

- tests/test_coordinator_launch_policy.py::CoordinatorLaunchPolicyTests::test_owner_claude_write_done_captures_before_landed_lab_removal
- tests/test_coordinator_launch_policy.py::CoordinatorLaunchPolicyTests::test_owner_claude_write_done_removes_landed_lab_after_rejected_capture_acceptance
- tests/test_coordinator_launch_policy.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_captures_before_landed_lab_removal
- tests/test_coordinator_launch_policy.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_removes_landed_lab_after_rejected_capture_acceptance
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_coordinator_launch_policy.py.txt)
- tests/test_fleet_custody.py::test_worker_facade_check_is_feedback_and_done_lands_only_its_bound_lab_and_line
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_fleet_custody.py.txt)
- tests/test_reworkwire.py::test_conflicting_done_reworks_exact_worker
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_reworkwire.py.txt)
- tests/test_external_owner_execution.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_captures_before_landed_lab_removal
- tests/test_external_owner_execution.py::ExternalOwnerExecutionTests::test_owner_claude_write_done_removes_landed_lab_after_rejected_capture_acceptance
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_external_owner_execution.py.txt)

Rebase onto canon/main, reproduce, fix your change (not the tests: no weakening, no time limits, no product patches from tests), run these files whole, commit and report.

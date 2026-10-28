# CMDTMPDIR: new failure in integration round 2 (18 Oct)

Merged last in round 2, this test passes at the merge before yours and fails at yours:
- tests/test_native_resume_trace.py::NativeResumeTraceTests::test_delayed_exact_message_uses_existing_finite_admission_budget
  The admission retry now sleeps [6, 12, 18, ... 60] instead of [6, 12] (tests/test_native_resume_trace.py:48): the delayed message is never admitted within the existing finite budget, so something your change does to the command facade's temp folder or socket makes the second retry fail. Output: ~/Developer/otto-program/ops/integ/runs-head/test_native_resume_trace.py.txt; bisect: ops/integ/bisect-r2-native.log.
Rebase onto canon/main, reproduce, fix your change (not the test), run this file and tests/test_fleet_custody.py, commit and report.

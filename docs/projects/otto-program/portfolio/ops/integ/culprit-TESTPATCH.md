# TESTPATCH: new failures found by integration round 5 (18 Oct, on canon a70b3f2)

Bisecting the round-5 merge sequence, these tests first fail at YOUR merge and pass on canon/main:

- tests/test_hostctl_serve.py::EscalationTests::test_manager_escalates_the_orchestrator_answers_and_the_manager_applies_it
- tests/test_hostctl_serve.py::ManagerLoopTests::test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results
- tests/test_hostctl_serve.py::ServeTests::test_activation_launches_the_manager_which_authenticates_and_reads_its_documents
- tests/test_hostctl_serve.py::WorkerWorkspaceCompositionTests::test_codex_worker_fake_stream_calls_tools_lands_and_owner_captures_before_lab_cleanup
  (output: ~/Developer/otto-program/ops/integ/runs-head/test_hostctl_serve.py.txt)

Rebase onto canon/main, reproduce, fix your change (not the tests: no weakening, no time limits, no product patches from tests), run these files whole, commit and report.

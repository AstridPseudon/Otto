# SAVEFIX: repair the landing regression

The landing sweep found a new reproducible failure in
`tests/test_events_final_corrections.py::_HistoryFixture::test_batch_children_have_exact_parent_facets_without_child_events`.
It passes on canon and fails 3/3 on the rebased lab. See
`ops/runs/SAVEFIX/.gate/pair-1-lab1.txt`: a follow-up sheet containing only
`{'id': 'A', 'lifecycle': 'active'}` raises `WorkValidationError` because the
existing task's title is lost and the update is treated as a new task.

Fix the regression in the existing SAVEFIX scope. Preserve the existing task
fields when a submitted sheet updates only some fields. Add a focused regression
test, run the task's required check, and report any additional affected paths
before editing outside the current brief's authorized files. Do not alter test
assertions to hide the production failure. Keep the D19-SAVEFIX decision and
all previous accepted behavior. Commit nothing; the launcher owns the commit.

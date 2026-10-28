# REDS resume 2: fix the two new landing regressions

The REDS landing was refused at 2026-10-16T21:26:52Z. After rebasing this lab onto current canon, fix these two NEW failures without weakening assertions:

- `tests/test_issue_metadata_inventory.py::IssueMetadataInventoryTests::test_reports_use_inventory_and_metadata_preserving_old_and_result_bodies`
- `tests/test_owner_issue_scoped_streams.py::ScopedIssueStreamTests::test_old_manager_revision_and_transferred_supervisor_survive_without_global_hydration`

Both reproduce 3/3 on the rejected REDS commit and 0/3 on BASE. They concern `OwnerIssueReaders` report selection and history retention. The original REDS brief owns `src/otto/portfolio/owner_issue_loop.py`; add these two test files to this repair's scope. Do not change test assertions. Keep all other files within the original REDS brief's scope, and don't overlap another task's files.

First reproduce the exact selectors on the rebased lab, then make them pass. Run the focused selectors after the fix and the REDS brief's full check command if practical; do not stop a long test run before it exits. Report red/green evidence, changed files, and any remaining issue. The existing 31 ASK BASE failures across five files are outside this repair.

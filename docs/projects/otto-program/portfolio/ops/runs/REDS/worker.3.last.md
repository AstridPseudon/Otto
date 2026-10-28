Reproduced both failures on the rebased lab: each raised `TypeError` because `reports()` called `list_events(subject_kinds=...)`, while the scoped readers accept stream queries.

Updated [owner_issue_loop.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/REDS/src/otto/portfolio/owner_issue_loop.py) to select assignment history from inventory and project events, then read report/result subjects from each assignment’s stream. It uses metadata-only subject reads when available and preserves the filtered-index compatibility path. No assertions or tests were changed.

**Green:** both requested selectors passed (**2 passed**); the full two test files passed (**3 passed** and **2 passed**). `d03_status_reads.py` also passed in the full check, and `git diff --check` passed.

The full REDS check completed with **31 failed, 159 passed, 4 skipped, and 38 subtests passed**. The 31 failures are the out-of-scope BASE failures identified in the brief. Only `owner_issue_loop.py` is modified; no commit was created.
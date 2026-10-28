Implemented retirement in the Herzchen work domain and added Otto’s `retire REF --reason ... --by REF` command. Retired records retain their reason and successor, preserve revision history, and are terminal for readiness, dispatch, and ordinary edits. Show and status include successor details; save rejects dependencies on retired tasks without redirecting them. The sheet path also retires document memberships through retained association revisions.

The regression run initially showed that save accepted a retired dependency and show omitted retirement details. Those regressions now pass. I did not check out canon to run a canon-first comparison.

**Checks:** The requested command passed once: **47 passed, 15 subtests passed**. After the final association compatibility adjustment, its focused document membership and successor display tests passed (**2 passed**). A later full rerun printed the passing test summary but hung during pytest shutdown; the four non-boundary files also reported **43 passed, 15 subtests passed** before shutdown hung. `git diff --check` passed.

Changes are uncommitted on `lab/RETIRE` for the launcher. No additional files are needed.
Implemented the liveness changes in the lab. Clients now fail fast with closure details and restart guidance; `otto wait` reports owner-down during shutdown or socket loss and exits nonzero; non-running service status includes a reason and restart command; and an unrequested closed service run returns an error exit status.

The acceptance tests failed on the baseline behaviors, then passed after the fixes:

- **Red:** The new checks exposed missing closure details, owner-down reporting, status advice, and exit-code handling.
- **Green:** `33 passed, 2 subtests passed` across the four task-owned test files.
- `git diff --check` passed.

The requested `otto-heavy` command could not run because `otto-heavy` is not on PATH. I ran its pytest payload directly. No new commit was created; the lab remains on base commit `5a99f2f183264f903df84cff6f1df54b971f33df` for the launcher to commit.
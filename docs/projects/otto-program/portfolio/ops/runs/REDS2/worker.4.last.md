**The scale subclass change is in place.** It excludes the two live-bound proofs and filters out the `None` overrides during test loading. No production bounds or assertions changed.

Checks passed:

- `tests/test_otto_open_release.py`: 36 passed, 8 subtests passed.
- Both named proofs run directly on `ProjectFolderProof`: 2 passed.
- `tests/test_project_folder_scale.py`, run alone twice: 51 passed and 16 subtests passed on each run.
- `git diff --check`: passed.

The contradiction was: **256 MiB configured limit; 21 KiB aggregate bounded, 16.3 KiB single rejected, 25 KiB document imported.**

I cleared the remaining conflict markers in four portfolio files so tests could collect, preserving the canon command list and combining the assessment evidence-grant behavior. No conflict markers remain in the portfolio sources, and I did not change `manager_journey_service.py` in this turn. However, Git still reports those four files as `UU`: the read-only `.git` index prevents formally staging the resolutions. I left them for the launcher; no commit was made.
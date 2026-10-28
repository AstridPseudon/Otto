The conflict markers are gone, and the merged `perch.sh` retains canon’s stage 2 fault hooks plus SKEL0’s stage 4 `conflict` and `owner` hooks. Stage 2 owner dispatch and stage 4 scenarios remain intact. I found no unrelated file damage; `tests/test_perch.py` was not edited.

The worktree is **content-resolved but not Git-index-resolved**: `git status` still shows `UU ops/bootstrap/perch.sh` and `git ls-files -u` lists its three index stages. Clearing that state requires writing shared Git metadata, which this sandbox forbids. I left it untouched for the launcher. The supplied `land.log` contains only the 12:40:45Z refusal line, not the later conflict context described in your message.

Checks:

- `.brief.md` command, `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_perch.py tests/test_perch_stage1.py tests/test_perch_staging.py tests/test_perch_timeline.py` — **85 passed, 20 failed, 57 subtests passed** in 25m15s. The census failure and fake perch/report failures hit `PermissionError: Operation not permitted: 'ps'`; the seeded-fault subtests then lacked reports. Five staging tests timed out starting `staging.sh up`. These are sandbox/environment failures for the landing gate to verify.
- Conflict-marker scan, `git diff --check`, `bash -n`, JSON parsing, and Python compilation — **passed**.

No commit was made. Stage 4 owner-driven execution and the real Claude journey remain incomplete and unproven.
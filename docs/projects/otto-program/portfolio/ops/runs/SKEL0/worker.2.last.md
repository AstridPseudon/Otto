The three conflicted files are **resolved in the working tree**, but the rebase is **not complete**. `git add` failed because Git could not create `${TRANSFER_ROOT}/source/otto/.git/worktrees/SKEL0/index.lock` (`Operation not permitted`). I did not retry the blocked metadata write. Git still reports those files as unmerged, so the launcher will need to stage them and continue the rebase outside this sandbox.

Resolution choices:

- `project.json`: kept canon’s stage 2 configuration and added SKEL0’s stage 4 canary.
- `perch.sh`: kept the stage 2 owner-driven scenario and stage 4 scenarios; the task loop now skips stage 2’s owner-managed tasks and real stage 4 tasks, while retaining fake stage 4 execution.
- `perch_report.py`: kept stage 2’s owner-managed task timeline handling and stage 4’s landing-conflict metadata.

The named `ops/runs/SKEL0/land.out` and `land.log` were not present in the lab or at the workspace’s expected repo-root path, so I could not read that log. I resolved the conflicts using Git’s conflict stages and the current canon versions.

Verification: `tests/test_perch_stage1.py -k 'StageFour'` passed (**5 passed, 19 deselected**); JSON parsing, `bash -n ops/bootstrap/perch.sh`, and `git diff --check` passed. I did not run the brief’s full focused command because it includes staging/census paths that previously failed on prohibited `ps` operations.

The stage 4 owner-driven and real Claude journeys remain incomplete and unproven. No commit was made.
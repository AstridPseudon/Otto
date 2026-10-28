The focused check passes on the current lab: **47 passed, 15 subtests passed**.

I inspected `4800623`, the aborted rebase reflog, and canon `85dbb13`. Canon includes SAVEFIX changes in `batches.py` and additional save regressions; those need to remain alongside RETIRE’s terminal-retirement guard, retired-dependency refusal, and regression. I made no file changes in this turn.

I could not complete the rebase: Git failed before starting because it could not create rebase metadata at `${TRANSFER_ROOT}/source/otto/.git/worktrees/RETIRE/rebase-merge` (`Operation not permitted`). That shared `.git` path is outside the writable lab. The lab remains clean at `4800623`; the rebase still needs to be retried where that Git metadata is writable.
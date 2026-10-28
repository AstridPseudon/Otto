Resolved the conflict in [register.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/STAGESETUP/src/otto/hostctl/register.py), preserving canon’s `source_bundle` and STAGESETUP’s `assessment_scope`, `raw_sha256`, and task `otto.plan` behavior.

**The rebase is not complete:** Git still reports `register.py` as unmerged (`UU`). Normal `git add` failed because Git could not create `.git/index.lock` (`Operation not permitted`). I did not work around the read-only `.git` boundary, so the index cannot be marked resolved here.

The original brief check completed: **36 passed, 8 failed, 2 subtests passed.** The failures were two sandbox preflights (`sandbox_apply: Operation not permitted`) and six staging startup timeouts after the tree checkout. The history replay assertion passed in this run.

`git diff --check` passed. No files outside the brief’s owned list were changed. The lab is at canon `08ec5201597c985e552e6e7d0422775475c82d34`, with the conflict resolution in the working file; the index still needs the launcher to resolve and continue the rebase.
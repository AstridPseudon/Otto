The xhard answer-file failure is **not reproducible in this lab**. The exact target test stops earlier: `start-manager` returns `unknown` because `sandbox-exec` reports `sandbox_apply: Operation not permitted`. The worker dispatch never runs here.

The brief’s exact check command finished with **22 passed, 4 skipped, 3 failed**. All three failures are manager-start tests blocked by that same sandbox error. I found no A4 landing log or recorded BASE in the lab to compare against.

I found no change in A4’s worker route or launch logic: registration reparses the same source files, and the serve change only adds generated-view authority metadata. That gives no evidence that A4 caused the landing’s xhard omission, but the landing-specific symptom remains unverified without a run that gets past manager startup.

I made no changes and did not alter any assertions. The lab worktree remains clean on `lab/A4`; nothing was landed or pushed.
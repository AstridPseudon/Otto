**FDLEAK is ready for the launcher to commit** on `lab/FDLEAK`. No commit was made; the lab is still based on `3f7843d1` (`canon/main`).

The owner now reuses its direction binding and late usage facade for the session, so repeated calls no longer create listening sockets. A different native body provider is rejected before opening a facade. Automatic dispatch fences persistent prelaunch failures until the admitted revision changes, while a readiness or capacity race remains eligible on a later pump. The socket client also closes its makefile stream explicitly.

Checks:

- Requested focused suite: **32 passed, 1 skipped**. The skip is the existing socket cleanup test’s home-directory write, denied by this sandbox.
- Nearby owner tests: **35 passed, 28 subtests passed**.
- `git diff --check`: passed.
- Stage 2 `--fake`: **not run**. Its staging root is outside this lab, and its restart uses a committed ref, so it cannot verify these uncommitted changes here. The landing gate must run it.

The additional file [owner_bootstrap.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FDLEAK/src/otto/portfolio/owner_bootstrap.py:580) was necessary because it contained the repeated facade construction. That per-call construction was replaced with session reuse; the immediate retry of persistent prelaunch refusals was replaced with a revision gate in [dispatch.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FDLEAK/src/herzchen/fleet/dispatch.py:183).

**Sub-agents:** `trace_owner` and `trace_tests` investigated read-only. `fix_facades` made the facade changes; I corrected its missing `__slots__` fields and tightened the late usage cache to one provider. `fix_retry` made the dispatch change; I corrected its handling of transient readiness races and misleading error text. `add_tests` added and ran the regressions; I directed it to cover both 500-cycle descriptor counts and changed-revision retries.
Implemented fail-closed alias resolution and strict actor decoding. Conflicting review or policy pins now hold readiness with blockers naming the aliases and values; malformed supplied aliases are rejected, and matching legacy aliases remain valid. Actor decoding requires an explicit `authenticated` field equal to literal `True`, including through tagged-wire construction.

**Runs**

- Baseline, before implementation, was red: the conflicting-pin and actor cases failed against the canon-derived code.
- After implementation, the targeted conflict, malformed-alias, digest, and actor tests passed: **5 passed, 5 subtests passed**.
- The requested full focused command still has pre-existing activation failures: **6 failed, 8 passed, 5 subtests passed**. The activation and recovery cases call a missing `ReviewedPlanActivation._admit` method. I left those existing assertions unchanged.
- `git diff --check` passed. No assertions were changed.

**Files changed**

- [reviewed_activation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED2/src/otto/portfolio/reviewed_activation.py)
- [test_reviewed_activation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED2/src/otto/portfolio/tests/test_reviewed_activation.py)
- [model.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED2/src/herzchen/contracts/model.py)
- [test_authenticated_actor_decode.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILCLOSED2/tests/test_authenticated_actor_decode.py)

No D19 assertion changes. The missing `_admit` method is the remaining blocker to a green full focused run.
Updated only the newly authorized [drain test fixture](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/DISPATCH/tests/test_admitted_transport_drain.py). It now supplies a current assignment, a digest-verified admitted task, and project/dependency readers. The admission guard and every drain assertion remain intact.

**Red → green:** the landing sweep had reproduced the regression 3/3 in the lab and 0/3 on BASE. A local run failed before the fixture change; the exact regression now passes, and the full drain file passes **2/2**.

The `.brief.md` check with the drain file added finished **79 passed, 7 failed**. The drain tests passed; all seven failures are the existing custody tests that require `ps`, which this sandbox denies. No other landing failure reproduced locally. The Luna sub-agent made the fixture change; I reviewed the exact record identities and diff. `git diff --check` is clean.

The change is uncommitted for the launcher. I did not request landing; the ordered queue can handle it after this resume exits.
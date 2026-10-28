- **blocking — [land.sh:330](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:330):** With `--batch A B` where A contains B’s commits, B is dropped as already included. The accepted-only check loop at line 444 skips B’s check—even if it fails—while B’s work lands through A, without its own `Land B:` commit.

- **blocking — [land.sh:745](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:745):** The candidate guard checks dirtiness, not HEAD equality. A check that cleanly checks out `canon/main` makes subsequent tests and staging examine BASE, while line 758 lands the original, saved `DIFF_REF`. An unjudged candidate can land.

- **blocking — [land.sh:758](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:758):** A signal after canon’s fast-forward but before push bypasses rollback: the trap at line 45 exits directly. Canon advances while GitHub remains unchanged and the result says refused. A signal after remote acceptance but before `LANDED` is assigned can likewise misreport a completed landing.

- **blocking — [land.sh:771](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:771):** If GitHub accepts the push, its acknowledgement is lost, and `ls-remote` also fails, the gate resets local canon and reports refusal although GitHub contains the batch. An unknown push outcome is treated as definite rejection.

- **blocking — [land.sh:97](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:97), [test_bootstrap_gate.py:296](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/tests/test_bootstrap_gate.py:296):** Two prohibited deadlines are introduced. The whole-gate wrapper inherits heavy’s [60-minute default](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/heavy.py:438), enforced at line 396; the new signal test fails after five seconds. The aggregate deadline also changes single-task behavior.

- **should-fix — [land.sh:469](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:469):** Sweep selection uses the final candidate’s net diff, not the union of task changes. If dependent B reverts a file changed by A, that file disappears from sweep selection despite appearing in A’s task manifest.

- **should-fix — [land.sh:567](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:567):** Attribution misses ordinary multiline imports such as `from otto import (` followed by `mod` on another line. A failure importing B’s changed `src/otto/mod.py` can be reported as unattributed, preventing the promised task identification.

- **should-fix — [land.sh:37](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:37):** `LAND RESULT` is printed before heavy cleans descendants and releases slots. Heavy can then append a [cleanup message](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/heavy.py:412) to the manager’s combined output. The result is neither guaranteed last nor proof cleanup finished; this affects single-task runs too.

- **should-fix — [manager_loop.py:101](${TRANSFER_ROOT}/portfolio/ops/manager_loop.py:101):** The existing manager rejects `["land.sh","--batch","A","B"]` because its second argument must be a task ID. Its landing handler at line 117 supports only single-task options, so the intended managed batching workflow remains unavailable.

- **note — [land.sh:74](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:74):** The ordinary independent-lab path enforces eight tasks, creates ordered merge commits, drops textual conflicts, and pushes once. D19 remains per-task at lines 244–315; orphan, added-test and staging phases remain present at lines 703–741. No batch-specific missing-D19 bypass was found.

- **note — [land.sh:97](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:97):** One weighted lease wraps the gate; pytest runs directly at line 397. The real heavy wrapper’s [finally cleanup](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/heavy.py:403) reaps descendants and releases slots; the apparent missing shell-worker cleanup alone is not a confirmed leak.

- **note — [land.sh:643](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh:643):** Claim 6 holds: parallel waves feed serial, ordered judging; all new failures in the first failing file are recorded before stopping later waves. Already-started files finish before judgment.

- **note — [test_bootstrap_gate.py:63](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/tests/test_bootstrap_gate.py:63):** Tests exercise real scratch Git repositories and a bare remote, without patching gate code. Heavy is stubbed. The authorized test run could not start because the read-only sandbox provided no writable temporary directory; the reported passes were not independently reproduced.

Blocking findings: 5
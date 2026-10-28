LANDBATCH is ready for review in the current lab. [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH/ops/bootstrap/land.sh) now holds one heavy lease for the full gate, weighted by `OTTO_GATE_JOBS` (default 2), with pytest running inside it directly. The parallel sweep stops scheduling later waves after the first file with confirmed NEW failures and reports every NEW failure from that file with batch task attribution. Already-running files in the same wave may finish. Single-task behavior and batch push custody remain covered by the gate tests.

The required check passed: **68 passed in 144.94s**. Two new regressions failed against the pre-amendment gate, then passed with the changes. `git diff --check` is clean. No files were added, and no commit, push, or landing was run.

A Luna sub-agent made the edits and ran the checks. I reviewed the diff and corrected its initial serial sweep approach and signal handling, including HUP forwarding.

D19 request: LANDBATCH
Implemented the landing evidence path on `lab/LANDEVIDENCE`; all changes are **uncommitted**. The [Otto landing adapter](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDEVIDENCE/src/otto/hostctl/fleet_landing.py:229) rechecks the exact passing sealed runner result, retains its receipt through the existing Evidence handler, and passes that verified revision ref through `freeze-input`, assessment, and acceptance. No commit, candidate, or placeholder is used as an evidence ref.

The regression now drives admitted work and a worker dispatch through real `done`, then verifies the frozen ref, accepted decision, and [transactional task completion](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDEVIDENCE/tests/test_fleet_custody.py:902). Failed checks, a different commit, missing evidence, and unresolvable evidence refuse without advancing the line.

Additional files were required:

- [owner.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDEVIDENCE/src/otto/hostctl/owner.py:29): supplies the Evidence handler lazily for the normal owner runtime.
- [owner_bootstrap.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDEVIDENCE/src/otto/portfolio/owner_bootstrap.py:696): passes the resolver to completion and permits an earlier scope revision only when task content still matches.
- [assignments.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDEVIDENCE/src/herzchen/domains/work/assignments.py:181): verifies managed evidence in both completion readback and the transactional completion gate.

Luna agents handled production wiring, regression tests, and an independent evidence-path review. I reviewed their work against the exact-check invariant. `git diff --check` passes. The requested test command completed with **35 passed, 8 failed**; all eight failures are custody process tests blocked by this worker sandbox’s `sandbox-exec` or `ps` permissions. No staging-owner tests were run.

Two handoff limits remain: `ops/brief-template.md` was absent from this checkout, and this worker Python cannot import Astrid’s managed pack loader. Evidence capture fails closed if the staging runtime also lacks that dependency; the orchestrator’s stage 2 rerun must verify it.
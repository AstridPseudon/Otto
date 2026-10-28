# D19 decision: COMPOSEFLEET, tests/test_hostctl_serve.py manager-loop test (the orchestrator, 16 Oct 2026)

**Decision: LAND.** No Opus call was made.

- **What changes:** `test_manager_dispatches_normal_and_xhard_workers_and_is_resumed_with_results` asserted that each route's answer file exists in the project root. It now asserts that exactly one answer file exists in each task's own assignment lab (`<repo>.otto-labs/**/<task id>/`), after a status read. Its fixture gets a disposable repo and `otto.plan` data, which the canonical lab resolver needs. `test_fleet_custody.py`'s fixture passes the current project revision, and the file gains a test that a project revision advance keeps a still-linked task's lab and refuses an unlinked one.
- **Why it's right:** COMPOSEFLEET's row is that a dispatched worker's workspace is its assignment's lab, one path. "The answer file is in the project root" is the old behaviour the row removes. The new assertion is stricter: exactly one file, in the right lab. It also turns canon's long-standing red (STAGE1 F11, "xhard-route worker did not run") green.
- **Scope:** these two files only.

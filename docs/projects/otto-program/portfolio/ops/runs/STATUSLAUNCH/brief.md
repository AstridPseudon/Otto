# Brief: STATUSLAUNCH (normal, 0.5 focused days)

**Outcome:** `project status` reports the actual automatic dispatch path state for each task: launched once a task has started, completed/landed once done, and unknown or failed with its reason when appropriate. Read the row in `projects/program/tasklist.md` for the full behavior.

**Why it matters:** Stage 2 on canon `f5036d2` dispatched A and B, landed and accepted them, and completed them in dependency order, but status continued to report `dispatch: admitted`, leaving the harness waiting for work that had already completed.

**Your lab:** `labs/STATUSLAUNCH`, on branch `lab/STATUSLAUNCH`, from `canon/main` at `f5036d26df14de9ae2e9391582bac92d7c30a385`. Work only here.

**Layer:** Otto product. New code belongs in `src/otto/hostctl/cli.py`, the owner-facing project status projection.

**Files you own:**
- `src/otto/hostctl/cli.py` — project status dispatch projection (`_task_dispatch_status`, around line 600).
- `tests/test_hostctl_cli.py` — retained-record projection tests and project status CLI coverage (around lines 297, 353).

**Other files:** You may edit any other file the outcome directly requires, except those under Do not touch. Report each extra file and why.

**Do not touch:** No worker files are running. Do not touch `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects, vision or Native5, or anything outside this lab.

**Build on what exists:** `src/otto/hostctl/cli.py:557-557` projects dispatch into each task row; `src/otto/hostctl/cli.py:600-642` currently derives it from retained assignment/dispatch/result/report records. Inspect the automatic pump's retained schedule/start outcome and lifecycle so status reports actual owner records instead of inferring launch from schedule existence.

**Your check.** Add or update a regression that exercises real owner status across automatic dispatch and completion, and verifies launched after start and completed/landed when done; preserve failed/unknown reasons and admitted before dispatch. Stage 2 `--fake` dispatch, settle, dependency-order, kill-recovery and census checks are run by the landing gate/orchestrator, not inside your worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_cli.py`

**Regression at the level the friction appears:** project status after automatic dispatch and after worker completion.

**Working rules:** Build on existing code. Never run `ottoctl`, and never pass it `--help`. Never wait, stash, or check out another commit in the lab. On Codex, do not commit; leave your work for `run-task.sh` to commit. Long test runs must have a long timeout and run to completion. Never run staging-owner tests in the worker sandbox.

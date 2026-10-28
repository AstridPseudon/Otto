# LANDBATCH resume 2: apply the full orchestrator ruling

Apply every item in the orchestrator's ruling at `${TRANSFER_ROOT}/portfolio/ops/reviews/LANDBATCH-restore.md` to the LANDBATCH implementation. The ruling is authoritative. In particular:

1. Remove time limits from the whole-gate heavy lease (the 60-minute default must not apply; use/add a no-deadline option) and replace any signal-test deadline with event-driven waiting. Keep the signal-test fix from resume 1.
2. Push the complete candidate first, using the expected old remote value. Advance local canon/main only after confirmed push success. Remove the now-unneeded rollback path. If push acknowledgement and `ls-remote` both fail, report `LAND RESULT: unknown push outcome ...` and leave local canon unchanged. Fetch before the next landing. Signals must never leave local canon ahead of GitHub.
3. Judge every batch task, including tasks whose commits are contained in another task: run its own check and D19 and report its outcome. After each check, guard that HEAD still equals the candidate and refuse if a check moved it.
4. Select sweep files as the union of each task's own changed files.
5. Attribute imports with Python `ast`, including multiline `from otto import (...)` forms.
6. Print the final `LAND RESULT:` line only after heavy has released slots and reaped children; print it outside the heavy wrapper.
7. Raise the batch cap from 8 to 40.

Add a real gate test for each numbered item. Preserve scratch Git repositories and a bare remote. Do not touch `ops/manager_loop.py`; the orchestrator already added the `land-batch` effect. Work in the LANDBATCH lab. The existing task-owned files are `ops/bootstrap/land.sh` and `tests/test_bootstrap_gate.py`; edit another file only when directly required by the outcome, and report it. Do not touch files owned by other tasks.

Run the full check command from the lab: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`. Report the exact changed files and test result. Leave changes for the launcher to commit; do not commit or push yourself. Follow every XHARD rule in the original brief and template, including the red/green regression requirement where applicable and long test timeouts.

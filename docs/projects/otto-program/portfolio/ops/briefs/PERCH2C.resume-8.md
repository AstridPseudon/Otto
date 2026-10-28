# Resume: PERCH2C (xhard)

Resume the existing PERCH2C worker in the same Sol session after rebasing on current canon. Preserve its committed work and apply the Orchestrator's 2026-10-17T22:47:15Z ruling to the second SEND BACK restore.

In `ops/bootstrap/perch.sh`, remove the 90-second marker deadline, 30-second capacity deadline, and 90-second first-worker deadline, including their `date` comparisons. Keep the `sleep 0.25` polling loops for the marker and owner status receipts. Each loop must have no time limit and must end only when its required evidence appears or the owner process is gone; if the owner is gone first, fail and name the missing evidence. Do not replace polling with a busy loop, retries, or a fixed delay. Run-level hang detection handles hangs.

Preserve the restored exact seeded-failure assertions and real temporary Store capture in `tests/test_perch.py`, all other assertions, and ORPHANWORKER's census lines in `ops/bootstrap/perch.sh` and `ops/bootstrap/perch_report.py`. Make only the targeted wait changes and necessary focused regression updates. Do not run stage 2 or start a staging owner.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, anything outside this lab, or files owned by currently running workers. Re-read the PERCH2C task row and report every changed file, test outcome, and any unfinished item. Run the lab's focused `Check command:` to completion, Python compilation for changed Python files, and `git diff --check`. Leave changes for the launcher to commit. Never stash, switch commits, or run ottoctl. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

# Resume: PERCH2C (xhard)

Apply the SEND BACK restore in `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-PERCH2C.md.sendback` after the requested rebase. In `tests/test_perch.py`, restore unconditional exact failure-set assertions for `admit_order`, `unadmitted`, and `reserve` as specified there; replace the capture test's `Store.open` and `host_domains` patches with a real temporary Store and normal domain configuration; remove the three newly added deadlines and sleep polling from the named stage-2 waits, using event-driven synchronization and run-level hang detection. Preserve all other existing implementation and assertions.

Work in the PERCH2C lab only. Preserve the actual C task lab as visible evidence. Do not edit `ops/bootstrap/perch.sh`, the ORPHANWORKER census region, production/, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab. Do not run stage 2 or start a staging owner.

Run the lab's original `Check command:` to completion, Python compilation, and `git diff --check`. Report exact results and any unfinished item. Leave changes uncommitted for the launcher. Never stash, switch commits, or run ottoctl. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

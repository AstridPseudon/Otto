# Resume: ACTIVATEWHILE (xhard)

**Outcome:** Apply the current D19-ACTIVATEWHILE SEND BACK restore while preserving the approved scoped cross-project activation and callback behavior.

**Decision:** Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-ACTIVATEWHILE.md.sendback` first. In `tests/test_act_activation.py`, remove the timed waits Astra identified: replace the event waits with unbounded `first_manager.wait()`, `worker_started.wait()`, and `second_manager.wait()`; replace the receipt and queued-execution waits with predicate loops that have no deadline. Current line numbers may have shifted; find the corresponding waits in the current file. Preserve the scoped custody, continuation, installation, exactly-once, and callback assertions. Do not weaken or remove assertions to make the test pass.

**Scope:** Work only in the ACTIVATEWHILE lab. Edit `tests/test_act_activation.py` only unless a directly required fixture change is necessary; explain any extra file. Do not touch production/, any Store, `~/.otto`, `~/.codex`, Codex project configuration, or anything outside this lab.

**Check:** Run `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_bounded_project_host.py` to completion, then `git diff --check`. Report results and every changed assertion. Leave changes uncommitted for the launcher. Never stash, switch commits, run ottoctl, or wait on background work. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

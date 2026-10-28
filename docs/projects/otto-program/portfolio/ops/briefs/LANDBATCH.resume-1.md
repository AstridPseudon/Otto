# LANDBATCH resume 1: apply Astra's D19 restore

Astra's D19 decision in `ops/reviews/D19-LANDBATCH.md.sendback` is SEND BACK. Apply its Restore instruction in `tests/test_bootstrap_gate.py`, in `test_outer_pid_signal_is_forwarded_to_the_leased_gate`: replace `import time; time.sleep(600)` with `import signal; signal.pause()`, and replace the `communicate(timeout=5)` / `TimeoutExpired` / SIGKILL block with `out, err = proc.communicate()`. Keep the readiness wait, outer-PID SIGTERM, and all assertions after the block. Do not add an elapsed-time deadline; run-level hang judgment handles a failure to terminate.

Owned files remain `ops/bootstrap/land.sh` and `tests/test_bootstrap_gate.py`. Do not touch files owned by other tasks. Re-run the task's check command from the brief, report the change and result, and leave it for the launcher to commit. Follow every XHARD rule in the original brief/template, including the regression red/green requirement where applicable. Do not commit or push.

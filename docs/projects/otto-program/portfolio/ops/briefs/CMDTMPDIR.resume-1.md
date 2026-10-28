# Resume CMDTMPDIR: fix round-2 integration regression

Canon advanced from `82b1976` to `3d91a35` in integration round 2. Your lab was rebased onto the prior canon; this wake requests a fresh rebase before resuming.

Use `ops/integ/culprit-CMDTMPDIR.md` as the failure evidence and task instruction. The integration failure is `tests/test_native_resume_trace.py::NativeResumeTraceTests::test_delayed_exact_message_uses_existing_finite_admission_budget`: the admission retry sleeps `[6, 12, 18, ... 60]` instead of `[6, 12]`. Fix the product change that causes the second retry to fail; do not change the test.

Run `tests/test_native_resume_trace.py` and `tests/test_fleet_custody.py` as required by the evidence file, plus `git diff --check`. Preserve the original task scope and all assertions. Report the fix and checks; the launcher commits your work.

Do not touch `ops/bootstrap/perch.sh` or `tests/test_perch.py` while DISTURB is running. Work only in the CMDTMPDIR lab.

**On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A long test runs to its end (use a long timeout); never stop it because a window passed. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.

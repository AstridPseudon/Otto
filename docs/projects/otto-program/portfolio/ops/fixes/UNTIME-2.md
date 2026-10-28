# UNTIME: the D19 answer and two reentrant fixes (manager, 10:31Z)

Your external-owner change stays as it is (`17a2851`). The Opus D19 answer, `ops/reviews/D19-UNTIME.md`, says LAND for the inbox `mkdir` and the numeric guards there. The reentrant-IPC change goes back: widening the guards doesn't fix the two failure kinds in the gate output. Read its F1 and F2 first.

## Fix 1: the pending-file race (`test_close_retains_child_responses_and_defers_second_dispatch_to_restart`, line ~209–213)

The test wakes when the replay response exists, then checks at once that `pending-ffffff.json` is gone. The host writes the response first and removes the pending file afterwards, so under load the test can run between the two.

Wait on the state: after `wait_file(queued)`, poll until `pending-ffffff.json` is absent, with a hang guard of 30 s. Keep the assertions on lines 212 and 213 exactly as they are.

## Fix 2: the partial read (`test_explicit_manager_commands_may_advance_bound_task_after_exact_admission`, and the same pattern elsewhere)

The child script writes its files directly, so `wait_file` (which returns as soon as the file exists) can read one that is still empty (`JSONDecodeError`, `s = ''`). Make the child write atomically: write to a temporary name in the same directory, then `os.replace` it into place. Do this at the child-ready write (line ~45), the child-responses write (line ~52), and anywhere else the child writes a file that a test waits on. The close test's `child_receipt` read (line ~174) depends on the same write.

Product code already does this (`retained_projection.py:132` uses `os.replace`), so match it.

## Keep as they are
- The widened guards from `17a2851` on the reentrant file (F3: the gate saw 64 s runs under load; the widening is right).
- The external-owner file in full.
- No assertion changed. If one has to change to pass, stop and report: that's a new D19.

## Don't touch
- The unlisted test `test_terminal_status_is_bounded_and_preserves_full_response`. It is already red on canon (`KeyError: 'summary'`, per the review). Report it, don't fix it.
- `src/`. The missing-capture time tolerance is a product question, and it goes to the orchestrator.

## The check, after the fix
Run each of the two files on its own, five times, in five separate foreground calls, through `otto-heavy`: `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "UNTIME check" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_reentrant_ipc.py`. Then the external-owner file once. Report each run's pass and fail count, and name any failure's test and line.

## Rules, as before
- Command forms from `ops/fixes/PERCH0FIX-2.md`: `git -C <lab> …` (one per call), the tilde path for `otto-heavy`, no `cd &&`, no `env`, no `/tmp`.
- Commit only the test files, never `.brief.md`.
- Never wait: no Monitor, no sleep loops, no background job you wait on.
- Report: the commit, the runs, and the lines changed.

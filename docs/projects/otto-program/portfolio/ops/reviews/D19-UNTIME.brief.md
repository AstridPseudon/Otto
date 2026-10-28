# Review brief: D19-UNTIME (opus), a worker changed what existing tests assert

Copy to `ops/reviews/D19-UNTIME.brief.md`, fill in the <…> parts, and launch with `ops/launch_review.sh D19-UNTIME opus` (PLAN.md §16). A re-review gets a new ID (`<ID>-r2`) and its brief lists the earlier findings.

---

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). This is a **D19 decision**: a worker changed what existing tests assert. Decide: LAND (the new expectation is right) or SEND BACK (the code should change instead, or the test should keep its old expectation), with the reason, for each change below.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. Your final message is saved as `ops/reviews/D19-UNTIME.md`.

## Hand the legwork to helpers
- The Agent tool with `subagent_type: "haiku-worker"` (Haiku 5.5 high). Split the work into parallel helpers, one per claim to verify. Each helper brief is self-contained: the question, the exact paths, the command, and what to report (file:line, output tails).
- You keep the judgment. A helper's "this is fine" is a lead: look at the evidence it cites before you rely on it.

## The task and the change

The task is `UNTIME` (`projects/program/tasklist.md`, line 50): the tests listed in `ops/flaky.txt` must wait on the state they mean, not on fixed time. Each listed test passes 5 of 5 runs under load. No assertion is removed. The lab files changed are `tests/test_external_owner_context.py` and `tests/test_manager_reentrant_ipc.py`.

The commit is `17a2851` on `lab/UNTIME` (read-only; base `4b3d9d7`). Read its diff:
`git -C ~/Developer/otto-claude-host/labs/UNTIME diff 4b3d9d7 17a2851 -- tests/`

The worker's description of the change:
- **External owner (`test_native_wait_admits_only_exact_owner_reads_without_releasing_custody`).** The test served its inbox without calling `start()`. The owner's pump could scan before the test's first publish created the directory, so the scan raised out of the external-wait loop and the request never got an answer. The test now creates the inbox the way `start()` does, before serving (a `mkdir`). Its response polls went from 3 s to 30 s, and `Event.wait(5)`/`Event.wait(2)`/`Thread.join(5)` went to 30 s.
- **Reentrant IPC (two listed tests).** The waits already wait on files and events. Only the hang guards were lengthened: `wait_file` 8 s to 30 s, child-script deadlines 10 s to 30 s, a child subprocess timeout 12 s to 60 s, `_closing` poll 5 s to 30 s, `closing.join(10)` to 30 s. The worker did not convert these to state waits.
- **Missing capture (the fourth listed test).** Unchanged. It has no timed wait in its own body.

## Questions
1. **External owner:** the `mkdir` of the inbox is a setup change that the test's own assertion doesn't depend on. Is it right (LAND), or does it change what the test is checking (SEND BACK)? Check it against `start()`.
2. **External owner timeouts:** do the numeric changes (3 s, 5 s, 2 s to 30 s) keep each one a hang guard only, with no assertion removed (LAND), or do any of them make a real expectation weaker (SEND BACK)?
3. **Reentrant IPC guards:** the row says to wait on state, and a guard is only allowed "against a hang". The worker only widened guards. Is widening guards enough for these two tests to be deterministic under load (LAND, with a follow-up row), or must they become state waits before landing (SEND BACK)? Name the state each wait should use if SEND BACK.
4. Anything else in the two files that changed an existing assertion. List it, or state that there is none.

## Read
- `PLAN.md` D14 and D19 (the landing gate) and §16; `RUNBOOK.md` §4 and §6.
- `projects/program/tasklist.md`: the `UNTIME` row (line 50).
- The owner's `start()` in `src/otto/` (find it with grep for `def start` near the owner pump) and the test's inbox setup.
- `ops/flaky.txt`: the four listed tests.
- The worker's reported runs: all four listed tests passed every run under concurrent load (3 files, 5 runs). One unlisted test in the reentrant file fails both alone and under load; it is not part of this decision, but say whether it is already red on canon.

## Answer in this shape
1. **Verdict** in one line for each question: LAND or SEND BACK.
2. **Findings**, most severe first, with evidence (file:line, command and output tail).
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Helpers:** how many you ran, one line each.

Don't pad. No finding without evidence.

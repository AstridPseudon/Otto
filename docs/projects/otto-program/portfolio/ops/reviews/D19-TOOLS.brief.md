# Review brief: D19-TOOLS (opus), D19 decision on TOOLS's changed existing tests. Written by the manager 12:35Z.

Copy to `ops/reviews/D19-TOOLS.brief.md` (already here) and launch with `ops/launch_review.sh D19-TOOLS opus` by the orchestrator only.

---

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **D19 decision:** a worker changed what an existing test asserts. Decide: LAND (the new expectation is right) or SEND BACK (the code should change instead), with the reason.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. Your final message is saved as `ops/reviews/D19-TOOLS.md`.

## Hand the legwork to helpers
- The Agent tool with `subagent_type: "haiku-worker"` (Haiku 5.5 high). Split the work into parallel helpers, one per test file or claim. You keep the judgment.

## Read
- `PLAN.md` D14 and D19; `RUNBOOK.md`.
- `projects/program/tasklist.md`: the TOOLS row. Its pinned outcome says "worker tools go from `Read,Write` (claude_cli.py:33) to Read, Write, Edit, Glob and Grep, plus the `otto` server". That makes the old `Read,Write` goldens wrong by the row's own outcome.
- The lab: `~/Developer/otto-claude-host/labs/TOOLS`, branch `lab/TOOLS`, commit `213e2fd` (the test-only commit) and `6e5725b` (the code). Run `git -C ~/Developer/otto-claude-host/labs/TOOLS show 213e2fd` and read the diff.
- The worker's report: `ops/runs/TOOLS/worker.json` (the `result` field).

## The changed tests (commit 213e2fd)
- `tests/test_host_contract.py`: the `worker.fresh` and `worker.resume` goldens now expect `--tools Edit,Glob,Grep,Read,Write` and the matching `--allowedTools`.
- `src/otto/agents/tests/test_claude_binding.py` and `tests/test_usage_capture.py`: their fake streams report the new tool list.

## Question
1. Is each changed expectation the one the TOOLS row pins, with no assertion weakened? Check each hunk.
2. Is the old `Read,Write` expectation a stale product claim, or did it guard something the new tool list now breaks?
3. LAND or SEND BACK for the test-only commit `213e2fd`.

## Answer in this shape
1. **Verdict** in one line: LAND or SEND BACK.
2. **Findings**, most severe first, each with file:line evidence.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** and why.
5. **Helpers:** how many, and what each did.

Don't pad. No finding without evidence.

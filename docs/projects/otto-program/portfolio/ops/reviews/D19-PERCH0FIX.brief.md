# Review brief: D19-PERCH0FIX (opus), a worker changed what existing perch tests assert

Copy to `ops/reviews/D19-PERCH0FIX.brief.md`, fill in the <…> parts, and launch with `ops/launch_review.sh D19-PERCH0FIX opus` (PLAN.md §16). A re-review gets a new ID (`<ID>-r2`) and its brief lists the earlier findings.

---

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). This is a **D19 decision**: a worker changed what an existing test asserts. Decide: LAND (the new expectation is right) or SEND BACK (the code should change instead), with the reason, for each change below.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. The staging Otto under `~/Developer/otto-claude-host/labs/_staging` may be read and queried. Your final message is saved as `ops/reviews/D19-PERCH0FIX.md`.

## Hand the legwork to helpers
- The Agent tool with `subagent_type: "haiku-worker"` (Haiku 5.5 high). Split the work into parallel helpers, one per claim to verify. Each helper brief is self-contained: the question, the exact paths, the command, and what to report (file:line, output tails).
- You keep the judgment. A helper's "this is fine" is a lead: look at the evidence it cites before you rely on it.

## The two changes

**Change 1: `28f1358` (pool rename).** The assertion `pool-units-within-limit` is renamed `harness-pool-within-limit` in `ops/bootstrap/perch_report.py` and in `tests/test_perch.py` (`NAMES`, `SEEDED_FAULTS`, `EXPECTED_RED`). The worker's reason: until stage 2, the pool peak is the harness's own count of its fake workers, not Otto's pool (STAGE0 F4), so the name must not claim Otto's pool. The check itself is unchanged. Question: is a rename of the assertion the right fix for F4, or should the check change (or be split), given the row's acceptance (`harness-pool-within-limit` is named in the row as the stage-2 rename)?

**Change 2: the `staging` seeded fault's expected red set.** `EXPECTED_RED["staging"]` now holds `{staging-ready, timeline-events, store-matches-stage}`. The worker's reason: a staging that never came up has no Store to match, so `store-matches-stage` correctly turns red too. The row's acceptance says "each seeded fault turns one red", and this fault turns three. Question: is this expectation right (LAND), or should the check be changed so this fault turns one red (SEND BACK)? The `lab` fault turns two (`labs-left-behind`, `timeline-events`), as it did before this task; say whether that is acceptable too.

## Read
- `PLAN.md` D14 and D19 (the landing gate) and §16; `RUNBOOK.md` §4 and §6.
- `projects/program/tasklist.md`: the `PERCH0FIX` row (line 54) for the acceptance and the "each seeded fault turns one red" rule.
- The diff of the tests against canon: `git -C ~/Developer/otto-claude-host/labs/PERCH0FIX diff 4b3d9d7 HEAD -- tests/test_perch.py` (and `-- ops/bootstrap/perch_report.py`). Read-only.
- The perch report from the worker's green run: `~/Developer/otto-claude-host/labs/PERCH0FIX/ops/perch/_scratch/out/0/20261016T095103Z/report.md`.
- The worker's own report: `~/Developer/otto-program/ops/runs/PERCH0FIX/worker.1.json` (the `result` field), which includes the seeded-fault table.

## Questions
1. Change 1: LAND or SEND BACK, with the reason.
2. Change 2: LAND or SEND BACK, with the reason. Does it conflict with the row's "each seeded fault turns one red" acceptance?
3. Anything else in `tests/test_perch.py` that changed an existing assertion and is not one of the two above. List it, or state that there is none.

## Answer in this shape
1. **Verdict** in one line for each change: LAND or SEND BACK.
2. **Findings**, most severe first, with evidence (file:line, command and output tail).
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Helpers:** how many you ran, one line each.

Don't pad. No finding without evidence.

# Review brief: <ID> (<opus | astra>), <stage or purpose>

Copy to `ops/reviews/<ID>.brief.md`, fill in the <…> parts, and launch with `ops/launch_review.sh <ID> <opus|astra>` (PLAN.md §16). A re-review gets a new ID (`<ID>-r2`) and its brief lists the earlier findings.

---

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). <ONE of these:>
- **Opus:** you check whether it works, judged on the live data and the code. Be diligent: a claim without evidence is not a finding, and a check you didn't run is not a pass.
- **Astra:** you are a second model family. Opus reviews whether it works; you judge whether it is the right shape: what is missing that nobody thought to test, what is built twice, what should be deleted, and what an agent using it would trip over. Breadth and imagination matter here; every finding still needs evidence.
- **D19 decision:** a worker changed what an existing test asserts. Decide: LAND (the new expectation is right) or SEND BACK (the code should change instead), with the reason.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. The staging Otto under `~/Developer/otto-claude-host/labs/_staging` may be read and queried. Your final message is saved as `ops/reviews/<ID>.md`.

## Hand the legwork to helpers
- **Opus:** the Agent tool with `subagent_type: "haiku-worker"` (Haiku 5.5 high). **Astra:** `spawn_agent` with `model: "gpt-6-luna"`.
- Split the work into as many parallel helpers as it divides into: one per file, scenario, stage report, or claim to verify. Helpers read, search, run read-only commands and tests, query the staging Store, and tally.
- Each helper brief is self-contained, because a helper sees nothing else: the question, the exact paths, the command to run, and what to report (file:line, output tails).
- You keep the judgment. A helper's "this is fine" or "the cause is X" is a lead: look at the evidence it cites before you rely on it.

## Read
- `PLAN.md` §1 (the end state), D14 (layers), D19 (the landing gate) and §16 (the stages); `RUNBOOK.md`.
- `projects/program/tasklist.md`: the rows for <tasks>.
- <the perch report `ops/perch/<stage>/<UTC>/report.md` and the raw data beside it>
- The code landed since <the previous stage's commit>: `git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' <from>..canon/main`, and the diffs.
- <earlier reviews of this stage in `ops/reviews/`, for a re-review>
- **Not** the other model's review of the same stage: the two stay independent.

## Questions
<the questions for this review, from PLAN.md §16>

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL (unsafe to go on). For a D19 decision: LAND or SEND BACK.
2. **Findings**, most severe first. For each:
   - what is wrong;
   - the evidence: file:line, the command and its output tail, or the report path;
   - why it matters;
   - the fix, as a task (an outcome and a check) or a new perch assertion.
3. **Sound:** what you checked and found sound, one line each, so the next review doesn't repeat it.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** anything landed that serves no current requirement, or duplicates another mechanism for the same purpose.
6. **Helpers:** how many you ran and what each did, one line each.

Don't pad. No finding without evidence.

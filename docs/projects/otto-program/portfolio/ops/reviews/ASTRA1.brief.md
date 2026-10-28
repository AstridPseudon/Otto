# Review brief: ASTRA1 (astra), stage 1 "Holds plans": the model's shape

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **Astra:** you are a second model family. Opus reviews whether it works; you judge whether it is the right shape: what is missing that nobody thought to test, what is built twice, what should be deleted, and what an agent using it would trip over. Breadth and imagination matter here; every finding still needs evidence (file:line or command output).

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. The staging Otto under `~/Developer/otto-claude-host/labs/_staging` may be read, but don't start, stop or kill it. Your final message is saved as `ops/reviews/ASTRA1.md`.

## Hand the legwork to helpers
Use `spawn_agent` with `model: "gpt-6-luna"`. Split the work into as many parallel helpers as it divides into (at most 4 at once; the machine is shared): one per question, table or module. Each helper brief is self-contained: the question, the exact paths, the command, and what to report. You keep the judgment, and you check the evidence a helper cites before you rely on it.

## Read
- `PLAN.md` §1 (the end state), §14 (the six follow-up projects), D14 (layers: Herzchen holds the model and the fleet, Otto the product) and §16 (stage 1 and the ASTRA1 row); `AGENT-UX.md`.
- `projects/program/tasklist.md`: rows A1, TYPE, A2, A3, A3FIX, A4, PERCH1, CONV.
- The code at `~/Developer/otto-claude-host/otto` canon/main (`c126587` or later): the work model under `src/herzchen/` (contracts, work, authoring), the save path (`otto save`, A2), `otto show/open/status` (A3), and the typed metadata namespaces (TYPE). `git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' 2cdbb96..canon/main` lists what landed since stage 0.
- The stage 1 perch report `~/Developer/otto-claude-host/otto/ops/perch/1/20261016T113140Z/report.md` and its raw data, including the Store-growth numbers.
- **Not** `ops/reviews/STAGE1.md`: the two reviews stay independent.

## Questions (PLAN.md §16, ASTRA1)
1. Is there exactly one source of truth for a plan, a task and its status? Name every place one fact is stored twice: Store tables, files, generated views, caches, the program folder's own tasklist.
2. Is this the smallest schema that carries the end state in §1? Which field or table has no reader?
3. Will the six follow-up projects (PLAN.md §14), Astrid's work and a superseded project fit without special cases? Sketch one of each as it would be saved.
4. In the perch's Store-growth numbers, what grows that needn't?
5. As a cold agent with only `otto save/show/open/status`: what would you trip over when you first save a plan, edit it, and hit a stale save? Count the commands and files touched.

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL.
2. **Findings**, most severe first. For each: what is wrong; the evidence; why it matters; the fix, as a task (an outcome and a check) or a perch assertion.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** what serves no current requirement or duplicates another mechanism.
6. **Helpers:** how many you ran and what each did.

Don't pad. No finding without evidence.

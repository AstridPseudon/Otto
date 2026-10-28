# Review brief: D19-HOSTKIT (opus), a D19 decision: an existing test's expectation changed

Copy of `ops/review-brief-template.md`, filled in. Launch with `ops/launch_review.sh D19-HOSTKIT opus`.

---

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). This is a **D19 decision**: a worker changed what an existing test asserts. Decide: **LAND** (the new expectation is right) or **SEND BACK** (the code should change instead), with the reason.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`.

## Hand the legwork to helpers
- Use the Agent tool with `subagent_type: "haiku-worker"` (Haiku 5.5 high) for reading, searching, and running read-only commands and tests. Split into as many parallel helpers as the work divides into.
- Each helper brief is self-contained: the question, the exact paths, the command, what to report (file:line, output tails).
- You keep the judgment. A helper's "this is fine" is a lead; check the evidence it cites.

## The change in question
`tests/test_usage_capture.py` in branch `lab/HOSTKIT` (vs `canon/main` at `ed78f58`):
- the import `from otto.agents.codex_cli import normalize_codex_jsonl, CodexCliAdapter` is replaced by `from herzchen.fleet.hosts.codex import normalize_codex_jsonl`;
- **one whole test is deleted**: `AdapterBoundaryTests::test_direct_emitted_usage_survives_adapter_interruption_and_telemetry_oserror_is_optional`. It drives `CodexCliAdapter` (in `otto/agents/codex_cli.py`) with a fake process that emits usage, then (a) interrupts after the provider emission, expecting outcome `unknown` and one observed usage record, and (b) makes the telemetry callback raise `OSError`, expecting the turn to still succeed and the usage to survive.

Show the full diff yourself: `git -C ~/Developer/otto-claude-host/otto diff canon/main...lab/HOSTKIT -- tests/test_usage_capture.py`.

## Why the worker deleted it
HOSTKIT's row says: "Codex has two bindings today ... Keep the one the live service runs, after checking which, and retire the other." The test covered `CodexCliAdapter`, the binding being retired, so the worker removed it with that class. The worker's report says only that `test_usage_capture` passed after the move; it doesn't argue that the behaviour is covered elsewhere.

## Questions
1. Is the behaviour the deleted test pins still required? Namely: usage emitted by the provider survives an interruption after emission (the turn's outcome is `unknown`, and the usage is recorded once); and an optional telemetry callback that fails doesn't fail the turn or lose the usage. Find where the live binding (`src/herzchen/fleet/hosts/codex.py` and whatever runs it, and the `herzchen/adapters/host.py` path) is tested for each. If the surviving binding has a test for both, the deletion is right: say which tests. If not, the deletion removes coverage that the live path still needs: SEND BACK, and name the test to port.
2. Did the `CodexCliAdapter` class get deleted in HOSTKIT, or only its use in this test? If the class is still used by the live service, the test shouldn't have been deleted at all.
3. Are there other tests in the changed files that were edited, deleted or weakened in HOSTKIT (`git diff --stat canon/main...lab/HOSTKIT -- tests/`)? List each, with whether it's a rename, a fixture change, or a deleted assertion.

## Read
- `PLAN.md` §1, D14, D19, §16; `RUNBOOK.md` §4 (the gate).
- `projects/program/tasklist.md`: the HOSTKIT row (its "Before landing" and "retire the other" text).
- The HOSTKIT lab diff: `git -C ~/Developer/otto-claude-host/labs/HOSTKIT log --oneline canon/main..lab/HOSTKIT` and the diffs of `src/herzchen/fleet/hosts/` and `src/otto/agents/`.
- The worker's report: `ops/runs/HOSTKIT/worker.2.json` (its `result` field).

## Answer in this shape
1. **Verdict** in one line: LAND or SEND BACK.
2. **Findings**, most severe first: what is wrong, the evidence (file:line and the command with its output tail), why it matters, and the fix as an outcome plus a check.
3. **Sound:** what you checked and found sound, one line each.
4. **Not checked:** what you couldn't check, and why.
5. **Delete list:** anything landed that serves no current requirement.

# SAVEFIX: the orchestrator's answer (16 Oct 2026), resume

1. **Yes:** you own `src/otto/portfolio/herzchen_binding.py` and `src/otto/portfolio/intake.py` as well, for the save wiring, the refusals and `show`'s criteria. Your earlier work is committed in your lab (5caf1d0, by me: the launcher's commit failed).
2. **Your tests can run now.** Codex's sandbox refused Unix sockets without network access; your session now has it (TOOLING12). Run your tests red on `canon/main` first, then green.
3. **`tests/test_revisions.py:137`** asserts `batch_history` on the project payload. Your row says `batch_history` and `last_batch` leave the project record, so change that assertion to the row's outcome: the per-save events carry the mapping. List it as file:line in your report. **D19 is decided: LAND** (`ops/reviews/D19-SAVEFIX.md`). Change no other existing assertion.
4. Everything else stands. Every sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

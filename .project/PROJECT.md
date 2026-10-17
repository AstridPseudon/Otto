# THROUGHPUT: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T19:41:46Z | TP1 | merged 60600a3 | +126/-0 | `tests/test_throughput_report.py` (2 passed); baseline parser run on 103 historical logs | Added repeatable timing breakdown; runner execution and wait records unavailable. Full landing/staging gate needs the gate.
2026-10-17T19:42:15Z | TP2 | blocked | — | No task check run | Historical evidence shows repeated D19 sweeps only; these must stay uncached, and no sealed runner records establish a separate eligible repeat.
2026-10-17T19:42:15Z | TP4 | blocked | — | No task check run | Astrid renderer is outside this clone and the write boundary; no callable renderer or cold path exists here.

## Questions for the orchestrator

- TP4 needs an Astrid checkout to implement and benchmark the warm renderer. Should a future THROUGHPUT run include that repository, or remain blocked under the Otto-clone-only boundary?

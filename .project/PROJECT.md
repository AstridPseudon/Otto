# THROUGHPUT: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T19:41:46Z | TP1 | merged 60600a3 | +126/-0 | `tests/test_throughput_report.py` (2 passed); baseline parser run on 103 historical logs | Added repeatable timing breakdown; runner execution and wait records unavailable. Full landing/staging gate needs the gate.
2026-10-17T19:42:15Z | TP2 | blocked | — | No task check run | Historical evidence shows repeated D19 sweeps only; these must stay uncached, and no sealed runner records establish a separate eligible repeat.
2026-10-17T19:42:15Z | TP4 | blocked | — | No task check run | Astrid renderer is outside this clone and the write boundary; no callable renderer or cold path exists here.
2026-10-17T19:45:13Z | TP3 | merged afff5cf | +100/-0 | `tests/test_landing.py` (16 passed); worker reported `tests/test_fleet_custody.py` 15 passed/14 sandbox failures and `tests/test_tools.py` 22 passed/7 environment failures | Feedback check now selects importing, ops-name-matching, and directly changed tests. No physical lines removed; full behavior is narrower. Fleet custody/tools and landing/staging gate need the gate.
2026-10-17T19:47:09Z | TP6 | merged 7085a26 | +114/-8 | `tests/test_worker_refusal_next_action.py` (3 passed) | Cold-agent trace took ~4 min; worker refusals now give case-specific recovery. No redundant steps found. `ask` is absent from this facade despite PLAN's four-verb description; question recorded.
2026-10-17T19:48:43Z | TP5 | merged eb82164 | +62/-0 | `tests/test_throughput_after.py` (1 passed) | Recorded baseline, actual task shortstats, blocked/unavailable measurements, and zero justified physical source deletions. Landing/staging gate needs the gate.

## Questions for the orchestrator

- TP4 needs an Astrid checkout to implement and benchmark the warm renderer. Should a future THROUGHPUT run include that repository, or remain blocked under the Otto-clone-only boundary?
- The worker-facade package exposes `task`, `check`, and `done` plus a listing operation, while PLAN §1 describes `task`, `check`, `ask`, and `done`. Where should the `ask` worker verb be supplied? TP6 preserved the existing facade scope.

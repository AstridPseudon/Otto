# THROUGHPUT: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17T19:41:46Z | TP1 | merged 60600a3 | +126/-0 | `tests/test_throughput_report.py` (2 passed); baseline parser run on 103 historical logs | Added repeatable timing breakdown; runner execution and wait records unavailable. Full landing/staging gate needs the gate.
2026-10-17T19:42:15Z | TP2 | blocked | — | No task check run | Historical evidence shows repeated D19 sweeps only; these must stay uncached, and no sealed runner records establish a separate eligible repeat.
2026-10-17T19:42:15Z | TP4 | blocked | — | No task check run | Astrid renderer is outside this clone and the write boundary; no callable renderer or cold path exists here.
2026-10-17T19:45:13Z | TP3 | merged afff5cf | +100/-0 | `tests/test_landing.py` (16 passed); worker reported `tests/test_fleet_custody.py` 15 passed/14 sandbox failures and `tests/test_tools.py` 22 passed/7 environment failures | Feedback check now selects importing, ops-name-matching, and directly changed tests. No physical lines removed; full behavior is narrower. Fleet custody/tools and landing/staging gate need the gate.
2026-10-17T19:47:09Z | TP6 | merged 7085a26 | +114/-8 | `tests/test_worker_refusal_next_action.py` (3 passed) | Fresh-agent code/schema trace took ~4 min; journey steps were inferred, not executed, so runtime UX remains unmeasured. Refusals now give case-specific recovery. `ask` is absent from this facade despite PLAN's four-verb description; question recorded.
2026-10-17T19:48:43Z | TP5 | merged eb82164 | +62/-0 | `tests/test_throughput_after.py` (1 passed) | Recorded baseline, actual task shortstats, blocked/unavailable measurements, and zero justified physical source deletions. Landing/staging gate needs the gate.
2026-10-17T19:54:26Z | TP3 review fix | merged 7b0e012 | +105/-9 | `tests/test_landing.py` (18 passed) | Astra found committed/broad argv selection, option-value, and deleted/renamed target defects; fixed them. Feedback remains separate from acceptance custody; no physical deletion.
2026-10-17T19:55:36Z | TP3 option fix | merged b109ce0 | +6/-1 | `tests/test_landing.py` (18 passed) | Astra found unsupported options followed by bare `tests` could lose their values; `--pyargs tests` and `--cov tests` now remain unchanged. Final Astra review pending.
2026-10-17T19:56:36Z | TP3 pyargs fix | merged 919407f | +4/-0 | `tests/test_landing.py` (18 passed) | Astra found `--pyargs -q tests` also changes collection mode; selector now preserves all argv containing `--pyargs`. Final Astra review pending.
2026-10-17T19:56:51Z | Final review | — | — | No further tests | Astra found no remaining concrete defects. It confirmed feedback selection leaves `done`'s admitted check and sealed-result custody intact; deletion budget delivered zero physical source deletions and is disclosed; blocked and unmeasured work is accurately reported.

## Questions for the orchestrator

- TP4 needs an Astrid checkout to implement and benchmark the warm renderer. Should a future THROUGHPUT run include that repository, or remain blocked under the Otto-clone-only boundary?
- The worker-facade package exposes `task`, `check`, and `done` plus a listing operation, while PLAN §1 describes `task`, `check`, `ask`, and `done`. Where should the `ask` worker verb be supplied? TP6 preserved the existing facade scope.

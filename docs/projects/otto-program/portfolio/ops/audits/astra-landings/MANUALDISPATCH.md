DEFECTS — MANUALDISPATCH duplicates dispatch records for ask continuations; still present on `canon/main` at `eb9b6cd`.

1. **P2 — One answered worker launch records two dispatches.**
   - The owner calls `continue_from_answer(..., execute=True)` at `src/otto/portfolio/manager_journey_service.py:1977`.
   - `src/otto/portfolio/execution.py:2046` records `<answer-request-key>:dispatch`, then calls `start()`.
   - The continuation’s target has no `launch_request` (`execution.py:642–660`), so the shared dispatch at `:1346` uses the fallback `execution-start:<schedule_id>` from `:1263`.
   - These distinct keys create distinct records and `work.assignment.dispatched` events (`src/herzchen/domains/work/assignments.py:857–868`). A successful answer continuation therefore violates “exactly one per launch.”
   - **Fix — normal:** Delete the explicit answer-path dispatch at `execution.py:2043–2047`; let the shared worker-start boundary record it once.
   - **Failing test:** Extend `tests/test_ask_integration.py:56` through a successful answer continuation: assert one additional provider call and exactly one additional dispatch event, then replay and assert neither increases. Today the event delta is two.

The shared start hook covers the other named routes. Both successor modules are deleted, and searches on current `canon/main` find no references to either module in `src`, `tests`, or `ops`.

The added event-count assertions would fail without the change by static inspection. They check real Store events with literal expectations and add no product-method patches or timer waits. Coverage remains incomplete: direct assign/start, correction, and retained-child are checked, but reroute/retry dispatch counts are not; the existing ask test checks occurrence uniqueness instead of dispatch uniqueness (`tests/test_ask_integration.py:59–61`).

No separate over-engineering finding beyond the redundant answer-path call. Tests were not run; the landing log reports passing checks.
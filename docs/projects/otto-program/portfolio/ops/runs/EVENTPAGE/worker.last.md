Implemented scoped, cursor-paged event and stream selectors in [store.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/EVENTPAGE/src/herzchen/kernel/store.py). Migrated backlinks, attention, responsibility deltas, and task discovery in [packets.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/EVENTPAGE/src/herzchen/content/packets.py) and [timeline.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/EVENTPAGE/src/herzchen/domains/work/timeline.py). The four broad `list_events()` reads are gone; the exact-stream timeline gap reader remains.

The hydration regression in [test_eventpage.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/EVENTPAGE/tests/test_eventpage.py) failed on unchanged canon because `page_events` was missing. It now passes, including the assertion that only **7 relevant bodies** are hydrated among 30,000 decoys.

- Requested check: **47 passed, 5 subtests passed**.
- Boundary and focused callers: **41 passed, 2 subtests passed**.
- `git diff --check`: passed. No sandbox-only failures.

All implementation was delegated to Luna agents: `store_selector` built the selectors and incorporated review corrections for cursor scope, pagination, and indexed pin lookups; `packet_readers` migrated the readers and changed the page drain to a generator; `task_discovery` migrated stream discovery without correction; `regression` wrote the tests and corrected its fixtures. Only the four owned files changed. No commit or push was made; the launcher can commit the lab.
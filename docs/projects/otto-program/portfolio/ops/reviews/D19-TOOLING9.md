# D19-TOOLING9: orchestrator decision (no Opus call)

1. **Verdict: LAND.**
2. **What changed:** `tests/test_bootstrap_gate.py`, where `test_nothing_to_wait_on_returns_at_once` becomes `test_with_nothing_running_it_waits_on_the_inbox`. The old test asserted that `workers.py wait` returns at once when no worker or landing runs. The new one asserts that it then waits on the inbox and wakes on a new `## Orchestrator` section.
3. **Why the expectation itself changes:** the old behavior left the manager with no supported way to wait for the orchestrator when it had nothing running. On 16 Oct it wrote its own sleep-loop watcher in /tmp, against its brief ("wait only with workers.py wait"). The new behavior closes that gap. The other wake reasons (worker exit, landing result, new section) keep their tests unchanged.
4. **Why the orchestrator decides it:** it's the orchestrator's own bootstrap tooling, changed at its direction (requests.md 04:45Z). An Opus call would buy nothing. Logged in `ops/STATUS.log`.

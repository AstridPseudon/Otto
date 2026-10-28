# D19 review brief: DRAINSETTLE (opus)

You are reviewing a landing gate decision for Otto. Decide LAND or SEND BACK on the changed expectations in `tests/test_bounded_project_host.py`.

Read-only review. Do not edit files, commit, run Otto commands, or inspect the live Store. Save the decision as `ops/reviews/D19-DRAINSETTLE.md`.

## Context

Task DRAINSETTLE pins the outcome: “Draining answers every queued request, so graceful stop never hangs.” When the owner drains, every queued execution that never started must receive exactly one held answer (`provider_called: false`, `effects_started: false`, retry after restart), retain its prepared Due for recovery, and release admission. A real-owner socket regression demonstrated the hang on canon and passed with the fix.

The landing gate reports changed existing expectations in `tests/test_bounded_project_host.py`. The worker says it updated old assertions that expected no queued reply. Its focused check passed 10 tests and `git diff --check` was clean. The new socket regression timed out on canon after 45 seconds, as expected, and passed in the lab.

The landing candidate is `e9c31f1b9908a24182dd63810497eed4cc2a6861`; base is `c67be79f69908dec37fa4a9dc5ad6ca6396a8fb8`. The worker changed `src/otto/portfolio/execution_host.py`, `tests/test_admitted_transport_drain.py`, and `tests/test_bounded_project_host.py`.

## Questions

1. Do the changed assertions in `tests/test_bounded_project_host.py` correctly reflect the DRAINSETTLE outcome, without weakening unrelated coverage?
2. Does the product change answer queued requests during graceful drain while preserving recovery and exactly-once semantics?
3. Verdict: LAND or SEND BACK.

Give concise findings with file:line evidence, what you checked, and anything not checked.

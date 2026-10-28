# Resume: ACTIVATEWHILE (xhard)

**Outcome:** Apply the D19-ACTIVATEWHILE SEND BACK restore, preserving the approved cross-project activation behavior and its regression.

**Decision:** Read `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-ACTIVATEWHILE.md.sendback`. In `tests/test_act_activation.py`, extend `test_busy_queues_once` with B-scoped custody: assert no terminal response while deferred; preserve the unchanged request and pending-receipt assertions; clear B's custody; poll the same request with a handler returning `{"outcome": "prepared"}`; assert exactly one invocation and a response for that token with outcome `prepared`; poll again and assert the invocation count remains one. Keep the new cross-project execution and callback regression.

**Scope:** Work only in the ACTIVATEWHILE lab. Edit `tests/test_act_activation.py` only unless a directly required fixture update is necessary; explain any additional file. Do not touch `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/manager_journey_client.py`, `src/otto/hostctl/execution.py`, or `tests/test_runner.py` (owned by active tasks). Do not touch production/, any Store, ~/.otto, ~/.codex, or anything outside this lab.

**Check:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_act_activation.py tests/test_bounded_project_host.py`. Run to completion and report results plus `git diff --check`. Do not alter unrelated assertions. Do not commit or push; the launcher commits on exit. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

# D19 request: REWORKWIRE

The landing gate refused REWORKWIRE because existing expectations changed in `tests/test_host_contract.py`. Decide LAND or SEND BACK for the one changed existing test contract below.

The worker replaced a mocked `run_turn` assertion with a real `ClaudeHost` continuation using a fake native process stream. It now checks that the continuation succeeds, uses the exact parked session and working directory, receives the prior landing log, and authorizes the same attempt. The authorization-bound test likewise runs a native process once, then verifies a repeated continuation is refused before a second launch. The task acceptance requires the owner to resume the same session in the kept lab with the landing log after a settled refusal, using fresh authorization; the existing mock only asserted the planned launch and did not exercise the real host contract.

Review the row `REWORKWIRE` in `projects/program/tasklist.md`, the diff of `tests/test_host_contract.py` in lab `REWORKWIRE` against `canon/main`, and the relevant `run_continuation` implementation and tests. Apply D19: decide whether the changed existing expectation correctly tests the accepted behavior or should be restored. Read-only; do not alter files. Save the verdict and evidence to `ops/reviews/D19-REWORKWIRE.md`.

Answer LAND or SEND BACK, with concise evidence (file:line and relevant test result or code path), why the change is correct or wrong, and the specific restoration if sending it back.

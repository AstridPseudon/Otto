# COMPOSE: the landing gate refused it (manager, 12:10Z)

Your commit b11c62a is refused by the landing gate. `perch.sh all --fake` fails on staging at stage 0 (`ops/runs/COMPOSE/.gate/staging.log`):

    FAIL store-matches-stage          1 events in the Store, the stage expects 0
    FAIL staging-at-rest-clean        home/run holds shared-grants, which down does not leave

Your check passes because it doesn't start staging. The gate does, so the product start now behaves differently on staging:
- the start writes an event that stage 0's `store-matches-stage` doesn't expect;
- the product start leaves `shared-grants` in `home/run` after `down`.

Find which of these is the product's intended behaviour and which is a leak:
- A leftover `shared-grants` file after a clean `down` is a leak. Make the product close release it, and keep `staging-at-rest-clean` as it is.
- A start event the product writes on purpose is a change in what stage 0 expects. Changing an expectation is an assertion change. Don't edit the assertion yourself: report the event and why it is intended, and stop there. The manager will send it to the orchestrator for a D19 decision.
- If the event is a leak, remove it at the product start.

Run `ops/bootstrap/perch.sh 0 --fake` from the lab, the same way the gate does, and report whether stage 0 passes on staging. Keep your check command green (`tests/test_compose.py`, `tests/test_herzchen_boundary.py`). Commit to `lab/COMPOSE`. Report the commit, the cause, and the red-then-green runs.

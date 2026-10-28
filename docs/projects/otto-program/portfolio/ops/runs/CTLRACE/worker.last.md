Implemented atomic request publication in [manager_ctl.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CTLRACE/install/controller/manager_ctl.py): it writes and syncs a same-directory temporary file, then replaces it with the existing `request-<token>.json` name.

Added a concurrent client, responder, and observer regression in [test_host_neutral_defaults.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CTLRACE/tests/test_host_neutral_defaults.py). It passed 200 paused-write iterations.

**Check:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_host_neutral_defaults.py` — **16 passed, 200 subtests passed**.

**Other writers inspected:** `src/otto/hostctl/lanes.py` already publishes requests via a temporary file and hard link. `src/herzchen/command_ports.py` uses socket transport, with no file-lane request writer. No other files were changed.

**Commit:** Pending the `run-task.sh` exit hook; I left the changes in the lab as instructed.
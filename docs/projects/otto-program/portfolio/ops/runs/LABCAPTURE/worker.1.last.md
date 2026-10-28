The LABCAPTURE resume changes are complete and uncommitted.

The landed-lab sweep now runs once at owner start, after the owner file is written and custody is held. It obtains the fleet through `_pair()`. Lab removal follows a verified owner capture even when acceptance is rejected; failed removal remains eligible for the next owner-start sweep. The named fake cleanup hooks remain deleted.

Changed paths: [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABCAPTURE/src/otto/hostctl/product_service.py), [owner_runtime.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABCAPTURE/src/otto/agents/owner_runtime.py), [test_fleet_custody.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABCAPTURE/tests/test_fleet_custody.py), and [test_external_owner_execution.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABCAPTURE/tests/test_external_owner_execution.py).

**Tests:** six focused lifecycle regressions passed. The exact three-file check finished with **45 passed, 16 subtests passed, 8 failed**. All eight failures are custody tests that require sandbox capabilities unavailable here: `sandbox-exec` returned “Operation not permitted,” and process census could not run `ps`. `git diff --check` passed. No staging-owner tests were run.

Luna agents `owner_start` and `capture_rejection` implemented the delegated changes. My review prompted tighter retained-capture identity checks and a rejected-capture retry fixture; I also removed an unnecessary assertion diagnostic.
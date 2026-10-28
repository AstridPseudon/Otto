Implemented cleanup regressions and the gate directory census.

- Hardened directory cleanup in [command_ports.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/src/herzchen/command_ports.py:453): after verifying directory ownership, close can remove an already-missing socket and its empty directory. A replaced socket still prevents cleanup.
- Added close, process-exit, error-exit, and unbound-facade checks in [test_tools.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/tests/test_tools.py:286).
- Added a before/after command-directory census to the landing gate in [land.sh](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/ops/bootstrap/land.sh:241), with a regression in [test_bootstrap_gate.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/tests/test_bootstrap_gate.py:209).

The required `tests/test_tools.py` run had **31 passed, 2 failed**, with **0 matching folders before and after**. The failures were `test_owner_failure_is_generic` (unexpected exception detail) and the macOS sandbox test (sandbox operation not permitted). The gate orphan regression passed, as did all 3 `test_command_ports_lifecycle.py` tests and `bash -n ops/bootstrap/land.sh`.

Changes are uncommitted for the launcher.
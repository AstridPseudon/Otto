The D14 placement correction is complete and **uncommitted**.

- [file_ipc_receipts.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/RECEIPTFENCE/src/herzchen/fleet/file_ipc_receipts.py) now owns request digesting, claim validation, settled receipt retry, and terminal cleanup.
- [execution_host.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/RECEIPTFENCE/src/otto/portfolio/execution_host.py) now wires that fleet behavior to Otto’s command dispatch, timing, atomic writer, and legacy marker reason.

The receipt path and prework behavior are preserved. No tests or decision-dependent assertions changed; the previously reported D19 and bounded-host expectation conflicts remain unresolved.

The focused receipt check passed (5 tests, 2 subtests), `tests/test_herzchen_boundary.py` passed (5 tests), and `git diff --check` passed.
# EFFECTS: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17 19:41Z | REFRESH | committed 3ae06be | +19/-9 | none | refreshed tasklist; measured deletion candidates and caller paths; PERCH2C/OWNERCOMPLETION refs noted
2026-10-17 19:47Z | EF1 | merged 5f3da51 | +186/-6 | `tests/test_operation_receipt_lineage.py` needs the gate: all 8 tests stop in setup on sandbox AF_UNIX `socket.bind` PermissionError; bodies did not run. `py_compile` and `git diff --check` pass | Added `src/herzchen/kernel/operations.py`, `src/herzchen/kernel/store.py`, `tests/test_operation_receipt_lineage.py`; durable start claim, reconstructed UNKNOWN hold; Astra found retained prepare/outcome digest incompatibility, worker fixed it by preserving legacy payload shape; reviewer direct checks confirm retained replay and one grant under concurrent same/different keys; no deletions.
2026-10-17 19:53Z | EF2 | merged 3e1f9b2 | +166/-13 | `tests/test_operation_receipt_lineage.py` needs the gate: all 9 tests stop in setup on sandbox AF_UNIX `socket.bind` PermissionError; bodies did not run. `py_compile` and `git diff --check` pass | Added `src/herzchen/kernel/operations.py`, `src/herzchen/kernel/store.py`, `tests/test_operation_receipt_lineage.py`; one retained-proof reconciliation path. Astra found forged-record custody overwrite and Python bool/int evidence equality; fixed via authoritative retained-request/state checks and canonical JSON comparison, while keeping exact same-key replay. Narrow `effect.proof` mutation port accepted; no deletions.

## Questions for the orchestrator

- The package deletion budget names “the successor remains” but no concrete module or symbol is identifiable in this clone. Please name the intended target when convenient; this does not block EF1–EF5.

## Questions for the orchestrator

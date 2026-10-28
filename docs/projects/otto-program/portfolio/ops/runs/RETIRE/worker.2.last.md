Resolved all conflict markers in `batches.py` and `test_otto_save.py`.

In `batches.py`, I kept SAVEFIX’s `creating` parameter and `criteria` support, and combined them with RETIRE’s guard against revising retired projects. The existing atomic first-save, event mapping, and `id` alias changes remain intact.

In `test_otto_save.py`, I retained all SAVEFIX regressions and the RETIRE regression that verifies saving a dependency on a retired task names its successor and does not redirect it.

Checks passed:

- Task check: **54 passed, 16 subtests passed**
- `tests/test_revisions.py`: **12 passed**
- No conflict markers remain in either file.
# D19 decision (the orchestrator, 2026-10-17, after three Astra reviews): tests/test_perch.py

Decision: LAND

- `tests/test_perch.py`: Astra's third review (ops/reviews/D19-PERCH2C.md.sendback, 23:09Z) found the changed expectations follow the row: independent A/B dependencies and capacity expectations (~496), Store-derived dispatch counts (~856), exact seeded-failure sets for each doctored fault (~983), the C-dispatch kill check (~1438), deletion of the two tests of the removed harness cleanup, and untimed `sleep 0.25` polling on the owner's own evidence, with hangs judged at the run level (the orchestrator's 22:47Z ruling). Its one remaining item, the new `timeout=10` on the wait test's subprocess (~1349), the orchestrator removed in the lab and re-ran the test (1 passed, 3 subtests). The other `timeout=` arguments in this file already exist on canon and are PATCHLINT's.

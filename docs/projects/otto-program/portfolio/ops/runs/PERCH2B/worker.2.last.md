Stopped at the review prerequisite. `service admit` requires a pinned review resource, but the product exposes no maintained command or owner-lane operation to create one. `WorkGraph.create_effort` is available internally and used by admission tests; the current PERCH script passes each task as its own review, which does not establish a valid review path. I did not build or run the stage-2 scenario.

- **Lab:** `lab/PERCH2B`, HEAD `b0900f1` (`PERCH2B: the worker's changes (worker.jsonl)`); worktree clean.
- **Focused check:** `tests.test_perch.AssertionKindTests` passed, 13 tests.
- **Seeded-fault evidence:** the existing stage-2 assertion test passes with clean fixture observations and turns only the matching assertion red for each seeded fault. This is fixture-level evidence, not a staging dispatch run.
- **Stage-2 report:** none. I did not rerun `perch.sh`; its earlier attempt stopped at the sandbox’s staging-root permission error. The landing gate must run the requested check.
- **Incomplete:** a product-supported way to create the pinned review is needed before staging can exercise admission and dispatch. No additional files were changed.
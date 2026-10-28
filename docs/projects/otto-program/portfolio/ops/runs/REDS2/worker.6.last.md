The four NEW gate failures now pass. I restored manager-scoped evidence verification so accepted evidence retains its read grant, and restored `review-task` to native-caller routing. The scale overrides and 05:32Z production-bound decision are unchanged.

Checks:

- `test_completion_project_refresh.py` and `test_shared_manager_client_routing.py`: **15 passed, 9 subtests passed**.
- Adjacent manager correction, journey, and continuation files: **76 passed, 12 subtests passed; 1 failed**.
- `git diff --check`: passed.

The remaining failure is a direct conflict: the new routing test requires `requires_native_caller("review-task")` to be true, while `test_manager_correction_planning.py::test_planning_requires_authenticated_ingress_and_client_selects_it` asserts it is false. I left both assertions untouched. Resolving that expectation requires the specified D19 decision; no test assertions were changed.

The lab has two uncommitted production changes, in `owner_bootstrap.py` and `manager_journey_client.py`, for the launcher to review and commit.
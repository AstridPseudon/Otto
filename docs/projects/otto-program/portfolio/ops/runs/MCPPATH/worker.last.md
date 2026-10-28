Implemented the worker MCP launcher isolation in the lab. `grant_for_due` now prefixes the server args with `-I`, and the regression exercises the real grant and `task` calls from labs containing package and stdlib shadows. I added `ref=assignment_ref` to the fixture because the current `grant_for_due` implementation requires it.

- **Canon red:** The new regression failed against untouched canon with `LAB_SHADOW`.
- **Lab green:** The focused regression passed: `1 passed`.
- **Full lab file:** `28 passed, 2 failed`. The failures are the existing owner-error detail assertion and a macOS sandbox permission denial.
- **Files changed:** [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MCPPATH/src/otto/hostctl/product_service.py:813) and [test_tools.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MCPPATH/tests/test_tools.py:615).

No other blockers.
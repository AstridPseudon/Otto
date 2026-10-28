Moved the reusable isolation policy into Herzchen’s tool-launch layer. Otto now calls that helper while keeping its interpreter, socket, token variable, server name, and tool list in Otto.

- **Canon red:** The regression failed with `LAB_SHADOW`.
- **Lab focused check:** `1 passed`.
- **Required full check:** `28 passed, 2 failed`. One is a sandbox-only macOS `sandbox_apply: Operation not permitted` failure; the other is the existing owner-error detail assertion.
- **Changed files:** [launch.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MCPPATH/src/herzchen/fleet/tools/launch.py) and [product_service.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MCPPATH/src/otto/hostctl/product_service.py). The real `grant_for_due` regression remains in `tests/test_tools.py` unchanged.

I inspected the RECEIPTFENCE brief and current diff. Its modified receipt files were not touched.
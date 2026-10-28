Updated [facade.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/src/herzchen/fleet/tools/facade.py:254) so only `LandingError` can expose an owner error message. Generic exceptions return only their class name, even if they carry `code` and `message` attributes. Added a regression for that case in [test_tools.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CMDTMPDIR/tests/test_tools.py:189). The existing temp-folder lifecycle changes remain intact.

- Focused generic-error and landing-refusal checks: **3 passed**.
- Original Check command: **33 passed, 1 failed**. The remaining sandbox test fails because this environment rejects `sandbox-exec` with “Operation not permitted.”
- Private `TMPDIR` census: **0 matching folders before, 0 after**.
- `git diff --check`: passed.

Changes are uncommitted for the launcher.
Implemented the missing operator guard across project creation. Orchestration no longer falls back to the owner actor, and create-and-open resolves the operator before reserving authoring state. New-project save and import also refuse before writing; existing-project save and attach remain available without an operator.

Added [test_missing_operator_creation.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPPRE/tests/test_missing_operator_creation.py:90), covering pending, template, orchestrated pending, create-and-open, new-project save, import, and direct orchestration-port retry. No existing assertions were changed.

**Check:** `20 passed, 1 skipped, 6 subtests passed`. `git diff --check` passed. Changes are uncommitted; no additional files were edited.
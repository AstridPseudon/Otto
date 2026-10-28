Implemented in the lab. The prework matched the brief; no departure.

- [assessment.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ASSESSCAP/src/otto/portfolio/assessment.py:133) now selects assessment events for the current parent before applying the existing 10,000 event refusal.
- [store.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ASSESSCAP/src/herzchen/kernel/store.py:2733) now selects amended scope declarations and correction creation and resolution events while retaining the parent, stream, event type, subject kind, and authority checks.
- [test_local_assessment_composition.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ASSESSCAP/tests/test_local_assessment_composition.py:156) adds the coverage and required-scope regression, selector assertions, and a check that the current correction remains in coverage. No existing assertions were changed.

The regression failed before the implementation change and passed afterward. The requested test file passed: **7 passed, 10 subtests passed**. `git diff --check` passed. I tested only in the lab; the launcher’s canonical checkout was not run.
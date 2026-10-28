Implemented in [save.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CONV/src/otto/portfolio/save.py:56): nonempty `documents` are accepted, checked to be an array, and carried into the parsed seed. The regression also saves a task’s `instructions` and confirms `show` returns them.

**Test runs**

- Baseline on the lab’s `canon/main` starting code: **1 failed, 20 passed**. The regression failed because `otto save` rejected nonempty `documents`.
- After the change: **21 passed, 9 subtests passed** with the specified pytest command.

I removed the obsolete rejection case from the existing refusal test at [test_otto_save.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CONV/tests/test_otto_save.py:279). That is the changed expectation; it now conflicts with the requested behavior.

The lab has uncommitted changes on `lab/CONV`, as required on Codex.
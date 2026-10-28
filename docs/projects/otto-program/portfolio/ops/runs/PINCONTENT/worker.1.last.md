Fixed the landing regression in [assignments.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PINCONTENT/src/herzchen/domains/work/assignments.py:926). Policy admission now loads the exact retained task revision before checking its original stamp; the shared content-aware pin check remains in place.

The named test and focused worker, admission, mandate, and dispatch checks pass: **57 passed, 6 subtests passed**. `git diff --check` is clean. A combined run still encounters the previously identified fresh-manager recovery error-string mismatch, unrelated to this fix.

Only `assignments.py` changed. PERCH2B’s files were untouched, and I made no commit so the launcher can commit on exit.
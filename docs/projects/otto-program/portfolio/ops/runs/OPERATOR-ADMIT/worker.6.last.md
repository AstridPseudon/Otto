The cold-client save preflight now accepts an omitted `--actor` and forwards the option only when supplied. The owner-bound CLI then supplies the write actor. This change required [hostctl/portfolio.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OPERATOR-ADMIT/src/otto/hostctl/portfolio.py), which you released from A6 ownership.

All requested files passed **separately**: owner lane 9, admit 12, operator admission 13 with 1 skipped, and stage 1 19 with 20 subtests. The brief’s combined check passed (34 passed, 1 skipped); owner preflight tests also passed (6). `git diff --check` passed.

Only `hostctl/portfolio.py` has an uncommitted change. No STAGESETUP-owned file was touched, and no commit was made.
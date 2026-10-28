Fixed the regression. New task aliases now retain the submitted `id`, so later partial sheet updates resolve the existing task and preserve its fields.

The landing test failed before the fix and passes now. The required check passes: **28 passed, 10 subtests passed**. `git diff --check` is clean.

Edited [batches.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SAVEFIX/src/herzchen/domains/work/batches.py) and added a focused regression in [test_otto_save.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/SAVEFIX/tests/test_otto_save.py). No other paths needed editing. Nothing was committed; the launcher owns the commit.
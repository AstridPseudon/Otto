Implemented the requested changes in the four owned files. Test cleanups register before each `up`, read the pidfile, stop the process group with `os.killpg`, wait for it, and remove the temporary root. The landing gate scans visible temporary roots and reports an orphan’s PID and home. The scratch tests stub `ps` because the worker sandbox blocks it.

**Checks**

- The orphan-detection test and the passing-landing test: **2 passed**.
- `bash -n`, Python syntax parsing, and `git diff --check`: passed.
- The full gate test command was attempted, but the sandbox denied `ps`; I did not rerun the full suite after adding the scratch `ps` stub.
- I did not run `test_staging_startup.py` or `test_perch_staging.py`; the brief reserves those owner-starting tests for the landing gate.

No existing assertions were removed or changed. No commit was created; the launcher should commit these changes.
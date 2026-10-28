# Brief: TOOLING13 (normal, 0.25 focused days), done by the orchestrator

**Title:** The gate's test runs end when pytest has reported, naming leaked threads

**Outcome:** A test that leaves a non-daemon thread running kept the interpreter alive after pytest's summary. On 16 Oct, SAVEFIX's landing waited 53 minutes on a run that had finished in 91 s (`test_supervisor_direction_client.py`'s failing test with a 5 s deadline), and RETIRE's worker saw the same stall. `ops/bootstrap/otto_gate_exit.py`, a pytest plugin loaded through `PYTEST_ADDOPTS` for the gate's sweep runs and the task's check, prints the leaked threads' names and then exits with pytest's own status. It is not a time limit: the run is over once pytest has reported. The Cpipe test's stub also exits when its scratch folder is gone; it had left five looping orphans.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

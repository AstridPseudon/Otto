"""pytest plugin for the landing gate: name the threads a run leaked, then exit with pytest's status.

A test that leaves a non-daemon thread running keeps the interpreter alive after pytest's summary.
On 16 Oct a failing test in tests/test_supervisor_direction_client.py did that, and SAVEFIX's landing
waited 53 minutes on a run that had finished in 91 s. This is not a time limit: the run is over when
pytest has reported, and the leak is printed so it can be fixed where it starts.
"""
import os
import sys
import threading


def pytest_sessionfinish(session, exitstatus):
    session.config._otto_gate_status = int(exitstatus)


def pytest_unconfigure(config):
    status = getattr(config, "_otto_gate_status", None)
    if status is None:
        return  # pytest stopped before the session finished: leave its own exit path alone
    leaked = [t for t in threading.enumerate()
              if t is not threading.main_thread() and t.is_alive() and not t.daemon]
    if leaked:
        print("otto-gate: %d non-daemon thread(s) still running after the session: %s"
              % (len(leaked), ", ".join(sorted(t.name for t in leaked))), file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)

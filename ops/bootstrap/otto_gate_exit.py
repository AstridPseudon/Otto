"""pytest plugin for the landing gate: name the threads a run leaked, then exit with pytest's status.

A test that leaves a non-daemon thread running keeps the interpreter alive after pytest's summary.
On 16 Oct a failing test in tests/test_supervisor_direction_client.py did that, and SAVEFIX's landing
waited 53 minutes on a run that had finished in 91 s. This is not a time limit: the run is over when
pytest has reported, and the leak is printed so it can be fixed where it starts.
"""
import os
import sys
import threading


def _file_outcomes(report):
    nodeid = getattr(report, "nodeid", "")
    path = nodeid.split("::", 1)[0]
    if not path:
        return None
    return os.path.normpath(path)


def _skip_reason(report):
    reason = getattr(report, "longrepr", "")
    if isinstance(reason, tuple) and len(reason) >= 3:
        reason = reason[2]
    elif hasattr(reason, "reprcrash") and reason.reprcrash:
        reason = reason.reprcrash.message
    reason = " ".join(str(reason).split())
    return reason[:240] or "skip reason unavailable"


def _record(report, config):
    path = _file_outcomes(report)
    if path is None:
        return
    files = getattr(config, "_otto_gate_files", None)
    if files is None:
        return
    record = files.setdefault(path, {"executed": False, "skips": []})
    if report.outcome == "skipped" and not hasattr(report, "wasxfail"):
        reason = _skip_reason(report)
        if reason not in record["skips"]:
            record["skips"].append(reason)
    elif (report.outcome == "failed" or
          (report.outcome == "passed" and getattr(report, "when", None) == "call") or
          hasattr(report, "wasxfail")):
        record["executed"] = True


def pytest_collectreport(report):
    _record(report, _CONFIG)


def pytest_runtest_logreport(report):
    _record(report, _CONFIG)


_CONFIG = None


def pytest_sessionstart(session):
    global _CONFIG
    _CONFIG = session.config
    session.config._otto_gate_files = {}


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    files = getattr(config, "_otto_gate_files", {})
    for path, record in sorted(files.items()):
        if record["skips"] and not record["executed"]:
            reason = "; ".join(record["skips"])
            path = " ".join(path.split())[:160]
            reason = " ".join(reason.split())[:200]
            terminalreporter.write_line("otto-gate: all skipped in %s: %s" % (path, reason))


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

"""ottoctl heavy: one heavy job at a time, and nothing it started outlives it (real processes)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def heavy(tmp_path: Path, *args: str, wait: bool = True, **kw) -> subprocess.Popen:
    env = dict(os.environ, OTTO_HEAVY_DIR=str(tmp_path / "state"), PYTHONPATH=str(SRC))
    env.pop("OTTO_HEAVY_LEASE", None)
    env.update(kw.pop("env", {}))
    return subprocess.Popen([sys.executable, "-m", "otto.hostctl.heavy", *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def py(code: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(code)]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); treat it as gone once its state says so.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_gone(pid: int, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def detached_sleeper(pidfile: Path, *, stop_self: bool = False, linger: float = 0.0) -> str:
    """A job whose grandchild leaves the process group (setsid) and lingers: today's leaked hosts and browsers."""
    grandchild = pidfile.with_suffix(".py")
    grandchild.write_text(
        "import os, signal, time\n"
        "os.setsid()\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        + ("os.kill(os.getpid(), signal.SIGSTOP)\n" if stop_self else "")
        + "time.sleep(120)\n")
    return (
        "import os, subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(grandchild)!r}])\n"
        "deadline = time.time() + 10\n"
        f"while not os.path.exists({str(pidfile)!r}) and time.time() < deadline:\n"
        "    time.sleep(0.05)\n"
        "time.sleep(0.3)\n"
        + (f"time.sleep({linger})\n" if linger else ""))


def test_runs_the_command_returns_its_exit_code_and_logs_machine_state(tmp_path):
    proc = heavy(tmp_path, "--purpose", "unit", "--", *py("import sys; sys.exit(3)"))
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 3, err
    status = heavy(tmp_path, "status")
    assert json.loads(status.communicate(timeout=30)[0])["lease"] == "free"
    record = json.loads((tmp_path / "state" / "heavy.log").read_text().splitlines()[-1])
    assert record["purpose"] == "unit" and record["exit_code"] == 3 and record["outcome"] == "exited"
    assert {"load_1m", "free_disk_gb"} <= set(record["machine_before"]) and "machine_after" in record


def test_a_second_lease_waits_for_the_first_and_says_who_holds_it(tmp_path):
    marks = tmp_path / "marks"
    first = heavy(tmp_path, "--purpose", "render A", "--",
                  *py(f"import time; open({str(marks)!r},'a').write('A+%f\\n' % time.time()); time.sleep(2); "
                      f"open({str(marks)!r},'a').write('A-%f\\n' % time.time())"))
    time.sleep(0.7)
    second = heavy(tmp_path, "--purpose", "journey B", "--",
                   *py(f"import time; open({str(marks)!r},'a').write('B+%f\\n' % time.time())"))
    _, err2 = second.communicate(timeout=30)
    first.communicate(timeout=30)
    times = dict(line.split("+") if "+" in line else (line.split("-")[0] + "-", line.split("-")[1])
                 for line in marks.read_text().splitlines())
    assert float(times["B"]) >= float(times["A-"]), "the second lease started before the first ended"
    assert "waiting for the lease held by" in err2 and "render A" in err2


def test_no_wait_returns_busy_and_names_the_holder(tmp_path):
    first = heavy(tmp_path, "--purpose", "render A", "--", *py("import time; time.sleep(3)"))
    time.sleep(0.7)
    busy = heavy(tmp_path, "--no-wait", "--", *py("pass"))
    _, err = busy.communicate(timeout=30)
    first.communicate(timeout=30)
    assert busy.returncode == 75 and "render A" in err


def test_a_detached_grandchild_is_stopped_when_the_job_ends(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    proc = heavy(tmp_path, "--", *py(detached_sleeper(pidfile)))
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    grandchild = int(pidfile.read_text())
    assert wait_gone(grandchild), "a process that left the group outlived its lease"
    assert "leftover" in err


def test_a_self_paused_grandchild_is_stopped_too(tmp_path):
    # Today's custody leak: children suspended at spawn and never resumed or killed.
    pidfile = tmp_path / "paused.pid"
    proc = heavy(tmp_path, "--", *py(detached_sleeper(pidfile, stop_self=True)))
    proc.communicate(timeout=60)
    assert wait_gone(int(pidfile.read_text()))


def test_time_running_out_stops_everything_and_exits_124(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = detached_sleeper(pidfile, linger=60)
    proc = heavy(tmp_path, "--max-minutes", "0.05", "--", *py(code))
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 124 and "time ran out" in err
    assert wait_gone(int(pidfile.read_text()))


def test_leftovers_of_a_holder_that_died_are_stopped_by_the_next_lease(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = detached_sleeper(pidfile, linger=60)
    holder = heavy(tmp_path, "--purpose", "crashed job", "--", *py(code))
    deadline = time.monotonic() + 15
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    job = json.loads((tmp_path / "state" / "heavy.json").read_text())
    holder.send_signal(signal.SIGKILL)  # the holder dies; its job and grandchild keep running
    holder.wait(timeout=30)  # (not communicate: the surviving job still holds the pipes open)
    holder.stdout.close(); holder.stderr.close()
    grandchild = int(pidfile.read_text())
    assert alive(grandchild) and alive(job["pid"])
    nxt = heavy(tmp_path, "--", *py("pass"))
    _, err = nxt.communicate(timeout=60)
    assert nxt.returncode == 0 and "crashed job" in err
    assert wait_gone(grandchild) and wait_gone(job["pid"])


def test_a_process_without_the_lease_is_never_signalled(tmp_path):
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        pidfile = tmp_path / "grandchild.pid"
        proc = heavy(tmp_path, "--", *py(detached_sleeper(pidfile)))
        proc.communicate(timeout=60)
        assert wait_gone(int(pidfile.read_text()))
        assert alive(bystander.pid)
    finally:
        bystander.kill()
        bystander.wait()


def test_a_heavy_call_inside_a_heavy_job_runs_straight_through(tmp_path):
    inner = [sys.executable, "-m", "otto.hostctl.heavy", "--no-wait", "--", sys.executable, "-c", "print('inner ran')"]
    proc = heavy(tmp_path, "--", *inner)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0 and "inner ran" in out, err

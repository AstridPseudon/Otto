"""ottoctl heavy: many agents share the machine's capacity, and nothing a job started outlives it (real processes)."""
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


def heavy(tmp_path: Path, *args: str, capacity: int = 1, **kw) -> subprocess.Popen:
    env = dict(os.environ, OTTO_HEAVY_DIR=str(tmp_path / "state"), PYTHONPATH=str(SRC),
               OTTO_HEAVY_CAPACITY=str(capacity))
    env.pop("OTTO_HEAVY_LEASE", None)
    env.update(kw.pop("env", {}))
    return subprocess.Popen([sys.executable, "-m", "otto.hostctl.heavy", *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def holding(tmp_path: Path, used: int, capacity: int = 1) -> None:
    """Wait until the pool's holders take USED slots (arrival order without fixed sleeps; only a hang fails)."""
    while json.loads(heavy(tmp_path, "status", capacity=capacity).communicate()[0])["used"] != used:
        time.sleep(0.05)


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
    status = json.loads(heavy(tmp_path, "status").communicate(timeout=30)[0])
    assert status["used"] == 0 and status["holders"] == [] and status["capacity"] == 1
    record = json.loads((tmp_path / "state" / "heavy.log").read_text().splitlines()[-1])
    assert record["purpose"] == "unit" and record["exit_code"] == 3 and record["outcome"] == "exited"
    assert {"load_1m", "free_disk_gb"} <= set(record["machine_before"]) and "machine_after" in record


def test_when_capacity_is_full_the_next_job_waits_and_says_who_holds_it(tmp_path):
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
    assert "waiting for 1 slot(s)" in err2 and "render A" in err2


def test_no_wait_returns_busy_and_names_what_is_running(tmp_path):
    first = heavy(tmp_path, "--purpose", "render A", "--", *py("import time; time.sleep(3)"))
    holding(tmp_path, 1)
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
    job = json.loads(next((tmp_path / "state" / "holders").glob("*.json")).read_text())
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


def _span(marks: Path, name: str) -> tuple[float, float]:
    lines = dict(line.split("=") for line in marks.read_text().splitlines())
    return float(lines[name + "+"]), float(lines[name + "-"])


def _job(marks: Path, name: str, seconds: float) -> list[str]:
    return py(f"import time; open({str(marks)!r},'a').write('{name}+=%f\\n' % time.time()); time.sleep({seconds}); "
              f"open({str(marks)!r},'a').write('{name}-=%f\\n' % time.time())")


def test_jobs_run_at_the_same_time_while_capacity_remains(tmp_path):
    marks = tmp_path / "marks"
    a = heavy(tmp_path, "--purpose", "frames A", "--", *_job(marks, "A", 2), capacity=3)
    b = heavy(tmp_path, "--purpose", "frames B", "--", *_job(marks, "B", 2), capacity=3)
    c = heavy(tmp_path, "--purpose", "frames C", "--", *_job(marks, "C", 2), capacity=3)
    for proc in (a, b, c):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    spans = [_span(marks, n) for n in "ABC"]
    assert max(s for s, _ in spans) < min(e for _, e in spans), "the three jobs did not overlap"


def test_a_heavier_job_waits_for_enough_slots_and_is_not_starved(tmp_path):
    marks = tmp_path / "marks"
    first = heavy(tmp_path, "--weight", "1", "--", *_job(marks, "small1", 2), capacity=2)
    time.sleep(0.6)
    big = heavy(tmp_path, "--weight", "2", "--purpose", "full render", "--", *_job(marks, "big", 0.5), capacity=2)
    time.sleep(0.6)
    later = heavy(tmp_path, "--weight", "1", "--", *_job(marks, "small2", 0.2), capacity=2)
    for proc in (first, big, later):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    s1, e1 = _span(marks, "small1"); sb, eb = _span(marks, "big"); s2, _ = _span(marks, "small2")
    assert sb >= e1, "the 2-slot job started while a slot was taken"
    assert s2 >= sb, "a later small job jumped the queue ahead of the waiting big job"


def test_a_small_job_uses_a_slot_the_waiting_head_cannot_and_never_delays_it(tmp_path):
    # 4 slots: a 3-slot render runs; a 3-slot job waits at the head with 1 slot free. A 1-slot check
    # behind it takes that slot at once; a second one doesn't (the head must still fit beside it).
    marks = tmp_path / "marks"
    render = heavy(tmp_path, "--weight", "3", "--", *_job(marks, "render", 4), capacity=4)
    holding(tmp_path, 3, capacity=4)
    head = heavy(tmp_path, "--weight", "3", "--purpose", "transcript", "--", *_job(marks, "head", 0.5), capacity=4)
    assert "waiting for 3 slot(s)" in head.stderr.readline()  # it heads the queue
    check = heavy(tmp_path, "--weight", "1", "--purpose", "gate", "--", *_job(marks, "check", 12), capacity=4)
    holding(tmp_path, 4, capacity=4)
    second = heavy(tmp_path, "--weight", "1", "--", *_job(marks, "second", 0.2), capacity=4)
    for proc in (render, head, check, second):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    _, end_render = _span(marks, "render"); s_head, _ = _span(marks, "head")
    s_check, e_check = _span(marks, "check"); s_second, _ = _span(marks, "second")
    assert s_check < end_render, "the 1-slot check waited although the head couldn't use the free slot"
    assert s_head >= end_render, "the 3-slot head started while the render held its slots"
    assert s_head < e_check, "the head waited for the backfilled check: backfill delayed it"
    assert s_second >= s_head, "a second small job backfilled into room the head needs"


def test_status_shows_capacity_and_what_is_running(tmp_path):
    job = heavy(tmp_path, "--weight", "2", "--purpose", "journey X", "--", *py("import time; time.sleep(2)"), capacity=4)
    time.sleep(0.8)
    status = json.loads(heavy(tmp_path, "status", capacity=4).communicate(timeout=30)[0])
    job.communicate(timeout=30)
    assert status["capacity"] == 4 and status["used"] == 2 and status["free"] == 2
    assert status["holders"][0]["purpose"] == "journey X"

"""ottoctl heavy: many agents share the machine's capacity, and nothing a job started outlives it (real processes)."""
from __future__ import annotations

import fcntl
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


def ticketed(tmp_path: Path, n: int) -> None:
    """Wait until N waiters hold tickets (state, not time)."""
    while len(list((tmp_path / "state" / "waiting").glob("*.json"))) != n:
        time.sleep(0.05)


def _mark_then_wait(marks: Path, name: str, go: Path) -> list[str]:
    """A job that records its start, then stays (holding its slots) until the test creates GO."""
    return py(f"import os, time; open({str(marks)!r},'a').write('{name}\\n')\n"
              f"while not os.path.exists({str(go)!r}): time.sleep(0.05)")


def started(marks: Path) -> list[str]:
    return marks.read_text().split() if marks.exists() else []


def await_started(marks: Path, n: int) -> list[str]:
    while len(started(marks)) < n:
        time.sleep(0.05)
    return started(marks)


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
    marks, go = tmp_path / "marks", tmp_path / "go"
    first = heavy(tmp_path, "--purpose", "render A", "--", *_mark_then_wait(marks, "A", go))
    holding(tmp_path, 1)
    second = heavy(tmp_path, "--purpose", "journey B", "--", *py(f"open({str(marks)!r},'a').write('B\\n')"))
    ticketed(tmp_path, 1)
    assert await_started(marks, 1) == ["A"], "the second lease started while the first held the only slot"
    go.write_text("")
    _, err2 = second.communicate(timeout=60)
    first.communicate(timeout=60)
    assert started(marks) == ["A", "B"]
    assert "waiting for 1 slot(s)" in err2 and "render A" in err2


def test_no_wait_returns_busy_and_names_what_is_running(tmp_path):
    go = tmp_path / "go"
    first = heavy(tmp_path, "--purpose", "render A", "--", *_mark_then_wait(tmp_path / "marks", "A", go))
    holding(tmp_path, 1)
    busy = heavy(tmp_path, "--no-wait", "--", *py("pass"))
    _, err = busy.communicate(timeout=60)
    go.write_text("")
    first.communicate(timeout=60)
    assert busy.returncode == 75 and "render A" in err


def test_a_detached_grandchild_is_stopped_when_the_job_ends(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    proc = heavy(tmp_path, "--", *py(detached_sleeper(pidfile)))
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    grandchild = int(pidfile.read_text())
    assert wait_gone(grandchild), "a process that left the group outlived its lease"
    assert "leftover" in err


def test_same_group_child_is_stopped_after_root_exits_before_first_census(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module
    from otto.portfolio.native_caller_ingress import process_identity

    monkeypatch.setenv("OTTO_HEAVY_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OTTO_HEAVY_CAPACITY", "1")
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    monkeypatch.delenv("OTTO_HEAVY_LEASE", raising=False)
    pidfile, orphaned = tmp_path / "same-group.pid", tmp_path / "root-exited"
    command = py(f"""
import os, time
from pathlib import Path
pid = os.fork()
if pid == 0:
    root = os.getppid()
    Path({str(pidfile)!r}).write_text(str(os.getpid()))
    while os.getppid() == root:
        time.sleep(0.01)
    Path({str(orphaned)!r}).touch()
    time.sleep(60)
    os._exit(0)
while not Path({str(pidfile)!r}).exists():
    time.sleep(0.01)
os._exit(0)
""")
    original = module._processes
    first = True
    child_birth = None

    def after_root_exit():
        nonlocal first, child_birth
        if first:
            first = False
            deadline = time.monotonic() + 10
            while not orphaned.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert orphaned.exists(), "the test command did not exit before census"
            record = json.loads(next((tmp_path / "state" / "holders").glob("*.json")).read_text())
            anchor = record.get("group_anchor")
            assert anchor and record["processes"][str(anchor)]["birth"], "no durable group anchor"
            child_birth = list(process_identity(int(pidfile.read_text())).birth)
        return original()

    monkeypatch.setattr(module, "_processes", after_root_exit)
    try:
        assert module.run(command, weight=1, purpose="same-group", max_minutes=1,
                          wait=True, owner="test") == 0
        assert wait_gone(int(pidfile.read_text())), "same-group child outlived its lease"
        assert not list((tmp_path / "state" / "holders").glob("*.json"))
    finally:
        if pidfile.exists() and child_birth is not None:
            try:
                pid = int(pidfile.read_text())
                if list(process_identity(pid).birth) == child_birth:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                pass


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
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_a_tagged_bystander_is_not_a_lease_cleanup_target():
    from otto.hostctl import heavy as module

    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 start_new_session=True,
                                 env=dict(os.environ, OTTO_HEAVY_LEASE="unrelated-lease"))
    try:
        # A copied environment is a discovery hint, not custody.
        module.stop_lease({"lease_id": "unrelated-lease", "pgid": None, "processes": {}})
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_reused_pid_with_same_display_start_is_not_signalled(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 43210, "pgid": 43210,
              "processes": {"43210": {"birth": [100, 1], "pgid": 43210}}}
    monkeypatch.setattr(module, "_processes", lambda: {
        43210: {"ppid": 1, "pgid": 43210, "birth": [100, 2], "display_start": "same second"}})
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("reused PID was signalled"))
    monkeypatch.setattr(module.os, "killpg", lambda *_args: pytest.fail("reused group was signalled"))
    assert module.stop_lease(record)["reaped"] == []


def test_persisted_anchor_adopts_same_group_child_after_root_exit(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 100, "pgid": 100, "group_anchor": 101,
              "processes": {"100": {"birth": [1], "pgid": 100},
                            "101": {"birth": [2], "pgid": 100}}}
    present = {101: {"ppid": 1, "pgid": 100, "birth": [2]},
               102: {"ppid": 1, "pgid": 100, "birth": [3]}}
    signals = []
    monkeypatch.setattr(module, "_processes", lambda: dict(present))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: bool(present))
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("individual PID signal"))

    def kill_group(pgid, sig):
        assert pgid == 100
        signals.append(sig)
        if sig == signal.SIGTERM:
            present.pop(102)
        elif sig == signal.SIGKILL:
            present.clear()

    monkeypatch.setattr(module.os, "killpg", kill_group)
    result = module.stop_lease(record)
    assert 102 in result["reaped"] and result["remaining"] == []
    assert record["processes"]["102"] == {"birth": [3], "pgid": 100}
    assert signal.SIGTERM in signals and signal.SIGKILL in signals


def test_recycled_group_with_dead_anchor_is_not_signalled(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 100, "pgid": 100, "group_anchor": 101,
              "processes": {"100": {"birth": [1], "pgid": 100},
                            "101": {"birth": [2], "pgid": 100}}}
    monkeypatch.setattr(module, "_processes", lambda: {
        101: {"ppid": 1, "pgid": 100, "birth": [4]},
        102: {"ppid": 101, "pgid": 100, "birth": [5]}})
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: True)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("reused PID was signalled"))
    monkeypatch.setattr(module.os, "killpg", lambda *_args: pytest.fail("reused group was signalled"))
    result = module.stop_lease(record)
    assert result["reaped"] == [] and result["remaining"] == ["group:100"]
    assert "102" not in record["processes"]


def test_anchor_reuse_between_census_and_signal_blocks_group_kill(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 100, "pgid": 100, "group_anchor": 101,
              "processes": {"101": {"birth": [2], "pgid": 100}}}
    valid = {101: {"ppid": 1, "pgid": 100, "birth": [2]}}
    reused = {101: {"ppid": 1, "pgid": 100, "birth": [4]}}
    scans = iter((valid, valid))
    monkeypatch.setattr(module, "_processes", lambda: next(scans, reused))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("reused PID was signalled"))
    monkeypatch.setattr(module.os, "killpg", lambda *_args: pytest.fail("reused group was signalled"))
    assert module.stop_lease(record)["remaining"] == []


def test_dead_holder_restart_stops_unseen_same_group_child(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    (directory / "holders").mkdir(parents=True)
    path = directory / "holders" / "lease.json"
    path.write_text(json.dumps({"lease_id": "lease", "holder_pid": 99999999,
                                "weight": 1, "pid": 100, "pgid": 100, "group_anchor": 101,
                                "processes": {"100": {"birth": [1], "pgid": 100},
                                              "101": {"birth": [2], "pgid": 100}}}))
    present = {101: {"ppid": 1, "pgid": 100, "birth": [2]},
               102: {"ppid": 1, "pgid": 100, "birth": [3]}}
    monkeypatch.setattr(module, "_processes", lambda: dict(present))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: bool(present))

    def kill(pid, sig):
        if pid == 99999999 and sig == 0:
            raise ProcessLookupError
        pytest.fail("unfenced PID signal")

    def kill_group(pgid, sig):
        assert pgid == 100
        if sig == signal.SIGTERM:
            present.pop(102)
        elif sig == signal.SIGKILL:
            present.clear()

    monkeypatch.setattr(module.os, "kill", kill)
    monkeypatch.setattr(module.os, "killpg", kill_group)
    recovered = module._reap_dead_holders(directory)
    assert recovered[0]["remaining"] == []
    assert 102 in recovered[0]["reaped"]
    assert not path.exists(), "settled recovery retained the capacity claim"


def test_missing_exact_birth_for_known_pid_keeps_lease_unresolved(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 43210, "pgid": 43210,
              "processes": {"43210": {"birth": [100, 1], "pgid": 43210}}}
    monkeypatch.setattr(module, "_processes", lambda: {
        43210: {"ppid": 1, "pgid": 43210, "birth": None}})
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("unverified PID was signalled"))
    monkeypatch.setattr(module.os, "killpg", lambda *_args: pytest.fail("unverified group was signalled"))
    assert module.stop_lease(record)["remaining"] == ["identity-unavailable:43210"]


def test_missing_exact_birth_gap_survives_empty_scans_and_restart(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    (directory / "holders").mkdir(parents=True)
    path = directory / "holders" / "birth-gap.json"
    path.write_text(json.dumps({"lease_id": "birth-gap", "holder_pid": 99999999,
                                "weight": 1, "pid": 43210, "pgid": 43210,
                                "processes": {"43210": {"birth": [1], "pgid": 43210}}}))
    scans = iter(({43210: {"ppid": 1, "pgid": 43210, "birth": None}}, {}, {}))
    monkeypatch.setattr(module, "_processes", lambda: next(scans))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    monkeypatch.setattr(module, "_alive", lambda _pid: False)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("unverified PID was signalled"))
    monkeypatch.setattr(module.os, "killpg", lambda *_args: pytest.fail("unverified group was signalled"))

    first = module._reap_dead_holders(directory)[0]
    assert first["sweep"] == "unavailable" and "identity-unavailable:43210" in first["remaining"]
    assert path.exists() and json.loads(path.read_text())["birth_gaps"] == [43210]

    restart = subprocess.run(py(f"""
import json
from pathlib import Path
from otto.hostctl import heavy
heavy._processes = lambda: {{}}
heavy._group_alive = lambda _pgid: False
print(json.dumps(heavy._reap_dead_holders(Path({str(directory)!r}))[0]))
"""), env=dict(os.environ, PYTHONPATH=str(SRC)), capture_output=True, text=True, timeout=30)
    assert restart.returncode == 0, restart.stderr
    second = json.loads(restart.stdout)
    assert second["sweep"] == "unavailable" and "identity-unavailable:43210" in second["remaining"]
    assert path.exists() and json.loads(path.read_text())["birth_gaps"] == [43210]


def test_census_gap_is_sticky_through_empty_cleanup_and_dead_holder_recovery(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    (directory / "holders").mkdir(parents=True)
    path = directory / "holders" / "gap.json"
    path.write_text(json.dumps({"lease_id": "gap", "holder_pid": 99999999, "weight": 1,
                                "pid": 43210, "pgid": 43210,
                                "processes": {"43210": {"birth": [1], "pgid": 43210}}}))
    scans = iter((None, {}, {}))
    monkeypatch.setattr(module, "_processes", lambda: next(scans))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    first = module._reap_dead_holders(directory)[0]
    assert first["sweep"] == "unavailable" and "census-gap" in first["remaining"]
    assert path.exists() and json.loads(path.read_text())["census_gap"] is True

    # A restarted process sees a complete empty census, but cannot erase the
    # earlier period in which a detached descendant may have escaped.
    restart = subprocess.run(py(f"""
import json
from pathlib import Path
from otto.hostctl import heavy
heavy._processes = lambda: {{}}
heavy._group_alive = lambda _pgid: False
print(json.dumps(heavy._reap_dead_holders(Path({str(directory)!r}))[0]))
"""), env=dict(os.environ, PYTHONPATH=str(SRC)), capture_output=True, text=True, timeout=30)
    assert restart.returncode == 0, restart.stderr
    second = json.loads(restart.stdout)
    assert "census-gap" in second["remaining"]
    assert path.exists() and json.loads(path.read_text())["census_gap"] is True


def test_normal_run_persists_a_census_gap_even_if_later_scans_succeed(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    monkeypatch.setenv("OTTO_HEAVY_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OTTO_HEAVY_CAPACITY", "1")
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    monkeypatch.delenv("OTTO_HEAVY_LEASE", raising=False)
    scans = iter((None,))
    monkeypatch.setattr(module, "_processes", lambda: next(scans, {}))
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    assert module.run(py("import time; time.sleep(0.3)"), weight=1, purpose="gap",
                      max_minutes=1, wait=True, owner="test") == 0
    record = json.loads(next((tmp_path / "state" / "holders").glob("*.json")).read_text())
    assert record["census_gap"] is True


def test_unidentified_descendant_is_retried_and_removed_after_complete_scan():
    from otto.hostctl import heavy as module

    record = {"pid": 100, "pgid": 100,
              "processes": {"100": {"birth": [1], "pgid": 100}}}
    first = {100: {"ppid": 1, "pgid": 100, "birth": [1]},
             101: {"ppid": 100, "pgid": 101, "birth": None}}
    assert module._observe(record, first)
    assert record["unidentified"] == [101]
    readable = {100: first[100], 101: {"ppid": 100, "pgid": 101, "birth": [2]}}
    assert module._observe(record, readable)
    assert record["processes"]["101"]["birth"] == [2]
    assert record.get("unidentified", []) == []

    record["unidentified"] = [102]
    assert module._observe(record, {100: first[100]})
    assert record.get("unidentified", []) == []


def test_unidentified_root_can_settle_after_complete_empty_scan(monkeypatch):
    from otto.hostctl import heavy as module

    record = {"pid": 43210, "pgid": 43210, "processes": {}}
    monkeypatch.setattr(module, "_processes", lambda: {})
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    assert module.stop_lease(record)["remaining"] == []


def test_reused_pid_is_recorded_when_it_is_a_verified_new_descendant():
    from otto.hostctl import heavy as module

    record = {"pid": 100, "pgid": 100,
              "processes": {"100": {"birth": [1], "pgid": 100},
                            "101": {"birth": [2], "pgid": 100}}}
    snapshot = {100: {"ppid": 1, "pgid": 100, "birth": [1]},
                101: {"ppid": 100, "pgid": 101, "birth": [3]}}
    assert module._observe(record, snapshot)
    assert record["processes"]["101"] == {"birth": [3], "pgid": 101}


def test_unreadable_linux_stat_for_tracked_pid_is_unresolved(monkeypatch):
    from otto.hostctl import heavy as module

    original_is_dir = Path.is_dir
    monkeypatch.setattr(module.Path, "is_dir", lambda path: str(path) == "/proc" or original_is_dir(path))
    monkeypatch.setattr(module.os, "listdir", lambda _path: ["43210"])
    original_read = Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path) == "/proc/43210/stat":
            raise PermissionError("stat temporarily unreadable")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(module.Path, "read_text", read_text)
    assert module._processes()[43210]["birth"] is None
    record = {"pid": 43210, "pgid": 43210,
              "processes": {"43210": {"birth": [1], "pgid": 43210}}}
    monkeypatch.setattr(module, "_group_alive", lambda _pgid: False)
    assert "identity-unavailable:43210" in module.stop_lease(record)["remaining"]


def test_unresolved_dead_holder_keeps_capacity_claim_until_settled(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    (directory / "holders").mkdir(parents=True)
    (directory / "waiting").mkdir()
    (directory / "slots").mkdir()
    holder_file = directory / "holders" / "unresolved.json"
    holder_file.write_text(json.dumps({"lease_id": "unresolved", "holder_pid": 99999999,
                                       "weight": 1, "purpose": "first", "pgid": None}))
    monkeypatch.setattr(module, "stop_lease", lambda *_args, **_kwargs: {"remaining": [12345]})
    assert module._reap_dead_holders(directory)[0]["remaining"] == [12345]
    assert holder_file.exists(), "unresolved custody was silently discarded"

    ticket = directory / "waiting" / "next.json"
    with ticket.open("w+") as mine:
        fcntl.flock(mine, fcntl.LOCK_EX)
        mine.write(json.dumps({"weight": 1, "purpose": "next", "queued_at": time.time()}))
        mine.flush()
        assert module._take(directory, 1, 1, ticket.name, False, lambda _backfill: None)[0] is None
        slots, _, _ = module._take(directory, 2, 1, ticket.name, False, lambda _backfill: None)
        assert slots is not None, "free capacity beside unresolved custody could not be used"
        for handle in slots:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()


def test_holder_crash_at_spawn_cannot_launch_command_without_durable_root(tmp_path):
    from otto.portfolio.native_caller_ingress import process_identity

    marker = tmp_path / "command-ran"
    spawned = tmp_path / "spawned.json"
    command = py(f"open({str(marker)!r}, 'w').write('ran')")
    code = f"""
import json, os, signal, sys
from pathlib import Path
from otto.hostctl import heavy
from otto.portfolio.native_caller_ingress import process_identity
command = {command!r}
real_popen = heavy.subprocess.Popen
def crash_after_spawn(args, *a, **kw):
    child = real_popen(args, *a, **kw)
    if args == command or (len(args) > 3 and args[1:3] == ['-m', 'otto.hostctl.heavy']
                           and args[3] == '--_lease_child'):
        identity = process_identity(child.pid)
        Path({str(spawned)!r}).write_text(json.dumps(
            {{'pid': child.pid, 'birth': list(identity.birth)}}))
        os.kill(os.getpid(), signal.SIGKILL)
    return child
heavy.subprocess.Popen = crash_after_spawn
raise SystemExit(heavy.run(command, weight=1, purpose='crash at spawn',
                           max_minutes=1, wait=True, owner='test'))
"""
    env = dict(os.environ, OTTO_HEAVY_DIR=str(tmp_path / "state"), PYTHONPATH=str(SRC),
               OTTO_HEAVY_CAPACITY="1")
    env.pop("OTTO_HEAVY_LEASE", None)
    holder = subprocess.Popen(py(code), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    holder.wait(timeout=30)
    holder.stdout.close(); holder.stderr.close()
    assert holder.returncode == -signal.SIGKILL
    launched = json.loads(spawned.read_text())
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            current = process_identity(launched["pid"])
        except ProcessLookupError:
            break
        except (PermissionError, OSError):
            try:
                os.kill(launched["pid"], 0)
            except ProcessLookupError:
                break
        else:
            if list(current.birth) != launched["birth"]:
                break  # A reused PID proves the recorded incarnation has exited.
        time.sleep(0.02)
    else:
        pytest.fail("the exact spawned helper did not reach a terminal state")
    assert not marker.exists(), "the requested command ran before exact custody was durable"
    path = next((tmp_path / "state" / "holders").glob("*.json"))
    record = json.loads(path.read_text())
    if record.get("launch_state") == "pending":
        from otto.hostctl import heavy as module
        recovered = module._reap_dead_holders(tmp_path / "state")
        assert recovered[0]["remaining"] == ["launch-pending"]
        assert path.exists(), "recovery settled an unresolved launch intent"
    else:
        assert record["pid"] and record["pgid"] == record["pid"]
        assert record["processes"][str(record["pid"])]["birth"]


def test_requested_command_sees_its_durable_root_identity(tmp_path):
    code = """
import json, os
from pathlib import Path
path = Path(os.environ['OTTO_HEAVY_DIR']) / 'holders' / (os.environ['OTTO_HEAVY_LEASE'] + '.json')
record = json.loads(path.read_text())
assert record['pid'] == os.getpid() == record['pgid']
assert record['launch_state'] == 'recorded'
assert record['processes'][str(os.getpid())]['birth']
"""
    proc = heavy(tmp_path, "--", *py(code))
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err


def test_dead_pending_launch_keeps_its_capacity_claim(tmp_path):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    for sub in ("holders", "waiting", "slots"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    path = directory / "holders" / "pending.json"
    path.write_text(json.dumps({"lease_id": "pending", "holder_pid": 99999999,
                                "weight": 1, "launch_state": "pending"}))
    assert module._reap_dead_holders(directory)[0]["remaining"] == ["launch-pending"]
    assert path.exists()
    ticket = directory / "waiting" / "next.json"
    with ticket.open("w+") as mine:
        fcntl.flock(mine, fcntl.LOCK_EX)
        mine.write(json.dumps({"weight": 1, "purpose": "next", "queued_at": time.time()}))
        mine.flush()
        assert module._take(directory, 1, 1, ticket.name, False, lambda _backfill: None)[0] is None


def test_a_heavy_call_inside_a_heavy_job_runs_straight_through(tmp_path):
    inner = [sys.executable, "-m", "otto.hostctl.heavy", "--no-wait", "--", sys.executable, "-c", "print('inner ran')"]
    proc = heavy(tmp_path, "--", *inner)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0 and "inner ran" in out, err


def _span(marks: Path, name: str) -> tuple[float, float]:
    lines = dict(line.split("=") for line in marks.read_text().splitlines())
    return float(lines[name + "+"]), float(lines[name + "-"])


def _together(marks: Path, name: str, n: int) -> list[str]:
    # Start, then stay until N jobs have started (they can only all start if they run at once).
    return py(f"import time; open({str(marks)!r},'a').write('{name}+=%f\\n' % time.time())\n"
              f"while open({str(marks)!r}).read().count('+=') < {n}: time.sleep(0.05)\n"
              f"open({str(marks)!r},'a').write('{name}-=%f\\n' % time.time())")


def test_jobs_run_at_the_same_time_while_capacity_remains(tmp_path):
    marks = tmp_path / "marks"
    a = heavy(tmp_path, "--purpose", "frames A", "--", *_together(marks, "A", 3), capacity=3)
    b = heavy(tmp_path, "--purpose", "frames B", "--", *_together(marks, "B", 3), capacity=3)
    c = heavy(tmp_path, "--purpose", "frames C", "--", *_together(marks, "C", 3), capacity=3)
    for proc in (a, b, c):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    spans = [_span(marks, n) for n in "ABC"]
    assert max(s for s, _ in spans) < min(e for _, e in spans), "the three jobs did not overlap"


def test_a_heavier_job_waits_for_enough_slots_and_is_not_starved(tmp_path):
    marks, go = tmp_path / "marks", tmp_path / "go"
    quick = lambda name: py(f"open({str(marks)!r},'a').write('{name}\\n')")
    first = heavy(tmp_path, "--weight", "1", "--", *_mark_then_wait(marks, "small1", go), capacity=2)
    holding(tmp_path, 1, capacity=2)
    big = heavy(tmp_path, "--weight", "2", "--purpose", "full render", "--", *quick("big"), capacity=2)
    assert "waiting for 2 slot(s)" in big.stderr.readline()  # it heads the queue
    later = heavy(tmp_path, "--weight", "1", "--", *quick("small2"), capacity=2)
    ticketed(tmp_path, 2)
    assert started(marks) == ["small1"], "the 2-slot job or a later small job started while a slot was taken"
    go.write_text("")
    for proc in (first, big, later):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    assert started(marks) == ["small1", "big", "small2"], "a later small job jumped the queue ahead of the big one"


def test_a_small_job_uses_a_slot_the_waiting_head_cannot_and_never_delays_it(tmp_path):
    # 4 slots: a 3-slot render runs; a 3-slot job waits at the head with 1 slot free. A 1-slot check
    # behind it takes that slot at once; a second one doesn't (the head must still fit beside it).
    marks = tmp_path / "marks"
    go = {n: tmp_path / f"go_{n}" for n in ("render", "head", "check")}
    render = heavy(tmp_path, "--weight", "3", "--", *_mark_then_wait(marks, "render", go["render"]), capacity=4)
    holding(tmp_path, 3, capacity=4)
    head = heavy(tmp_path, "--weight", "3", "--purpose", "transcript", "--",
                 *_mark_then_wait(marks, "head", go["head"]), capacity=4)
    assert "waiting for 3 slot(s)" in head.stderr.readline()  # it heads the queue
    check = heavy(tmp_path, "--weight", "1", "--purpose", "gate", "--",
                  *_mark_then_wait(marks, "check", go["check"]), capacity=4)
    holding(tmp_path, 4, capacity=4)
    assert await_started(marks, 2) == ["render", "check"], "the check waited although the head couldn't use the free slot"
    second = heavy(tmp_path, "--weight", "1", "--", *py(f"open({str(marks)!r},'a').write('second\\n')"), capacity=4)
    ticketed(tmp_path, 2)
    assert started(marks) == ["render", "check"], "a second small job backfilled into room the head needs"
    go["render"].write_text("")
    assert await_started(marks, 3) == ["render", "check", "head"], "the head did not start right after the render ended"
    # the head started while the check still runs, and the second small job is still behind it
    go["head"].write_text(""); go["check"].write_text("")
    for proc in (render, head, check, second):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    assert started(marks) == ["render", "check", "head", "second"]


def test_status_shows_capacity_and_what_is_running(tmp_path):
    go = tmp_path / "go"
    job = heavy(tmp_path, "--weight", "2", "--purpose", "journey X", "--",
                *_mark_then_wait(tmp_path / "marks", "X", go), capacity=4)
    holding(tmp_path, 2, capacity=4)
    status = json.loads(heavy(tmp_path, "status", capacity=4).communicate(timeout=30)[0])
    go.write_text("")
    job.communicate(timeout=30)
    assert status["capacity"] == 4 and status["used"] == 2 and status["free"] == 2
    assert status["holders"][0]["purpose"] == "journey X"


def test_status_exposes_unresolved_lease_and_recovery_action(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    for sub in ("slots", "holders", "waiting"):
        (directory / sub).mkdir(parents=True)
    unresolved = {"reaped": [42], "remaining": ["identity-unavailable:43", "group:42"],
                  "sweep": "unavailable"}
    (directory / "holders" / "lease-42.json").write_text(json.dumps({
        "lease_id": "lease-42", "owner": "worker", "purpose": "render", "weight": 2,
        "unresolved": unresolved,
    }))
    monkeypatch.setattr(module, "state_dir", lambda: directory)
    monkeypatch.setattr(module, "machine_state", lambda: {})
    monkeypatch.setattr(module, "capacity", lambda _directory: 3)

    status = module.status()
    holder = status["holders"][0]
    assert holder["lease_id"] == "lease-42"
    assert holder["unresolved"] == unresolved
    assert "lease-42" in holder["next_action"]
    assert "identity-unavailable:43" in holder["next_action"]
    assert "claim held" in holder["next_action"]


def test_status_does_not_call_dead_holder_active_without_unresolved_detail(tmp_path, monkeypatch):
    from otto.hostctl import heavy as module

    directory = tmp_path / "state"
    for sub in ("slots", "holders", "waiting"):
        (directory / sub).mkdir(parents=True)
    (directory / "holders" / "stale.json").write_text(json.dumps({
        "lease_id": "stale", "owner": "worker", "purpose": "render", "weight": 1,
        "holder_pid": 99999999,
    }))
    monkeypatch.setattr(module, "state_dir", lambda: directory)
    monkeypatch.setattr(module, "machine_state", lambda: {})
    monkeypatch.setattr(module, "capacity", lambda _directory: 2)

    status = module.status()
    holder = status["holders"][0]
    assert status["used"] == 1
    assert holder["holder_state"] == "dead"
    assert holder["unresolved"] is None
    assert "stale" in holder["next_action"]
    assert "claim held" in holder["next_action"]
    assert "recovery" in holder["next_action"]
    assert "active" not in holder["next_action"]


def admitted(tmp_path: Path) -> list[str]:
    """Purposes in the order the pool admitted them (the log's admission stamp, not a racy child write)."""
    lines = (tmp_path / "state" / "heavy.log").read_text().splitlines()
    return [r["purpose"] for r in sorted(map(json.loads, lines), key=lambda r: r["admitted_ns"])]


def _queue(tmp_path, names_weights, capacity, already=0):
    """Start waiters one by one, each ticket observed before the next starts."""
    procs = []
    for n, (name, weight) in enumerate(names_weights, already + 1):
        procs.append(heavy(tmp_path, "--weight", str(weight), "--purpose", name, "--", *py("pass"), capacity=capacity))
        ticketed(tmp_path, n)
    return procs


def _holder(tmp_path, weight, capacity):
    go = tmp_path / "go0"
    marks = tmp_path / "marks0"
    proc = heavy(tmp_path, "--weight", str(weight), "--purpose", "H0", "--", *_mark_then_wait(marks, "H0", go),
                 capacity=capacity)
    holding(tmp_path, weight, capacity=capacity)
    return proc, go


def test_waiters_start_in_arrival_order(tmp_path):
    holder, go = _holder(tmp_path, 1, 1)
    procs = _queue(tmp_path, [("A", 1), ("B", 1), ("C", 1)], 1)
    go.write_text("")
    for proc in (holder, *procs):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    assert admitted(tmp_path) == ["H0", "A", "B", "C"]


def test_backfill_takes_the_earliest_that_fits(tmp_path):
    # cap 6: H0 (4) runs, HEAD (3) waits with 2 free, so backfill room is 6 - 3 = 3. B2 (2) arrived before
    # B1 (1) and both fit: B2 goes first. We hold the admission guard while both arrive, so neither polls first.
    holder, go = _holder(tmp_path, 4, 6)
    head = _queue(tmp_path, [("HEAD", 3)], 6)
    with open(tmp_path / "state" / "admit.lock", "a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        rest = _queue(tmp_path, [("B2", 2), ("B1", 1)], 6, already=1)
    while not (tmp_path / "state" / "heavy.log").exists() or len(admitted(tmp_path)) < 2:
        time.sleep(0.05)  # both backfillers have run and ended while H0 still holds its slots
    go.write_text("")
    for proc in (holder, *head, *rest):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    assert admitted(tmp_path) == ["H0", "B2", "B1", "HEAD"]


def test_a_killed_waiter_never_blocks_the_queue(tmp_path):
    holder, go = _holder(tmp_path, 1, 1)
    doomed, nxt = _queue(tmp_path, [("doomed", 1), ("next", 1)], 1)
    doomed.kill()
    doomed.communicate()
    go.write_text("")
    holder.communicate(timeout=60)
    nxt.communicate(timeout=60)
    assert nxt.returncode == 0 and admitted(tmp_path) == ["H0", "next"]


def test_a_later_small_job_never_overtakes_the_waiting_gate(tmp_path):
    # The real friction: a 4-slot job holds the pool; a 1-slot gate waits; later 1- and 2-slot jobs must not pass it.
    holder, go = _holder(tmp_path, 4, 4)
    procs = _queue(tmp_path, [("gate", 1), ("S1", 1), ("S2", 1), ("M", 2)], 4)
    go.write_text("")
    for proc in (holder, *procs):
        proc.communicate(timeout=60)
        assert proc.returncode == 0
    assert admitted(tmp_path) == ["H0", "gate", "S1", "S2", "M"]


def test_a_ticket_nobody_holds_is_ignored_even_if_its_pid_is_alive(tmp_path):
    # A killed waiter's pid can be reused by an unrelated live process; only the ticket's lock says it waits.
    (tmp_path / "state" / "waiting").mkdir(parents=True)
    stale = tmp_path / "state" / "waiting" / f"1-{os.getpid()}.json"
    stale.write_text(json.dumps({"pid": os.getpid(), "weight": 1, "purpose": "ghost", "queued_at": 0}))
    proc = heavy(tmp_path, "--", *py("pass"))
    proc.communicate(timeout=60)
    assert proc.returncode == 0 and not stale.exists()

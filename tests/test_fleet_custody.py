"""Process-tree custody: the birth-fenced group kill, the fail-closed census and the cleanup latch.

Every test launches real processes and kills every group or pid it launched in a ``finally``.
"""
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from unittest import mock

from herzchen.fleet import custody

DEVNULL = subprocess.DEVNULL


def _reap_tree(leader):
    """Kill the group led by a process this test launched, then reap the leader. Safe to call twice."""
    if leader is None:
        return
    try:
        os.killpg(leader.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        leader.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _kill_pid(pid):
    """Kill one pid this test launched (an escapee outside the group)."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _observe_until(owner, ready, seconds=5.0):
    """Poll the owner's census until ``ready(live)`` holds, bounded. Returns the last live map."""
    deadline = time.monotonic() + seconds
    while True:
        live = owner.observe() or {}
        if ready(live) or time.monotonic() >= deadline:
            return live
        time.sleep(0.05)


def _dead_pids(pids, seconds=2.0):
    """The pids that still answer signal 0 after a bounded wait. ``[]`` means all are gone.

    Callers reap their own leaders first: a zombie still answers signal 0.
    """
    pending = set(pids)
    deadline = time.monotonic() + seconds
    while True:
        for pid in list(pending):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pending.discard(pid)
            except PermissionError:
                pass  # the pid exists under another owner: still alive
        if not pending or time.monotonic() >= deadline:
            return sorted(pending)
        time.sleep(0.05)


def _write_latch(path, pgid, leader_birth, members):
    """Hand-write a latch record in the format the owner persists."""
    record = {"pgid": pgid, "leader_birth": leader_birth, "state": "running",
              "members": {str(pid): birth for pid, birth in members.items()}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    return str(path)


def test_empty_census_is_uncertain():
    snap = custody.census()
    assert isinstance(snap, dict) and os.getpid() in snap, "the real census lists this very process"

    blank = mock.MagicMock()
    blank.__enter__.return_value = blank
    blank.communicate.return_value = ("", None)
    blank.returncode = 0
    with mock.patch.object(custody, "_REAL_POPEN", return_value=blank):
        assert custody.census() is None, "an empty table is a broken census, not an empty machine"

    owner = None
    try:
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & wait"], census_fn=lambda: {},
                                       stdout=DEVNULL, stderr=DEVNULL)
        assert owner.doubt is not None, "no leader identity was captured, so doubt is latched"
        disposition = owner.terminate(0.2)
        assert disposition.state == "uncertain", disposition
        assert not disposition.gone
    finally:
        _reap_tree(owner.process if owner is not None else None)


def test_cleanup_latch_resumes_after_crash(tmp_path):
    latch = str(tmp_path / "latch.json")
    leaders = []
    owner = None
    try:
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & sleep 31 & wait"], latch_path=latch,
                                       stdout=DEVNULL, stderr=DEVNULL)
        leaders.append(owner.process)
        live = _observe_until(owner, lambda seen: len(seen) >= 3)
        assert len(live) >= 3, "the leader and both sleeps were tracked within 5s"
        live = owner.observe() or {}
        tracked = sorted(live)

        with open(latch, encoding="utf-8") as handle:
            record = json.load(handle)
        assert record["pgid"] == owner.pgid, "the latch names the group before any signal"
        assert set(record["members"]) == {str(pid) for pid in tracked}, "the latch names every tracked member"

        owner = None  # the owner crashes: no terminate, no Popen handle kept by custody
        assert os.path.exists(latch)
        disposition = custody.resume_cleanup(latch, 0.3)
        assert disposition.state == "gone", disposition
        leaders[0].wait(timeout=2)  # our zombie leader; a zombie still answers signal 0
        assert _dead_pids(tracked) == []
        assert not os.path.exists(latch), "a gone cleanup retires its latch"

        # A latch whose census is empty must stay uncertain and keep its file.
        second = str(tmp_path / "latch-empty.json")
        owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 30 & sleep 31 & wait"], latch_path=second,
                                       stdout=DEVNULL, stderr=DEVNULL)
        leaders.append(owner.process)
        assert len(_observe_until(owner, lambda seen: len(seen) >= 3)) >= 3
        owner.observe()
        owner = None
        disposition = custody.resume_cleanup(second, 0.3, census_fn=lambda: {})
        assert disposition.state == "uncertain", disposition
        assert os.path.exists(second), "an uncertain cleanup keeps its latch"
    finally:
        if owner is not None:
            leaders.append(owner.process)
        for leader in leaders:
            _reap_tree(leader)


def test_reused_pgid_never_signalled(tmp_path):
    bystander = subprocess.Popen(["sleep", "30"], start_new_session=True, stdout=DEVNULL, stderr=DEVNULL)
    try:
        with mock.patch.object(custody.os, "kill", wraps=os.kill) as kill, \
                mock.patch.object(custody.os, "killpg", wraps=os.killpg) as killpg:
            def touched():
                return [c for c in kill.call_args_list + killpg.call_args_list
                        if c.args and c.args[0] == bystander.pid]

            # The leader pid is alive with a different birth: the old group is provably gone.
            stale = _write_latch(tmp_path / "stale.json", bystander.pid, "stale-birth",
                                 {bystander.pid: "stale-birth"})
            disposition = custody.resume_cleanup(stale, 0.3)
            assert disposition.state == "gone", disposition
            assert bystander.poll() is None, "a reused group id is never signalled"
            assert touched() == [], "no signal reached the bystander"
            assert not os.path.exists(stale)

            # The leader birth is unknown and the members cannot be proven ours: uncertain, latch kept.
            mismatch = _write_latch(tmp_path / "mismatch.json", bystander.pid, None,
                                    {bystander.pid: "stale-birth"})
            disposition = custody.resume_cleanup(mismatch, 0.3)
            assert disposition.state == "uncertain", disposition
            assert bystander.poll() is None
            assert touched() == [], "no signal reached the bystander"
            assert os.path.exists(mismatch), "an uncertain cleanup keeps its latch"

            # The unit check: the stale identity never passes the group signal fence.
            unit = custody.Custody(None, bystander.pid, "stale-birth", {bystander.pid: "stale-birth"})
            assert unit.signal_group(signal.SIGTERM) is False
            assert bystander.poll() is None
            assert touched() == [], "no signal reached the bystander"
    finally:
        _reap_tree(bystander)


def test_group_kill_takes_grandchildren_and_setsid_escapees(tmp_path):
    pidfile = tmp_path / "escapee.pid"
    script = "\n".join([
        "import os, sys, time",
        "pidfile = sys.argv[1]",
        "if os.fork() == 0:",
        "    os.setsid()",
        "    with open(pidfile + '.tmp', 'w') as handle:",
        "        handle.write(str(os.getpid()))",
        "    os.replace(pidfile + '.tmp', pidfile)",
        "    time.sleep(42)",
        "    os._exit(0)",
        "time.sleep(42)",
    ])
    command = "sleep 40 & sh -c 'sleep 41 & wait' & %s -c %s %s & wait" % (
        shlex.quote(sys.executable), shlex.quote(script), shlex.quote(str(pidfile)))
    owner = custody.Custody.launch(["/bin/sh", "-c", command], stdout=DEVNULL, stderr=DEVNULL)
    leader = owner.process
    escapee = None
    try:
        deadline = time.monotonic() + 5.0
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), "the python child started its setsid grandchild within 5s"
        escapee = int(pidfile.read_text(encoding="utf-8"))
        assert os.getpgid(escapee) != owner.pgid, "the grandchild really left the group"

        live = _observe_until(owner, lambda seen: escapee in seen and len(seen) >= 6)
        assert escapee in live, "the setsid escapee was adopted through its tracked parent"
        tracked = sorted(live)

        disposition = owner.terminate(0.3)
        assert disposition.state == "gone", disposition
        leader.wait(timeout=2)
        assert _dead_pids(tracked) == [], "every grouped and escaped pid is dead"
    finally:
        if escapee is not None:
            _kill_pid(escapee)
        _reap_tree(leader)


def test_normal_exit_release_sweeps_stragglers():
    owner = custody.Custody.launch(["/bin/sh", "-c", "sleep 40 & sleep 1; exit 0"],
                                   stdout=DEVNULL, stderr=DEVNULL)
    leader = owner.process
    try:
        time.sleep(0.3)
        live = owner.observe() or {}
        assert len(live) >= 2, "the straggler sleep is tracked while the shell still runs"
        tracked = sorted(live)

        assert leader.wait(timeout=5) == 0, "the shell finished on its own"
        disposition = owner.release()
        assert disposition.state == "gone", disposition
        assert _dead_pids(tracked) == [], "the straggler was swept"
    finally:
        _reap_tree(leader)

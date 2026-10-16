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

from herzchen.adapters import host as host_module
from herzchen.contracts import HostIdentity, HostOperation, HostOutcome, HostRequest, ResourceRef
from herzchen.fleet import custody
from herzchen.fleet.hosts.codex import CodexStream

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


# -- the Codex CLI binding over custody: timeout, interrupt and a recycled pid ----------------------

CODEX_USAGE = {"input_tokens": 3, "output_tokens": 1}


def _ps_stat(pid):
    """The ps state column for pid ('' when ps lists nothing). Uses the real Popen even under a patch."""
    proc = custody._REAL_POPEN(["ps", "-o", "stat=", "-p", str(pid)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    out, _ = proc.communicate(timeout=5)
    return out.strip()


def _is_dead(pid):
    """Gone: no such pid, or a zombie (or nothing listed by ps). A pid this test did not launch is never touched."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    stat = _ps_stat(pid)
    return stat == "" or stat.startswith("Z")


def _await_dead(pids, seconds=3.0):
    """The pids still alive after a bounded wait. ``[]`` means every one is dead or a zombie."""
    deadline = time.monotonic() + seconds
    while True:
        alive = [pid for pid in pids if not _is_dead(pid)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.05)


def _pids_in(paths):
    """Pids this test's fake CLI wrote to its own files. Missing or unreadable files contribute nothing."""
    pids = []
    for path in paths:
        try:
            pids.append(int(path.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            pass
    return pids


def _fake_cli(directory, body):
    """A fake Codex CLI: a python script used as the launcher. It reads its prompt, then runs ``body``."""
    path = os.path.join(str(directory), "fake-codex")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!%s\n" % sys.executable)
        handle.write("import json, os, shlex, signal, subprocess, sys, time\n")
        handle.write("DEVNULL = subprocess.DEVNULL\n")
        handle.write("def emit(event):\n    print(json.dumps(event), flush=True)\n")
        handle.write("sys.stdin.read()\n")
        handle.write(body)
    os.chmod(path, 0o755)
    return path


def _binding(directory, launcher, **overrides):
    """A real CodexCliBinding with a one-second finite start deadline."""
    options = {"timeout_seconds": 1.0, "occurrence_deadline": time.monotonic() + 10}
    options.update(overrides)
    return host_module.CodexCliBinding(worktree=str(directory), launcher=launcher, prompt="fake brief", **options)


def _invoke():
    return HostRequest(HostOperation.INVOKE, HostIdentity("fixture-worker", None),
                       ResourceRef("fixture", "work.task", "task", "rev-1"), "read-only")


def _turn_lines():
    return [json.dumps({"type": "thread.started", "thread_id": "fake-session"}),
            json.dumps({"type": "turn.started", "turn_id": "turn-1"}),
            json.dumps({"type": "turn.completed", "turn_id": "turn-1", "usage": CODEX_USAGE})]


def _shape(value):
    """Keys and list structure only, leaves collapsed: two captures with the same shape have the same fields."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_shape(item) for item in value[:1]]
    return "leaf"


def test_codex_timeout_kills_group(tmp_path):
    child_file, grand_file = tmp_path / "child.pid", tmp_path / "grand.pid"
    grand_code = ("import os, time; os.setsid(); open(%r, 'w').write(str(os.getpid())); time.sleep(60)"
                  % str(grand_file))
    body = (
        "emit({'type': 'thread.started', 'thread_id': 'fake-session'})\n"
        "child = subprocess.Popen(['sleep', '60'], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "open(%r, 'w').write(str(child.pid))\n"
        "subprocess.Popen(['/bin/sh', '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "time.sleep(60)\n" % (str(child_file), "%s -c %s & wait" % (sys.executable, shlex.quote(grand_code))))
    launcher = _fake_cli(tmp_path, body)
    try:
        receipt, envelope = _binding(tmp_path, launcher).execute(_invoke())
        assert child_file.exists() and grand_file.exists(), "the fake CLI launched the child and the setsid grandchild"
        pids = _pids_in([child_file, grand_file])
        assert receipt.outcome == HostOutcome.UNKNOWN, receipt
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        assert envelope["exit_status"] is None
        assert _await_dead(pids, 3.0) == [], "the same-group child and the setsid grandchild are both dead within 3s"
    finally:
        for pid in _pids_in([child_file, grand_file]):
            _kill_pid(pid)


def test_codex_interrupt_after_usage_is_unknown(tmp_path):
    interrupted_dir, normal_dir = tmp_path / "interrupted", tmp_path / "normal"
    interrupted_dir.mkdir()
    normal_dir.mkdir()
    lines = _turn_lines()
    # The CLI reports the whole turn, then kills itself with SIGTERM: exit status -15.
    interrupted = _fake_cli(interrupted_dir, "for line in %r:\n    print(line, flush=True)\n"
                            "os.kill(os.getpid(), signal.SIGTERM)\ntime.sleep(5)\n" % (lines,))
    normal = _fake_cli(normal_dir, "for line in %r:\n    print(line, flush=True)\nsys.exit(0)\n" % (lines,))

    receipt, envelope = _binding(interrupted_dir, interrupted).execute(_invoke())
    assert envelope["exit_status"] == -15, envelope["exit_status"]
    assert receipt.outcome == HostOutcome.UNKNOWN, "an interrupted turn is unknown, never failed"
    assert receipt.unsupported_reason == "codex_execution_interrupted", receipt
    assert envelope["usage_capture"], "usage observed before the interrupt is retained"

    normal_receipt, normal_envelope = _binding(normal_dir, normal).execute(_invoke())
    assert normal_receipt.outcome == HostOutcome.SUCCEEDED, normal_receipt
    assert _shape(envelope["usage_capture"]) == _shape(normal_envelope["usage_capture"]), \
        "the interrupted capture has the same shape as a normal turn's"

    # The same three records through the stream: the exit code alone decides the outcome.
    for code, expected in ((-2, "unknown"), (1, "failed"), (0, "succeeded")):
        stream = CodexStream()
        for line in lines:
            stream.feed(line)
        result = stream.finish(code)
        assert result.outcome == expected, (code, result.outcome)
        assert result.usage_capture is not None, code


def test_timed_out_fake_cli_leaves_nothing_and_spares_reused_pid(tmp_path):
    # C1: a same-group child with a grandchild in the same group, plus a child that ignores SIGTERM.
    ignoring_file, sh_file, grand_file = tmp_path / "ignoring.pid", tmp_path / "sh.pid", tmp_path / "grand.pid"
    ignoring_code = ("import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                     "open(%r, 'w').write(str(os.getpid())); time.sleep(60)" % str(ignoring_file))
    shell_code = "sleep 60 & echo $! > %s; wait" % shlex.quote(str(grand_file))
    body = (
        "emit({'type': 'thread.started', 'thread_id': 'fake-session'})\n"
        "ignoring = subprocess.Popen([sys.executable, '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "for _ in range(500):\n"
        "    if os.path.exists(%r):\n        break\n"
        "    time.sleep(0.01)\n"
        "shell = subprocess.Popen(['/bin/sh', '-c', %r], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)\n"
        "open(%r, 'w').write(str(shell.pid))\n"
        "time.sleep(60)\n" % (ignoring_code, str(ignoring_file), shell_code, str(sh_file)))
    launcher = _fake_cli(tmp_path, body)
    files = [ignoring_file, sh_file, grand_file]
    try:
        receipt, envelope = _binding(tmp_path, launcher).execute(_invoke())
        assert all(path.exists() for path in files), "the ignoring child, the shell and its grandchild all started"
        pids = _pids_in(files)
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        assert _await_dead(pids, 3.0) == [], "no child, grandchild or SIGTERM-ignoring child is left"
    finally:
        for pid in _pids_in(files):
            _kill_pid(pid)

    # C2: the launch-time census shows the pid with another birth, so the group id was recycled after launch.
    bystander = subprocess.Popen(["sleep", "60"], start_new_session=True, stdout=DEVNULL, stderr=DEVNULL)
    real_census = custody.census
    try:
        real = real_census()
        assert real is not None and bystander.pid in real, "the real census lists the bystander"
        at_launch = dict(real)
        info = real[bystander.pid]
        at_launch[bystander.pid] = custody.Proc(info.pid, info.ppid, info.pgid, "launch-birth", info.zombie)
        calls = []

        def census_after_launch():
            calls.append(1)
            return at_launch if len(calls) == 1 else real_census()   # the first census is taken at launch

        stand_in = mock.MagicMock(name="stand_in")
        stand_in.pid = bystander.pid
        stand_in.stdout = None      # the communicate-only branch: the timeout is a TimeoutExpired from communicate
        stand_in.stderr = None
        stand_in.poll.return_value = 0   # reaped as far as custody can see: the group is never "ours" by leader
        stand_in.returncode = 0
        stand_in.wait.return_value = 0
        stand_in.communicate.side_effect = [subprocess.TimeoutExpired("codex", 1.0), ("", "")]

        with mock.patch.object(custody.os, "kill", wraps=os.kill) as kill, \
                mock.patch.object(custody.os, "killpg", wraps=os.killpg) as killpg, \
                mock.patch.object(host_module.subprocess, "Popen", return_value=stand_in), \
                mock.patch.object(custody, "census", side_effect=census_after_launch):
            receipt, envelope = _binding(tmp_path, "/fixture/codex").execute(_invoke())
        assert receipt.outcome == HostOutcome.UNKNOWN, receipt
        assert receipt.unsupported_reason == "codex_execution_timeout", receipt
        touched = [c for c in kill.call_args_list + killpg.call_args_list
                   if c.args and c.args[0] == bystander.pid]
        assert touched == [], "no kill or killpg reached the bystander pid or its group"
        assert bystander.poll() is None, "a recycled pid is never signalled: the bystander is still alive"
        assert len(calls) > 1, "the timeout path consulted the census after launch"
    finally:
        _reap_tree(bystander)

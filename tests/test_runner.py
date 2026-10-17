"""The fleet runner against its design spec (.runner-design.md): real processes, a real unix socket.

Every test launches processes through a Runner (or Custody) and the ``harness`` fixture stops every runner,
shuts every socket server and kills every raw process the test started, even when the test fails.
Waits are polling loops with a 10 second deadline; no assertion depends on a fixed sleep.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from herzchen.fleet.capacity import CapacityPolicy, CapacityPool
from herzchen.fleet.custody import Custody, Disposition, Proc
from herzchen.fleet.runner import (
    EXIT_UNKNOWN,
    Entry,
    Holder,
    ResultStore,
    Runner,
    RunnerClient,
    RunnerServer,
    StoreError,
    git_commit_identity,
    pick,
)

PY = sys.executable
SRC = str(Path(__file__).resolve().parents[1] / "src")
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (SRC, os.environ.get("PYTHONPATH", "")) if p))

GATE_CODE = "import os,time,sys\nwhile not os.path.exists(sys.argv[1]): time.sleep(0.05)"
QUICK = [PY, "-c", "print('ok')"]
COUNT_CODE = "import sys\nopen(sys.argv[1], 'a').write('x\\n')\n"
GATE_COUNT_CODE = ("import os, sys, time\n"
                   "open(sys.argv[1], 'a').write('x\\n')\n"
                   "while not os.path.exists(sys.argv[2]):\n"
                   "    time.sleep(0.05)\n")
MARK_CODE = "import sys\nopen(sys.argv[1], 'w').write('ran')\n"
SLEEPER_CODE = ("import os, sys, time\n"
                "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
                "time.sleep(5)\n")
USAGE_CODE = ("import json, os, sys, time\n"
              "path = os.environ['RUNNER_USAGE_PATH']\n"
              "os.makedirs(os.path.dirname(path), exist_ok=True)\n"
              "open(path, 'w').write(json.dumps({'tokens': int(sys.argv[1])}))\n"
              "time.sleep(float(sys.argv[2]))\n")
ORPHAN_CODE = ("import os, subprocess, sys, time\n"
               "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(1)'])\n"
               "open(sys.argv[1], 'w').write(str(child.pid))\n"
               "while not os.path.exists(sys.argv[2]): time.sleep(0.05)\n")

NESTED_CLIENT_SRC = '''\
import json, os, sys
from herzchen.fleet.runner.client import RunnerClient

NESTED_CODE = "import sys\\nopen(sys.argv[1], 'w').write('nested')\\nsys.exit(4)\\n"


def _write_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(value, handle)
    os.replace(tmp, path)


def run(sock, cwd, marker, out):
    client = RunnerClient(sock, timeout=30)
    argv = [sys.executable, "-c", NESTED_CODE, marker]
    resp = client.call({"op": "submit", "argv": argv, "cwd": cwd, "task": "nested", "purpose": "nested check"})
    _write_json(out, resp)
    if not resp.get("ok"):
        return 99
    got = client.call({"op": "await", "run_id": resp["run_id"], "timeout": 20})
    return int(got.get("exit_code", 98))


if __name__ == "__main__":
    sys.exit(run(*sys.argv[1:5]))
'''

PARENT_SRC = '''\
import os, subprocess, sys, time
import nested_client

sock, cwd, marker, out, gate, mode = sys.argv[1:7]
if mode == "direct":
    code = nested_client.run(sock, cwd, marker, out)
else:
    here = os.path.dirname(os.path.abspath(__file__))
    child = subprocess.Popen([sys.executable, os.path.join(here, "nested_client.py"), sock, cwd, marker, out],
                             start_new_session=True)
    code = child.wait()
tmp = out + ".done.tmp"
with open(tmp, "w") as handle:
    handle.write(str(code))
os.replace(tmp, out + ".done")
while not os.path.exists(gate):
    time.sleep(0.05)
sys.exit(code)
'''


# -- helpers ---------------------------------------------------------------------------------------

def wait_until(predicate, what, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for %s" % what)
        time.sleep(0.02)


def wait_state(store, run_id, *states):
    wait_until(lambda: (store.get(run_id) or {}).get("state") in states,
               "%s to be %s" % (run_id, "/".join(states)))


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lines(path):
    return path.read_text().count("\n") if path.exists() else 0


def gate_cmd(path):
    return [PY, "-c", GATE_CODE, str(path)]


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=runner-test",
                           "-c", "user.email=runner-test@example.invalid", "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def make_repo(path: Path) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    (path / "a.txt").write_text("one\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "init")
    return git(path, "rev-parse", "HEAD")


class Harness:
    """Builds runners, servers and raw processes under one tmp dir, and tears all of them down."""

    def __init__(self, tmp: Path, sock_dir: Path):
        self.tmp = Path(os.path.realpath(str(tmp)))
        self.sock_dir = sock_dir
        self.state = self.tmp / "state"
        self.lab = self.tmp / "lab"
        self.cwd = self.tmp / "cwd"
        for directory in (self.state, self.lab, self.cwd):
            directory.mkdir(parents=True, exist_ok=True)
        self.sock = None
        self._store = None
        self._runners = []
        self._servers = []
        self._procs = []

    @property
    def store(self) -> ResultStore:
        if self._store is None:
            self._store = self.new_store()
        return self._store

    def new_store(self) -> ResultStore:
        return ResultStore(self.state / "store", forbidden_roots=[str(self.lab)])

    def runner(self, *, pool=None, store=None, resolve=None, **kw) -> Runner:
        runner = Runner(pool if pool is not None else CapacityPool(CapacityPolicy(heavy_headroom=3)),
                        store if store is not None else self.store,
                        state_dir=self.state,
                        resolve_commit=resolve if resolve is not None else (lambda cwd: "c1"),
                        environ=ENV, grace_seconds=1.0, poll_seconds=0.05, **kw)
        self._runners.append(runner)
        runner.start()
        return runner

    def retire(self, runner) -> None:
        self._runners.remove(runner)
        runner.stop()

    def submit(self, runner, argv, cwd=None, **kw) -> str:
        resp = runner.submit({"argv": list(argv), "cwd": str(cwd if cwd is not None else self.cwd), **kw})
        assert resp["ok"], resp
        return resp["run_id"]

    def serve(self, runner) -> RunnerClient:
        self.sock = str(self.sock_dir / "r.sock")
        server = RunnerServer(runner, self.sock)
        self._servers.append(server)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return RunnerClient(self.sock, timeout=30)

    def sock_submit(self, client, argv, **kw) -> str:
        cwd = kw.pop("cwd", self.cwd)
        resp = client.call({"op": "submit", "argv": list(argv), "cwd": str(cwd), **kw})
        assert resp.get("ok") is True, resp
        return resp["run_id"]

    def popen(self, argv, **kw) -> subprocess.Popen:
        kw.setdefault("stdout", subprocess.DEVNULL)
        kw.setdefault("stderr", subprocess.DEVNULL)
        proc = subprocess.Popen(argv, **kw)
        self._procs.append(proc)
        return proc

    def scripts(self) -> dict:
        directory = self.tmp / "scripts"
        directory.mkdir(exist_ok=True)
        paths = {"client": directory / "nested_client.py", "parent": directory / "parent.py"}
        paths["client"].write_text(NESTED_CLIENT_SRC)
        paths["parent"].write_text(PARENT_SRC)
        return {name: str(path) for name, path in paths.items()}

    def record(self, store, run_id, argv, commit, state, cwd=None, **over) -> dict:
        """A complete record in the spec's shape, with a correct binding (the seal is set by put)."""
        cwd = os.path.realpath(str(cwd if cwd is not None else self.cwd))
        rec = {"run_id": run_id, "seq": store.next_seq(), "binding": store.binding(list(argv), cwd, commit),
               "argv": list(argv), "cwd": cwd, "commit": commit, "task": "t", "purpose": run_id,
               "units": 1, "weight_requested": 1, "max_seconds": 3600.0, "state": state, "outcome": None,
               "exit_code": None, "nested_in": None, "backfill": False, "submitted_at": time.time(),
               "started_at": None, "settled_at": None, "seconds": None, "unit_seconds": None, "tokens": 0,
               "custody": None, "output_sha256": None, "output_bytes": 0}
        rec.update(over)
        return rec

    def write_raw(self, record) -> Path:
        """Write a record file straight into store/runs, as a process that bypasses the runner would."""
        path = self.state / "store" / "runs" / (record["run_id"] + ".json")
        path.write_text(json.dumps(record, sort_keys=True))
        os.chmod(path, 0o600)
        return path

    def close(self) -> None:
        errors = []
        for server in self._servers:
            try:
                server.shutdown()
                server.server_close()
            except Exception as exc:  # keep tearing down the rest
                errors.append(exc)
        for runner in reversed(self._runners):
            try:
                runner.stop()
            except Exception as exc:
                errors.append(exc)
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        if errors:
            raise errors[0]


@pytest.fixture
def harness(tmp_path):
    sock_dir = Path(tempfile.mkdtemp(dir="/tmp", prefix="rn-"))
    h = Harness(tmp_path, sock_dir)
    try:
        yield h
    finally:
        try:
            h.close()
        finally:
            shutil.rmtree(sock_dir, ignore_errors=True)


# -- 1. narrow checks are not blocked behind a wide waiter -----------------------------------------

def test_narrow_check_not_blocked_behind_wide_waiter(harness):
    runner, store = harness.runner(), harness.store
    gate_a, gate_w, gate_b = (harness.tmp / name for name in ("gate-a", "gate-w", "gate-b"))

    a = harness.submit(runner, gate_cmd(gate_a), weight=2, request_id="a")
    wait_state(store, a, "running")
    w = harness.submit(runner, gate_cmd(gate_w), weight=2, request_id="w")
    assert store.get(w)["state"] == "queued"                    # free 1 < 2: the wide head waits
    x = harness.submit(runner, QUICK, weight=2, request_id="x")  # wide, behind the head
    assert store.get(x)["state"] == "queued"

    n = harness.submit(runner, QUICK, weight=1, request_id="n")  # narrow check backfills and settles
    wait_state(store, n, "settled")
    assert store.get(n)["backfill"] is True
    assert store.get(a)["state"] == "running"
    assert store.get(w)["state"] == "queued"
    assert store.get(x)["state"] == "queued"

    b = harness.submit(runner, gate_cmd(gate_b), weight=1, request_id="b")  # a second backfilled holder
    wait_state(store, b, "running")
    assert store.get(b)["backfill"] is True
    assert store.get(x)["state"] == "queued"                    # the wide candidate never backfills

    n2 = harness.submit(runner, QUICK, weight=1, request_id="n2")
    assert store.get(n2)["state"] == "queued"                   # room is 0 while b holds

    gate_a.touch()                                              # A ends: the head W fits and starts
    wait_state(store, w, "running")
    assert store.get(b)["state"] == "running"                   # W started while b still holds
    assert store.get(w)["started_at"] >= store.get(a)["settled_at"]
    assert store.get(n2)["state"] == "queued"
    assert store.get(x)["state"] == "queued"

    gate_b.touch()                                              # b ends: N2 backfills behind W
    wait_until(lambda: store.get(n2)["started_at"] is not None, "n2 to start once b ends")
    assert store.get(w)["state"] == "running"
    assert store.get(w)["started_at"] <= store.get(n2)["started_at"]
    assert store.get(n2)["backfill"] is True
    assert store.get(x)["state"] == "queued"

    gate_w.touch()
    wait_state(store, x, "settled")                             # the wide job runs once the head is done


def test_admission_head_that_fits_is_never_a_backfill():
    head = Entry("h", 2, 1)
    assert pick([head, Entry("n", 1, 2)], [], 3) == (head, False)
    assert pick([head], [Holder(1, False)], 3) == (head, False)
    assert pick([], [], 3) is None


def test_admission_backfill_only_within_min_of_room_and_free():
    holders = [Holder(3, False)]                  # free 2; head of 3 cannot start
    head = Entry("h", 3, 1)
    wide, narrow, later = Entry("w", 3, 2), Entry("a", 2, 3), Entry("b", 1, 4)
    # room = 5 - 3 - 0 = 2 and free = 2: the first candidate in arrival order that fits is taken
    assert pick([head, wide, narrow, later], holders, 5) == (narrow, True)
    assert pick([head, wide], holders, 5) is None   # 3 > min(room, free)


def test_admission_backfilled_holders_shrink_the_room():
    head, narrow = Entry("h", 3, 1), Entry("a", 2, 2)
    holders = [Holder(3, False), Holder(1, True)]  # free 1, room = 5 - 3 - 1 = 1
    assert pick([head, narrow], holders, 5) is None
    one = Entry("one", 1, 3)
    assert pick([head, narrow, one], holders, 5) == (one, True)


# -- 2. await returns the exit code over the real socket -------------------------------------------

def test_await_returns_exit_code(harness):
    runner = harness.runner()
    client = harness.serve(runner)

    harness.sock_submit(client, [PY, "-c", "import sys; sys.exit(7)"], request_id="exit7")
    got = client.call({"op": "await", "run_id": "exit7", "timeout": 10})
    assert got["ok"] is True and got["done"] is True
    assert got["exit_code"] == 7
    assert got["record"]["state"] == "settled" and got["record"]["outcome"] == "exited"

    pidfile = harness.tmp / "sleeper.pid"
    harness.sock_submit(client, [PY, "-c", SLEEPER_CODE, str(pidfile)], request_id="sleeper", max_seconds=0.3)
    got = client.call({"op": "await", "run_id": "sleeper", "timeout": 10})
    assert got["exit_code"] == 124
    assert got["record"]["state"] == "settled" and got["record"]["outcome"] == "timed_out"
    pid = int(wait_until(lambda: pidfile.exists() and pidfile.read_text().strip(), "sleeper pid file"))
    wait_until(lambda: not alive(pid), "the timed-out sleeper to be gone")

    harness.sock_submit(client, [PY, "-c", "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n"],
                        request_id="killed")
    got = client.call({"op": "await", "run_id": "killed", "timeout": 10})
    assert got["exit_code"] == 128 + 9
    assert got["record"]["outcome"] == "exited"


# -- 3. the lab cannot write results ---------------------------------------------------------------

def test_lab_cannot_write_store(harness):
    lab = harness.lab

    # (a) a store inside the forbidden lab is refused, also through a symlink into it
    with pytest.raises(StoreError):
        ResultStore(lab / "store", forbidden_roots=[str(lab)])
    assert not list(lab.rglob("seal.key"))
    link = harness.tmp / "link"
    os.symlink(lab, link)
    with pytest.raises(StoreError):
        ResultStore(link / "store", forbidden_roots=[str(lab)])
    # a store whose root is later swapped for a symlink into the lab is refused on put
    moving = harness.tmp / "moving"
    store_swap = ResultStore(moving, forbidden_roots=[str(lab)])
    swap_record = harness.record(store_swap, "swap1", QUICK, "c1", "queued")
    shutil.rmtree(moving)
    os.symlink(lab, moving)
    with pytest.raises(StoreError):
        store_swap.put(swap_record)
    assert not list(lab.rglob("*.json"))

    # (b) the socket has no op that writes results, and submit ignores what a caller smuggles in
    runner = harness.runner()
    store = harness.store
    client = harness.serve(runner)
    for op in ("put_result", "settle", "result"):
        resp = client.call({"op": op, "run_id": "x1", "state": "settled", "exit_code": 0, "result": {"a": 1}})
        assert resp["ok"] is False and resp["error"] == "unknown_op", resp
    resp = client.call({"op": "submit", "argv": [PY, "-c", "import sys; sys.exit(3)"],
                        "cwd": str(harness.cwd), "request_id": "smug1", "state": "settled", "exit_code": 0,
                        "result": {"ok": True}, "store": "/x", "seal": "00"})
    assert resp["ok"] is True and resp["state"] in ("queued", "running"), resp
    got = client.call({"op": "await", "run_id": "smug1", "timeout": 10})
    assert got["exit_code"] == 3 and got["record"]["outcome"] == "exited"
    rec = store.get("smug1")
    assert rec["exit_code"] == 3 and "result" not in rec and "store" not in rec

    # (c) forged record files in store/runs are evidence_invalid and never summed
    fake = harness.record(store, "forged1", [PY, "-c", "pass"], "c1", "settled", exit_code=0, outcome="exited",
                          seal="ab" * 32)
    harness.write_raw(fake)
    got = client.call({"op": "await", "run_id": "forged1", "timeout": 1})
    assert got["ok"] is False and got["error"] == "evidence_invalid"

    harness.sock_submit(client, [PY, "-c", "import sys; sys.exit(5)"], request_id="real1")
    assert client.call({"op": "await", "run_id": "real1", "timeout": 10})["exit_code"] == 5
    real_path = harness.state / "store" / "runs" / "real1.json"
    doc = json.loads(real_path.read_text())
    doc["exit_code"] = 0                                        # the lab edits a real record
    real_path.write_text(json.dumps(doc, sort_keys=True))
    got = client.call({"op": "await", "run_id": "real1", "timeout": 1})
    assert got["ok"] is False and got["error"] == "evidence_invalid"

    rep = client.call({"op": "report"})
    verified, invalid = store.all_records()
    assert rep["ok"] is True
    assert sorted(rep["invalid"]) == ["forged1", "real1"] == sorted(invalid)
    assert rep["totals"]["runs"] == len(verified) == 1

    # (d) resubmitting under a forged run_id launches nothing
    marker = harness.tmp / "forged-launched"
    for rid in ("forged1", "real1"):
        resp = client.call({"op": "submit", "argv": [PY, "-c", MARK_CODE, str(marker)],
                            "cwd": str(harness.cwd), "request_id": rid})
        assert resp["ok"] is False and resp["error"] == "evidence_invalid", resp
    harness.sock_submit(client, QUICK, request_id="sentinel1")
    assert client.call({"op": "await", "run_id": "sentinel1", "timeout": 10})["exit_code"] == 0
    assert not marker.exists()


# -- 4. restart never reruns a settled run; latches; commit identity -------------------------------

def test_restart_never_reruns_settled(harness):
    counter = harness.tmp / "counter"
    argv = [PY, "-c", COUNT_CODE, str(counter)]
    first = harness.runner()
    harness.submit(first, argv, request_id="r1")
    assert first.await_run("r1", timeout=10)["exit_code"] == 0
    seal = harness.store.get("r1")["seal"]
    assert lines(counter) == 1
    harness.retire(first)

    second = harness.runner(store=harness.new_store())          # a restart: new pool, new store object
    resp = second.submit({"argv": argv, "cwd": str(harness.cwd), "request_id": "r1"})
    assert resp["ok"] is True and resp["existing"] is True, resp
    assert lines(counter) == 1
    got = second.await_run("r1", timeout=10)
    assert got["exit_code"] == 0 and got["record"]["seal"] == seal
    resp = second.submit({"argv": [PY, "-c", "print(1)"], "cwd": str(harness.cwd), "request_id": "r1"})
    assert resp["ok"] is False and resp["error"] == "binding_mismatch", resp
    harness.retire(second)

    third = harness.runner(store=harness.new_store(), resolve=lambda cwd: "c2")
    resp = third.submit({"argv": argv, "cwd": str(harness.cwd), "request_id": "r1"})
    assert resp["ok"] is False and resp["error"] == "binding_mismatch", resp   # never a result for another commit
    assert lines(counter) == 1
    harness.retire(third)


def test_restart_lost_running_and_queued_rules(harness):
    store = harness.store
    running_counter, queued_counter, stale_counter = (harness.tmp / n for n in
                                                      ("running-counter", "queued-counter", "stale-counter"))
    gate = harness.tmp / "never-created"
    store.put(harness.record(store, "lost1", [PY, "-c", GATE_COUNT_CODE, str(running_counter), str(gate)],
                             "c1", "running", started_at=time.time()))
    store.put(harness.record(store, "q-ok", [PY, "-c", COUNT_CODE, str(queued_counter)], "c1", "queued"))
    store.put(harness.record(store, "q-stale", [PY, "-c", COUNT_CODE, str(stale_counter)], "c0", "queued"))

    runner = harness.runner()                                  # restart: reconcile runs in the constructor
    got = runner.await_run("lost1", timeout=10)
    assert got["exit_code"] == EXIT_UNKNOWN
    assert got["record"]["state"] == "unknown" and got["record"]["outcome"] == "lost_in_restart"
    assert got["record"]["exit_code"] is None
    assert not running_counter.exists()                        # never relaunched

    got = runner.await_run("q-ok", timeout=10)
    assert got["exit_code"] == 0
    assert lines(queued_counter) == 1                          # launched exactly once
    got = runner.await_run("q-stale", timeout=10)
    assert got["exit_code"] == EXIT_UNKNOWN and got["record"]["outcome"] == "stale_commit"
    assert not stale_counter.exists()
    harness.retire(runner)

    again = harness.runner(store=harness.new_store())          # another restart: settled is never rerun
    assert again.await_run("q-ok", timeout=10)["exit_code"] == 0
    assert lines(queued_counter) == 1
    harness.retire(again)


def test_restart_kills_orphaned_tree_by_latch(harness):
    # Not launched through a Runner: a runner's own live _execute thread would race reconcile for the same
    # record. This drives the same latch a runner writes (state/latches/<run_id>.json) and checks that
    # reconcile's cleanup kills the whole tree before the record is settled.
    store = harness.store
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    rid = "orphan1"
    latch = latches / (rid + ".json")
    grand_pid_file = harness.tmp / "grandchild.pid"
    gate = harness.tmp / "orphan-gate"
    argv = [PY, "-c", ORPHAN_CODE, str(grand_pid_file), str(gate)]
    store.put(harness.record(store, rid, argv, "c1", "running", started_at=time.time()))
    leader = Custody.launch(argv, latch_path=str(latch), cwd=str(harness.cwd),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        grandchild = int(wait_until(lambda: grand_pid_file.exists() and grand_pid_file.read_text().strip(),
                                    "the grandchild pid"))
        runner = harness.runner(store=harness.new_store())     # restart over the same state dir
        got = runner.await_run(rid, timeout=10)
        assert got["exit_code"] == EXIT_UNKNOWN
        assert got["record"]["state"] == "unknown" and got["record"]["outcome"] == "lost_in_restart"
        assert got["record"]["custody"] == "gone"
        wait_until(lambda: not alive(grandchild), "the orphaned grandchild to be killed")
        assert not latch.exists()
        harness.retire(runner)
    finally:
        try:
            os.killpg(leader.pgid, 9)
        except OSError:
            pass
        leader.process.wait()


def test_uncertain_scope_holds_only_its_own_units(harness):
    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    class Scope:
        process = Process()

        def __init__(self, uncertain):
            self.uncertain = uncertain

        def release(self):
            return Disposition("uncertain" if self.uncertain else "gone")

    pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
    runner = harness.runner(pool=pool, launch=lambda argv, **kw: Scope(argv[-1] == "uncertain"))
    first = harness.submit(runner, ["fake", "uncertain"], weight=2, request_id="uncertain-scope")
    wait_state(harness.store, first, "unknown")
    wait_until(lambda: runner.status()["used"] == 2, "uncertain lease to retain two units")
    assert harness.store.get(first)["custody"] == "uncertain"
    assert runner.status(first).get("next_action")
    assert runner.status(first)["recovery"]["claim_held"] is True
    assert runner.await_run(first).get("next_action")
    assert "Do not resubmit" in runner.await_run(first)["next_action"]

    second = harness.submit(runner, ["fake", "clean"], weight=1, request_id="clean-scope")
    assert runner.await_run(second, timeout=10)["record"]["state"] == "settled"
    wait_until(lambda: runner.status()["used"] == 2, "only the uncertain lease to remain")
    assert pool.snapshot()["pool"]["held_units"] == 2


def test_restart_restores_exact_lease_for_unresolved_scope(harness):
    store = harness.store
    record = harness.record(store, "unresolved-restart", ["fake", "old"], "c1", "running",
                            units=2, started_at=time.time())
    store.put(record)
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    (latches / "unresolved-restart.json").write_text(
        json.dumps({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}))

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    class Scope:
        process = Process()

        def release(self):
            return Disposition("gone")

    for _ in range(2):
        runner = harness.runner(store=harness.new_store(), launch=lambda argv, **kw: Scope())
        assert runner.status()["used"] == 2
        assert runner.await_run("unresolved-restart")["record"]["custody"] == "uncertain"
        status = runner.status("unresolved-restart")
        assert status["recovery"] == {"scope_run_id": "unresolved-restart", "latch_present": True,
                                      "claim_run_id": "unresolved-restart", "claim_held": True,
                                      "claim_units": 2}
        assert "unresolved-restart" in status["next_action"]
        assert "claim held" in status["next_action"]
        assert "claim held" in runner.await_run("unresolved-restart")["next_action"]
        clean = harness.submit(runner, ["fake", "new"], weight=1)
        assert runner.await_run(clean, timeout=10)["record"]["state"] == "settled"
        assert runner.status()["used"] == 2
        harness.retire(runner)


def test_restart_does_not_restore_lease_after_latch_cleanup(harness, monkeypatch):
    store = harness.store
    record = harness.record(store, "cleaned-restart", ["fake", "old"], "c1", "unknown",
                            units=2, custody="uncertain", outcome="lost_in_restart")
    store.put(record)
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    latch = latches / "cleaned-restart.json"
    latch.write_text("unresolved")

    def cleanup(path, grace, census_fn):
        assert path == str(latch)
        latch.unlink()
        return Disposition("gone")

    monkeypatch.setattr("herzchen.fleet.runner.runner.custody.resume_cleanup", cleanup)
    first = harness.runner(store=harness.new_store())
    assert first.status()["used"] == 0 and not latch.exists()
    status = first.status("cleaned-restart")
    assert status["record"]["custody"] == "uncertain"
    assert status["recovery"] == {"scope_run_id": "cleaned-restart", "latch_present": False,
                                  "claim_run_id": "cleaned-restart", "claim_held": False,
                                  "claim_units": 0}
    assert "claim released" in status["next_action"]
    assert "keep its capacity claim held" not in status["next_action"]
    assert "claim released" in first.await_run("cleaned-restart")["next_action"]
    harness.retire(first)
    second = harness.runner(store=harness.new_store())
    assert second.status()["used"] == 0
    harness.retire(second)


@pytest.mark.parametrize("parent_evidence,claim_units", [("missing", 1), ("invalid", 2)])
def test_restart_retains_nested_claim_without_verifiable_parent(harness, parent_evidence, claim_units):
    store = harness.store
    parent_id = "lost-parent"
    if parent_evidence == "invalid":
        parent = harness.record(store, parent_id, ["fake", "parent"], "c1", "running",
                                units=2, started_at=time.time())
        store.put(parent)
        harness.write_raw(dict(parent, seal="invalid"))
    child_id = "live-child"
    store.put(harness.record(store, child_id, ["fake", "child"], "c1", "running",
                             units=0, weight_requested=1, nested_in=parent_id,
                             claim_run_id=parent_id, claim_units=claim_units,
                             started_at=time.time()))
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    if parent_evidence == "invalid":
        (latches / (parent_id + ".json")).write_text(
            json.dumps({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}))
    latch = latches / (child_id + ".json")
    leader = Custody.launch(gate_cmd(harness.tmp / "child-gate"), latch_path=str(latch),
                            cwd=str(harness.cwd), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        class Process:
            returncode = 0

            def wait(self, timeout=None):
                return 0

        class Scope:
            process = Process()

            def release(self):
                return Disposition("gone")

        pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
        runner = harness.runner(pool=pool, store=harness.new_store(), census_fn=lambda: None,
                                launch=lambda argv, **kw: Scope())
        assert latch.exists()
        assert runner.await_run(child_id)["record"]["custody"] == "uncertain"
        assert runner.status()["used"] == claim_units
        fitting = harness.submit(runner, ["fake", "fits"], weight=3 - claim_units,
                                 request_id="fitting-heavy")
        assert runner.await_run(fitting, timeout=10)["record"]["state"] == "settled"
        blocked = harness.submit(runner, QUICK, weight=3, request_id="other-heavy")
        assert store.get(blocked)["state"] == "queued"
        pool.ensure_turn("independent-turn")
        assert pool.snapshot()["turns"]["reserved"] == 1
        pool.release_turn("independent-turn")
    finally:
        try:
            os.killpg(leader.pgid, 9)
        except OSError:
            pass
        leader.process.wait()


def test_restart_retains_unmatched_unresolved_latch_claim(harness):
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    latch = latches / "unmatched-scope.json"
    leader = Custody.launch(gate_cmd(harness.tmp / "unmatched-gate"), latch_path=str(latch),
                            claim_run_id="unmatched-scope", claim_units=1,
                            cwd=str(harness.cwd), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        class Process:
            returncode = 0

            def wait(self, timeout=None):
                return 0

        class Scope:
            process = Process()

            def release(self):
                return Disposition("gone")

        pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
        runner = harness.runner(pool=pool, census_fn=lambda: None,
                                launch=lambda argv, **kw: Scope())
        assert latch.exists()
        assert json.loads(latch.read_text())["claim_units"] == 1
        assert runner.status()["used"] == 1
        fitting = harness.submit(runner, ["fake", "fits"], weight=2, request_id="fits-unmatched")
        assert runner.await_run(fitting, timeout=10)["record"]["state"] == "settled"
        blocked = harness.submit(runner, QUICK, weight=3, request_id="behind-unmatched")
        assert harness.store.get(blocked)["state"] == "queued"
        pool.ensure_turn("independent-turn")
        assert pool.snapshot()["turns"]["reserved"] == 1
        pool.release_turn("independent-turn")
    finally:
        try:
            os.killpg(leader.pgid, 9)
        except OSError:
            pass
        leader.process.wait()


def test_restart_legacy_nested_scope_without_claim_size_stays_conservative(harness):
    store = harness.store
    store.put(harness.record(store, "legacy-child", ["fake", "child"], "c1", "unknown",
                             units=0, nested_in="missing-parent", custody="uncertain"))
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    (latches / "legacy-child.json").write_text(
        json.dumps({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}))
    runner = harness.runner(store=harness.new_store())
    assert runner.status()["used"] == 3
    blocked = harness.submit(runner, QUICK, weight=1, request_id="behind-legacy")
    assert store.get(blocked)["state"] == "queued"


def test_restart_nested_scope_uses_verified_parent_claim(harness):
    store = harness.store
    store.put(harness.record(store, "verified-parent", ["fake", "parent"], "c1", "unknown",
                             units=2, outcome="lost_in_restart", custody="gone"))
    store.put(harness.record(store, "nested-child", ["fake", "child"], "c1", "unknown",
                             units=0, nested_in="verified-parent", outcome="lost_in_restart",
                             custody="uncertain"))
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    (latches / "nested-child.json").write_text(
        json.dumps({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}))

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    class Scope:
        process = Process()

        def release(self):
            return Disposition("gone")

    pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
    runner = harness.runner(pool=pool, store=harness.new_store(), launch=lambda argv, **kw: Scope())
    assert runner.status()["used"] == 2
    assert {holder["run_id"] for holder in runner.status()["holders"]} == {"verified-parent"}
    narrow = harness.submit(runner, ["fake", "narrow"], weight=1, request_id="narrow-beside-parent")
    assert runner.await_run(narrow, timeout=10)["record"]["state"] == "settled"
    wide = harness.submit(runner, ["fake", "wide"], weight=2, request_id="wide-behind-parent")
    assert store.get(wide)["state"] == "queued"
    pool.ensure_turn("independent-turn")
    assert pool.snapshot()["turns"]["reserved"] == 1
    pool.release_turn("independent-turn")


def test_legacy_grandchild_guidance_uses_held_root_claim(harness):
    store = harness.store
    store.put(harness.record(store, "root", ["fake", "root"], "c1", "unknown",
                             units=2, custody="gone", outcome="lost_in_restart"))
    store.put(harness.record(store, "child", ["fake", "child"], "c1", "unknown",
                             units=0, nested_in="root", custody="gone", outcome="lost_in_restart"))
    store.put(harness.record(store, "grandchild", ["fake", "grandchild"], "c1", "unknown",
                             units=0, nested_in="child", custody="uncertain", outcome="lost_in_restart"))
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    (latches / "grandchild.json").write_text(
        json.dumps({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}))

    runner = harness.runner(store=harness.new_store())
    assert runner.status()["used"] == 2
    recovery = runner.status("grandchild")["recovery"]
    assert recovery == {"scope_run_id": "grandchild", "latch_present": True,
                        "claim_run_id": "root", "claim_held": True, "claim_units": 2}
    assert "claim held for root" in runner.await_run("grandchild")["next_action"]


def test_restart_queued_record_with_unresolved_latch_is_not_relaunched(harness):
    store = harness.store
    store.put(harness.record(store, "queued-with-latch", ["fake", "old"], "c1", "queued",
                             units=2))
    latches = harness.state / "latches"
    latches.mkdir(exist_ok=True)
    latch = latches / "queued-with-latch.json"
    latch.write_text(json.dumps({"pgid": None, "leader_birth": None,
                                 "state": "launching", "members": {}}))
    launched = []
    runner = harness.runner(store=harness.new_store(), launch=lambda argv, **kw: launched.append(argv))
    assert store.get("queued-with-latch")["state"] == "unknown"
    assert store.get("queued-with-latch")["custody"] == "uncertain"
    assert runner.status()["used"] == 2
    assert latch.exists()
    assert launched == []


def test_peer_without_parent_credential_needs_own_lease(harness):
    gate = threading.Event()

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            assert gate.wait(10)
            return 0

    class Scope:
        process = Process()

        def observe(self, snap):
            return {4242: "peer-birth"}

        def release(self):
            return Disposition("gone")

        def terminate(self, grace):
            gate.set()
            return Disposition("gone")

    pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
    runner = harness.runner(pool=pool, launch=lambda argv, **kw: Scope(),
                            census_fn=lambda: {4242: Proc(4242, 11, 11, "peer-birth")})
    try:
        first = harness.submit(runner, ["fake", "parent"], weight=3, request_id="parent-scope")
        wait_until(lambda: first in runner._leases and runner._leases[first].custody is not None,
                   "parent custody to start")
        response = runner.submit({"argv": ["fake", "unrelated"], "cwd": str(harness.cwd),
                                  "request_id": "unrelated-peer"}, peer_pid=4242)
        assert response["ok"] and response["nested"] is False
        assert harness.store.get("unrelated-peer")["state"] == "queued"
        assert harness.store.get("unrelated-peer")["units"] == 1
        token = runner._leases[first].parent_token
        malformed = runner.submit({"argv": ["fake", "malformed"], "cwd": str(harness.cwd),
                                   "request_id": "malformed-peer", "parent_run_id": first,
                                   "parent_token": "\u00e9"}, peer_pid=4242)
        assert malformed["ok"] and malformed["nested"] is False
        assert harness.store.get("malformed-peer")["state"] == "queued"
        linked = runner.submit({"argv": ["fake", "linked"], "cwd": str(harness.cwd),
                                "request_id": "linked-peer", "parent_run_id": first,
                                "parent_token": token}, peer_pid=4242)
        assert linked["ok"] and linked["nested"] is True
        assert harness.store.get("linked-peer")["units"] == 0
        assert harness.store.get("linked-peer")["claim_run_id"] == first
        assert harness.store.get("linked-peer")["claim_units"] == 3
        gate.set()
        wait_until(lambda: first not in runner._leases, "parent lease to finish")
        stale = runner.submit({"argv": ["fake", "stale"], "cwd": str(harness.cwd),
                               "request_id": "stale-peer", "parent_run_id": first,
                               "parent_token": token}, peer_pid=4242)
        assert stale["ok"] and stale["nested"] is False
        assert harness.store.get("stale-peer")["units"] == 1
    finally:
        gate.set()


def test_immediate_child_waits_for_parent_launch_identity(harness):
    gate = threading.Event()
    entered = threading.Event()
    child_response = {}

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            assert gate.wait(10)
            return 0

    class Scope:
        process = Process()

        def release(self):
            return Disposition("gone")

        def terminate(self, grace):
            gate.set()
            return Disposition("gone")

    runner = None

    def launch(argv, **kwargs):
        if argv[-1] == "parent":
            env = kwargs["env"]

            def child():
                child_response.update(runner.submit(
                    {"argv": ["fake", "child"], "cwd": str(harness.cwd), "request_id": "immediate-child",
                     "parent_run_id": env["RUNNER_PARENT_RUN_ID"],
                     "parent_token": env["RUNNER_PARENT_TOKEN"]}, peer_pid=4242))

            threading.Thread(target=child, daemon=True).start()
            assert entered.wait(5)
        return Scope()

    runner = harness.runner(launch=launch)
    original = runner._parent_lease

    def observed(request):
        if request.get("request_id") == "immediate-child":
            entered.set()
        return original(request)

    runner._parent_lease = observed
    try:
        harness.submit(runner, ["fake", "parent"], weight=3, request_id="immediate-parent")
        wait_until(lambda: child_response, "immediate child submit response")
        assert child_response["ok"] and child_response["nested"] is True
        assert harness.store.get("immediate-child")["units"] == 0
    finally:
        gate.set()


def test_git_commit_identity_clean_dirty_and_not_a_repo(harness):
    repo = harness.tmp / "repo"
    head = make_repo(repo)
    assert re.fullmatch(r"[0-9a-f]{40}", head)
    assert git_commit_identity(str(repo)) == head
    (repo / "a.txt").write_text("two\n")
    dirty = git_commit_identity(str(repo))
    assert re.fullmatch(head + r"\+dirty-[0-9a-f]{16}", dirty), dirty
    assert git_commit_identity(str(repo)) == dirty            # deterministic for the same tree
    (repo / "a.txt").write_text("three\n")
    assert git_commit_identity(str(repo)) not in (dirty, head)
    (repo / "b.txt").write_text("untracked\n")                # untracked files count
    with_untracked = git_commit_identity(str(repo))
    assert re.fullmatch(head + r"\+dirty-[0-9a-f]{16}", with_untracked)
    (repo / "b.txt").unlink()
    (repo / "a.txt").write_text("one\n")
    assert git_commit_identity(str(repo)) == head              # clean again

    plain = harness.tmp / "plain"
    plain.mkdir()
    assert git_commit_identity(str(plain)) is None
    empty = harness.tmp / "no-commit"
    empty.mkdir()
    git(empty, "init", "-q")
    assert git_commit_identity(str(empty)) is None


def test_tree_change_before_launch_settles_stale(harness):
    repo = harness.tmp / "repo"
    head = make_repo(repo)
    runner = harness.runner(resolve=git_commit_identity)
    store = harness.store
    gate = harness.tmp / "gate-holder"
    holder = harness.submit(runner, gate_cmd(gate), cwd=repo, weight=3, request_id="holder")
    wait_state(store, holder, "running")                       # the holder resolved the commit at launch
    counter = harness.tmp / "stale-run-counter"
    q = harness.submit(runner, [PY, "-c", COUNT_CODE, str(counter)], cwd=repo, weight=1, request_id="stale-q")
    assert store.get(q)["state"] == "queued" and store.get(q)["commit"] == head
    (repo / "a.txt").write_text("changed\n")                  # the tree moves before q can launch
    gate.touch()
    wait_state(store, q, "unknown")
    rec = store.get(q)
    assert rec["outcome"] == "stale_commit" and rec["exit_code"] is None
    assert not counter.exists()                               # never ran
    assert runner.await_run(q, timeout=10)["exit_code"] == EXIT_UNKNOWN


# -- 5. report totals equal the stored results -----------------------------------------------------

def test_report_totals_equal_results(harness):
    runner, store = harness.runner(), harness.store
    specs = [
        ("u-a1", "alpha", [PY, "-c", USAGE_CODE, "7", "0.05"]),
        ("p-a2", "alpha", [PY, "-c", "import sys; sys.exit(2)"]),
        ("u-b1", "beta", [PY, "-c", USAGE_CODE, "11", "0.1"]),
        ("p-b2", "beta", [PY, "-c", "import time\ntime.sleep(0.2)"]),
    ]
    for rid, task, argv in specs:
        harness.submit(runner, argv, request_id=rid, task=task)
    for rid, _, _ in specs:
        wait_state(store, rid, "settled")
    harness.write_raw(harness.record(store, "forged-r", QUICK, "c1", "settled", task="alpha", tokens=1000,
                                     exit_code=0, outcome="exited", seconds=99.0, unit_seconds=99.0,
                                     seal="cd" * 32))

    rep = runner.report()
    verified, invalid = store.all_records()
    assert invalid == ["forged-r"] and rep["invalid"] == ["forged-r"]
    assert len(verified) == 4
    totals = rep["totals"]
    assert totals["runs"] == 4 and totals["settled"] == 4 and totals["unknown"] == 0
    assert totals["tokens"] == 18 == sum(r["tokens"] for r in verified)
    assert totals["seconds"] == pytest.approx(sum(r["seconds"] for r in verified), abs=1e-6)
    assert totals["unit_seconds"] == pytest.approx(sum(r["unit_seconds"] for r in verified), abs=1e-6)
    tasks = rep["tasks"]
    assert set(tasks) == {"alpha", "beta"}
    assert tasks["alpha"]["runs"] == 2 and tasks["beta"]["runs"] == 2
    assert tasks["alpha"]["tokens"] == 7 and tasks["beta"]["tokens"] == 11
    for field in ("runs", "settled", "unknown", "tokens"):
        assert sum(tasks[t][field] for t in tasks) == totals[field], field
    for field in ("seconds", "unit_seconds"):
        assert sum(tasks[t][field] for t in tasks) == pytest.approx(totals[field], abs=1e-6), field


# -- 6. nested and standalone runs are counted once under a full pool (ASTRA0) ---------------------

@pytest.mark.parametrize("mode", ["direct", "setsid"])
def test_nested_and_standalone_counted_once_under_full_pool(harness, mode):
    pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
    runner, store = harness.runner(pool=pool), harness.store
    client = harness.serve(runner)
    scripts = harness.scripts()
    gate = harness.tmp / "gate-parent"
    marker = harness.tmp / "nested.marker"
    out = harness.tmp / "nested.json"
    done = Path(str(out) + ".done")
    harness.submit(runner, [PY, scripts["parent"], harness.sock, str(harness.cwd), str(marker), str(out),
                            str(gate), mode], weight=3, request_id="parent-1", task="parent")
    wait_state(store, "parent-1", "running")
    harness.submit(runner, QUICK, weight=1, request_id="standalone-1", task="standalone")
    assert store.get("standalone-1")["state"] == "queued"      # the pool is full

    wait_until(lambda: done.exists(), "the nested run to complete under the parent")
    assert marker.read_text() == "nested"
    assert store.get("parent-1")["state"] == "running"         # the parent still holds all 3 units
    assert pool.snapshot()["pool"]["held_units"] == 3
    assert store.get("standalone-1")["state"] == "queued"
    nested = [r for r in store.all_records()[0] if r["nested_in"] == "parent-1"]
    assert len(nested) == 1
    assert nested[0]["units"] == 0 and nested[0]["unit_seconds"] == 0.0
    assert nested[0]["state"] == "settled" and nested[0]["exit_code"] == 4

    gate.touch()
    assert runner.await_run("parent-1", timeout=10)["exit_code"] == 4
    assert runner.await_run("standalone-1", timeout=10)["exit_code"] == 0
    assert store.get("standalone-1")["started_at"] >= store.get("parent-1")["settled_at"]
    wait_until(lambda: pool.snapshot()["pool"]["held_units"] == 0, "the pool to be released")
    ledger = pool.snapshot()["pool"]
    assert ledger["cumulative_used_units"] == 3 + 1
    assert ledger["held_units"] == 0

    rep = runner.report()
    assert rep["totals"]["runs"] == 3
    p, s = store.get("parent-1"), store.get("standalone-1")
    assert rep["totals"]["unit_seconds"] == pytest.approx(p["unit_seconds"] + s["unit_seconds"], abs=1e-6)


def test_env_bypass_is_not_nested(harness):
    pool = CapacityPool(CapacityPolicy(heavy_headroom=3))
    runner, store = harness.runner(pool=pool), harness.store
    harness.serve(runner)
    scripts = harness.scripts()
    gate = harness.tmp / "gate-full"
    full = harness.submit(runner, gate_cmd(gate), weight=3, request_id="full-1")
    wait_state(store, full, "running")

    marker = harness.tmp / "bypass.marker"
    out = harness.tmp / "bypass.json"
    env = dict(ENV, OTTO_HEAVY_LEASE="anything", RUNNER_LEASE="anything")
    proc = harness.popen([PY, scripts["client"], harness.sock, str(harness.cwd), str(marker), str(out)], env=env)
    resp = wait_until(lambda: json.loads(out.read_text()) if out.exists() else None, "the bypass submit response")
    assert resp["ok"] is True and resp["nested"] is False, resp
    run_id = resp["run_id"]
    assert store.get(run_id)["state"] == "queued"              # not nested, not started
    assert store.get(run_id)["started_at"] is None
    assert not marker.exists()

    gate.touch()                                               # the lease ends; the check is admitted on its own units
    assert proc.wait(timeout=10) == 4
    rec = store.get(run_id)
    assert rec["state"] == "settled" and rec["nested_in"] is None
    assert rec["units"] == 1 and rec["exit_code"] == 4
    assert marker.read_text() == "nested"

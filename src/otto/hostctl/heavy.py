"""ottoctl heavy: one heavy job at a time on this machine.

Renders, real-film journeys and full test suites take the machine's single heavy lease:

    ottoctl heavy [--purpose TEXT] [--max-minutes N] [--no-wait] -- CMD [ARGS...]
    ottoctl heavy status

The lease is an exclusive ``flock`` on ``<dir>/heavy.lock`` (``$OTTO_HEAVY_DIR``, default
``~/.local/state/otto``) plus ``<dir>/heavy.json`` naming the holder. The kernel releases the lock
when the holder dies, so a lease can't go stale.

CMD runs in its own session with ``OTTO_HEAVY_LEASE=<id>`` in its environment. When it ends, fails,
is interrupted or runs out of time, everything still carrying the lease is stopped: its process
group, and any process that left the group (``setsid``, a detached browser) but still carries the
lease id in its environment. Nothing else is ever signalled. A lease whose holder died leaves its
id in heavy.json; the next lease stops that id's leftovers before it starts.

Exit codes: CMD's own; 75 busy (with --no-wait); 124 time ran out; 130/143 interrupted.
Every lease appends one JSON line (who, what, how long, machine state before and after, reaped
leftovers) to ``<dir>/heavy.log``.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
import uuid

LEASE_ENV = "OTTO_HEAVY_LEASE"
EXIT_BUSY, EXIT_TIMEOUT = 75, 124
GRACE_SECONDS = 5.0
LOG_KEEP_LINES = 500


def state_dir() -> Path:
    path = Path(os.environ.get("OTTO_HEAVY_DIR") or Path.home() / ".local" / "state" / "otto")
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_state() -> dict:
    """Load, swap and free disk, recorded beside every heavy job's timing."""
    state: dict = {"load_1m": round(os.getloadavg()[0], 2),
                   "free_disk_gb": round(shutil.disk_usage("/").free / 1e9, 1)}
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5).stdout
            fields = dict(part.split(" = ") for part in out.strip().split("  ") if " = " in part)
            state["swap_used_mb"] = float(fields.get("used", "0M").rstrip("M"))
            state["swap_total_mb"] = float(fields.get("total", "0M").rstrip("M"))
        else:
            info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
            total = int(info["SwapTotal"].split()[0]) / 1024
            state["swap_used_mb"] = round(total - int(info["SwapFree"].split()[0]) / 1024)
            state["swap_total_mb"] = round(total)
    except Exception:  # noqa: BLE001 - the state is evidence, never a reason to fail the job
        pass
    return state


def tagged_pids(lease_id: str) -> list[int] | None:
    """Pids whose environment carries this lease (None: this host can't list environments)."""
    marker = f"{LEASE_ENV}={lease_id}"
    me = os.getpid()
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["ps", "-axwwE", "-o", "pid=,command="], capture_output=True, text=True,
                                 timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        pids = []
        for line in out.splitlines():
            if marker in line:
                pid = int(line.split(None, 1)[0])
                if pid != me:
                    pids.append(pid)
        return pids
    pids = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if entry.isdigit() and int(entry) != me:
            try:
                if marker.encode() in Path("/proc", entry, "environ").read_bytes().split(b"\0"):
                    pids.append(int(entry))
            except OSError:
                continue
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_lease(lease_id: str, pgid: int | None) -> dict:
    """Stop the lease's group and every process still carrying its id: TERM (+CONT), grace, KILL."""
    def targets() -> set[int]:
        found = set(tagged_pids(lease_id) or [])
        return {pid for pid in found if _alive(pid)}

    def signal_all(sig: int) -> None:
        if pgid:
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        for pid in targets():
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    before = targets()
    group_alive = bool(pgid) and _group_alive(pgid)
    if not before and not group_alive:
        return {"reaped": [], "sweep": "complete" if tagged_pids(lease_id) is not None else "unavailable"}
    signal_all(signal.SIGTERM)
    signal_all(signal.SIGCONT)  # a stopped process only acts on TERM once continued
    deadline = time.monotonic() + GRACE_SECONDS
    while time.monotonic() < deadline and (targets() or (pgid and _group_alive(pgid))):
        time.sleep(0.2)
    killed = sorted(targets())
    if killed or (pgid and _group_alive(pgid)):
        signal_all(signal.SIGKILL)
        time.sleep(0.2)
    return {"reaped": sorted(before), "needed_kill": killed,
            "remaining": sorted(targets()), "sweep": "complete" if tagged_pids(lease_id) is not None else "unavailable"}


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_holder(directory: Path) -> dict | None:
    try:
        return json.loads((directory / "heavy.json").read_text())
    except (OSError, ValueError):
        return None


def _append_log(directory: Path, record: dict) -> None:
    path = directory / "heavy.log"
    lines = path.read_text().splitlines() if path.exists() else []
    lines.append(json.dumps(record, sort_keys=True))
    path.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n")


def status() -> dict:
    directory = state_dir()
    with open(directory / "heavy.lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            return {"lease": "held", "holder": _read_holder(directory), "machine": machine_state()}
        fcntl.flock(lock, fcntl.LOCK_UN)
    return {"lease": "free", "machine": machine_state()}


def run(command: list[str], *, purpose: str, max_minutes: float, wait: bool, owner: str) -> int:
    if os.environ.get(LEASE_ENV):
        # Already inside a heavy job (e.g. a journey that renders): it holds the lease; run straight through.
        return subprocess.call(command)
    directory = state_dir()
    lock = open(directory / "heavy.lock", "a+")
    announced = False
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            holder = _read_holder(directory) or {}
            if not wait:
                print(f"heavy: busy, held by {holder.get('owner', '?')} for {holder.get('purpose', '?')} "
                      f"since {holder.get('started_at', '?')}", file=sys.stderr)
                return EXIT_BUSY
            if not announced:
                print(f"heavy: waiting for the lease held by {holder.get('owner', '?')} "
                      f"({holder.get('purpose', '?')}, since {holder.get('started_at', '?')})", file=sys.stderr)
                announced = True
            time.sleep(2)

    # A previous holder that died keeps its id here: stop its leftovers before we start.
    previous = _read_holder(directory)
    inherited = None
    if previous and previous.get("lease_id"):
        inherited = stop_lease(previous["lease_id"], previous.get("pgid"))
        if inherited.get("reaped"):
            print(f"heavy: stopped {len(inherited['reaped'])} leftovers of {previous.get('owner')}'s "
                  f"lease ({previous.get('purpose')})", file=sys.stderr)

    lease_id = uuid.uuid4().hex[:12]
    started = time.time()
    before = machine_state()
    env = dict(os.environ, **{LEASE_ENV: lease_id})
    child = subprocess.Popen(command, env=env, start_new_session=True)
    record = {"lease_id": lease_id, "owner": owner, "purpose": purpose, "pid": child.pid, "pgid": child.pid,
              "holder_pid": os.getpid(), "command": command,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
              "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started + max_minutes * 60)),
              "machine_before": before}
    (directory / "heavy.json").write_text(json.dumps(record, indent=1))

    outcome, code = "exited", None
    stop_signal: list[int] = []

    def on_signal(signum, _frame):
        stop_signal.append(signum)
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    previous_handlers = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            code = child.wait(timeout=max_minutes * 60)
        except subprocess.TimeoutExpired:
            outcome, code = "timed_out", EXIT_TIMEOUT
            print(f"heavy: time ran out after {max_minutes:g} min; stopping the lease's processes", file=sys.stderr)
        if stop_signal:
            outcome = "interrupted"
            code = 128 + stop_signal[0]
    finally:
        sweep = stop_lease(lease_id, child.pid)
        try:
            child.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if sweep.get("reaped"):
            print(f"heavy: stopped {len(sweep['reaped'])} leftover process(es) of this lease", file=sys.stderr)
        _append_log(directory, {**record, "outcome": outcome, "exit_code": code,
                                "seconds": round(time.time() - started, 1), "machine_after": machine_state(),
                                "leftovers": sweep, "inherited_leftovers": inherited})
        (directory / "heavy.json").write_text(json.dumps({**record, "lease_id": None, "released_at":
                                                          time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return code if code is not None else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["status"]:
        print(json.dumps(status(), indent=1))
        return 0
    if "--" not in argv:
        print("usage: ottoctl heavy [--purpose TEXT] [--max-minutes N] [--no-wait] -- CMD [ARGS...]\n"
              "       ottoctl heavy status", file=sys.stderr)
        return 2
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="ottoctl heavy", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--purpose", help="what this heavy job is for (shown to whoever waits)")
    parser.add_argument("--max-minutes", type=float, default=60.0, help="stop everything after this long (default 60)")
    parser.add_argument("--no-wait", action="store_true", help="exit 75 instead of waiting when the lease is held")
    parser.add_argument("--owner", default=os.environ.get("OTTO_HEAVY_OWNER")
                        or f"{os.environ.get('USER', '?')} pid {os.getppid()} in {os.getcwd()}",
                        help="who holds the lease (default $OTTO_HEAVY_OWNER, or the caller's pid and directory)")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    if not command:
        parser.error("no command after --")
    return run(command, purpose=args.purpose or " ".join(command)[:120], max_minutes=args.max_minutes,
               wait=not args.no_wait, owner=args.owner)


if __name__ == "__main__":
    raise SystemExit(main())

"""ottoctl heavy: many agents share the machine's heavy capacity, and nothing a job started outlives it.

Heavy jobs (frame captures, renders, real-film journeys, full test suites) take slots from the
machine's capacity; light work (edits, checks, show) takes none:

    ottoctl heavy [--weight N] [--purpose TEXT] [--max-minutes N] [--no-deadline] [--no-wait] -- CMD [ARGS...]
    ottoctl heavy status

**Capacity** is a number of slots: ``$OTTO_HEAVY_CAPACITY``, else ``<dir>/capacity``, else one slot
per 2 GB of physical memory (4 on an 8 GB Mac). A job takes ``--weight`` slots (default 1). A guide
for this machine: a frame or visualize call 1, a real-film journey or full test suite 2, a
full-film render 3. Jobs run concurrently while slots remain. Each waiter takes a ticket in
``waiting/``; the earliest live ticket is the head, so a big job isn't starved by a stream of small
ones. While the head waits for more slots than are free, the earliest ticket behind it that fits may
take free slots, but only while the head could still start beside every such job: it never delays it. While the OS reports **critical** memory pressure, a new
job waits for a running one to finish instead of piling on (it never waits on an otherwise idle
machine).

**State:** ``$OTTO_HEAVY_DIR``, default ``~/.local/state/otto``. Each slot is an ``flock`` on
``slots/<i>.lock``, so the kernel frees it when its holder dies. Each lease names itself in
``holders/<id>.json`` (marked ``backfill`` if it took slots ahead of the head).

**Cleanup:** CMD runs in its own session with ``OTTO_HEAVY_LEASE=<id>`` in its environment. When it
ends, fails, is interrupted or runs out of time, the lease stops its process group and every process
still carrying that id: ones that left the group (``setsid``, a detached browser) and paused ones,
with TERM + CONT, a grace period, then KILL. Nothing without the id is ever signalled. A lease whose
holder died is cleaned up by the next lease to start.

Exit codes: CMD's own; 75 no capacity (with --no-wait); 124 time ran out; 130/143 interrupted.
Every lease appends one JSON line to ``<dir>/heavy.log``: who, what, weight, waited, ran, and the
machine state (load, swap, memory pressure, free disk) before and after.
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
POLL_SECONDS = 1.0
LOG_KEEP_LINES = 2000
PRESSURE_CRITICAL = 4  # kern.memorystatus_vm_pressure_level: 1 normal, 2 warn, 4 critical


def state_dir() -> Path:
    path = Path(os.environ.get("OTTO_HEAVY_DIR") or Path.home() / ".local" / "state" / "otto")
    for sub in ("slots", "holders", "waiting"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    return path


def capacity(directory: Path) -> int:
    configured = os.environ.get("OTTO_HEAVY_CAPACITY")
    if not configured and (directory / "capacity").exists():
        configured = (directory / "capacity").read_text().strip()
    if configured:
        return max(1, int(configured))
    try:
        if platform.system() == "Darwin":
            mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                     timeout=5).stdout)
        else:
            mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return max(1, mem // (2 * 1024 ** 3))
    except Exception:  # noqa: BLE001
        return 2


def memory_pressure() -> int | None:
    if platform.system() != "Darwin":
        return None
    try:
        return int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                                  capture_output=True, text=True, timeout=5).stdout)
    except Exception:  # noqa: BLE001
        return None


def machine_state() -> dict:
    """Load, swap, memory pressure and free disk, recorded beside every heavy job's timing."""
    state: dict = {"load_1m": round(os.getloadavg()[0], 2),
                   "free_disk_gb": round(shutil.disk_usage("/").free / 1e9, 1)}
    pressure = memory_pressure()
    if pressure is not None:
        state["memory_pressure"] = {1: "normal", 2: "warn", 4: "critical"}.get(pressure, str(pressure))
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
        return [int(line.split(None, 1)[0]) for line in out.splitlines()
                if marker in line and int(line.split(None, 1)[0]) != me]
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


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_lease(lease_id: str, pgid: int | None) -> dict:
    """Stop the lease's group and every process still carrying its id: TERM (+CONT), grace, KILL."""
    def targets() -> set[int]:
        return {pid for pid in (tagged_pids(lease_id) or []) if _alive(pid)}

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

    sweep = "complete" if tagged_pids(lease_id) is not None else "unavailable"
    before = targets()
    if not before and not (pgid and _group_alive(pgid)):
        return {"reaped": [], "sweep": sweep}
    signal_all(signal.SIGTERM)
    signal_all(signal.SIGCONT)  # a stopped process only acts on TERM once continued
    deadline = time.monotonic() + GRACE_SECONDS
    while time.monotonic() < deadline and (targets() or (pgid and _group_alive(pgid))):
        time.sleep(0.2)
    killed = sorted(targets())
    if killed or (pgid and _group_alive(pgid)):
        signal_all(signal.SIGKILL)
        time.sleep(0.2)
    return {"reaped": sorted(before), "needed_kill": killed, "remaining": sorted(targets()), "sweep": sweep}


def _holders(directory: Path) -> list[dict]:
    out = []
    for path in sorted((directory / "holders").glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out


def _reap_dead_holders(directory: Path) -> list[dict]:
    """Leases whose holder process died: stop what they left behind and drop their record."""
    cleaned = []
    for holder in _holders(directory):
        if holder.get("holder_pid") and not _alive(int(holder["holder_pid"])):
            result = stop_lease(holder["lease_id"], holder.get("pgid"))
            (directory / "holders" / f"{holder['lease_id']}.json").unlink(missing_ok=True)
            cleaned.append({"owner": holder.get("owner"), "purpose": holder.get("purpose"), **result})
    return cleaned


def _try_slots(directory: Path, cap: int, weight: int) -> list | None:
    """Take `weight` free slots now, or none (all-or-nothing)."""
    taken = []
    for index in range(cap):
        handle = open(directory / "slots" / f"{index}.lock", "a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            continue
        taken.append(handle)
        if len(taken) == weight:
            return taken
    for handle in taken:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
    return None


def _waiting(directory: Path) -> list[dict]:
    """Live tickets in arrival order. A waiter holds an flock on its ticket, so the kernel frees it on
    death: a ticket we can lock is dead (never judged by pid, which the machine reuses) and is dropped."""
    out = []
    for path in sorted((directory / "waiting").glob("*.json")):
        try:
            with open(path) as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                        raise
                    out.append({**json.loads(handle.read()), "ticket": path.name})
                    continue
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            continue
    return out


def _take(directory: Path, cap: int, weight: int, ticket: str, blocked: bool, claim) -> tuple:
    """Take slots if it is this ticket's turn: (slots or None, tickets ahead, running holders).

    Whoever holds the earliest ticket is the head and starts when its weight fits. Others may backfill
    only while the head can't start, in arrival order, and backfilled jobs together never take more
    than ``cap - head weight``, so the head never waits longer because of them. ``claim`` records the
    holder under the same guard, so two waiters can never count the same room.
    """
    with open(directory / "admit.lock", "a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        queue = _waiting(directory)
        ahead = next((i for i, t in enumerate(queue) if t["ticket"] == ticket), None)
        running = [h for h in _holders(directory) if _alive(int(h.get("holder_pid") or 0))]
        if ahead is None or (blocked and running):
            return None, ahead or 0, running
        backfill = ahead > 0
        if backfill:
            head = int(queue[0].get("weight", cap))
            if cap - sum(int(h.get("weight", 1)) for h in running) >= head:
                return None, ahead, running  # the head can start now; it goes first
            room = cap - head - sum(int(h.get("weight", 1)) for h in running if h.get("backfill"))
            first = next((t for t in queue[1:] if int(t.get("weight", 1)) <= room), None)
            if not first or first["ticket"] != ticket:
                return None, ahead, running
        slots = _try_slots(directory, cap, weight)
        if slots:
            claim(backfill)
        return slots, ahead, running


def _append_log(directory: Path, record: dict) -> None:
    path = directory / "heavy.log"
    with open(directory / "log.lock", "a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        lines = path.read_text().splitlines() if path.exists() else []
        lines.append(json.dumps(record, sort_keys=True))
        path.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n")


def status() -> dict:
    directory = state_dir()
    cap = capacity(directory)
    holders = [h for h in _holders(directory) if _alive(int(h.get("holder_pid") or 0))]
    used = sum(int(h.get("weight", 1)) for h in holders)
    return {"capacity": cap, "used": used, "free": max(0, cap - used),
            "holders": [{k: h.get(k) for k in ("owner", "purpose", "weight", "started_at", "expires_at")}
                        for h in holders],
            "waiting": [{"purpose": t.get("purpose"), "weight": t.get("weight"),
                         "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t.get("queued_at", 0)))}
                        for t in _waiting(directory)],
            "machine": machine_state()}


def _describe(holders: list[dict]) -> str:
    return "; ".join(f"{h.get('owner', '?')}: {h.get('purpose', '?')} (weight {h.get('weight', 1)}, since "
                     f"{h.get('started_at', '?')})" for h in holders) or "nobody (memory pressure)"


def run(command: list[str], *, weight: int, purpose: str, max_minutes: float | None, wait: bool, owner: str) -> int:
    if os.environ.get(LEASE_ENV):
        # Already inside a heavy job (e.g. a journey that renders frames): it holds slots; run straight through.
        return subprocess.call(command)
    directory = state_dir()
    cap = capacity(directory)
    weight = max(1, min(weight, cap))
    inherited = _reap_dead_holders(directory)
    for item in inherited:
        if item.get("reaped"):
            print(f"heavy: stopped {len(item['reaped'])} leftovers of {item.get('owner')}'s dead lease "
                  f"({item.get('purpose')})", file=sys.stderr)

    # Queue in arrival order: a ticket per waiter; the earliest live ticket is the head (see _take).
    queued_at = time.time()
    ticket = directory / "waiting" / f"{time.time_ns()}-{os.getpid()}.json"
    mine = open(ticket.with_suffix(".tmp"), "w")  # locked before it is visible; held until we start or exit
    fcntl.flock(mine, fcntl.LOCK_EX)
    mine.write(json.dumps({"weight": weight, "purpose": purpose, "queued_at": queued_at}))
    mine.flush()
    os.replace(ticket.with_suffix(".tmp"), ticket)
    lease_id = uuid.uuid4().hex[:12]
    record = {"lease_id": lease_id, "owner": owner, "purpose": purpose, "weight": weight, "capacity": cap,
              "holder_pid": os.getpid(), "command": command}
    holder_file = directory / "holders" / f"{lease_id}.json"

    def claim(backfill: bool) -> None:
        now = time.time()
        record.update(backfill=backfill, admitted_ns=time.time_ns(), waited_seconds=round(now - queued_at, 1),
                      started_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)))
        if max_minutes is not None:
            record["expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + max_minutes * 60))
        holder_file.write_text(json.dumps(record, indent=1))
        ticket.unlink(missing_ok=True)

    handlers = {sig: signal.signal(sig, lambda signum, _f: sys.exit(128 + signum))
                for sig in (signal.SIGINT, signal.SIGTERM)}
    announced = False
    try:
        while True:
            blocked = memory_pressure() == PRESSURE_CRITICAL
            slots, ahead, running = _take(directory, cap, weight, ticket.name, blocked, claim)
            if slots:
                if record["backfill"]:
                    print("heavy: running in free slots the waiting job ahead can't use", file=sys.stderr)
                break
            if not wait:
                print(f"heavy: no capacity now ({cap} slots; running: {_describe(running)})", file=sys.stderr)
                return EXIT_BUSY
            if not announced:
                what = (f"waiting for {weight} slot(s), "
                        + ("memory pressure is critical" if blocked else f"all {cap} slots in use") if not ahead
                        else f"queued behind {ahead} waiting job(s)")
                print(f"heavy: {what}; running: {_describe(running)}", file=sys.stderr)
                announced = True
            _reap_dead_holders(directory)
            time.sleep(POLL_SECONDS)
    finally:
        ticket.unlink(missing_ok=True)
        mine.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)

    started = record["admitted_ns"] / 1e9
    record["machine_before"] = machine_state()
    env = dict(os.environ, **{LEASE_ENV: lease_id})
    child = subprocess.Popen(command, env=env, start_new_session=True)
    record.update(pid=child.pid, pgid=child.pid)
    holder_file.write_text(json.dumps(record, indent=1))

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
            if max_minutes is None:
                code = child.wait()
            else:
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
        holder_file.unlink(missing_ok=True)
        for handle in slots or []:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
    return code if code is not None else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["status"]:
        print(json.dumps(status(), indent=1))
        return 0
    if "--" not in argv:
        print("usage: ottoctl heavy [--weight N] [--purpose TEXT] [--max-minutes N] [--no-deadline] [--no-wait] -- CMD [ARGS...]\n"
              "       ottoctl heavy status", file=sys.stderr)
        return 2
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="ottoctl heavy", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weight", type=int, default=1,
                        help="slots this job takes (frame 1, journey or test suite 2, full render 3)")
    parser.add_argument("--purpose", help="what this heavy job is for (shown to whoever waits)")
    parser.add_argument("--max-minutes", type=float, default=60.0, help="stop everything after this long (default 60)")
    parser.add_argument("--no-deadline", action="store_true", help="run until the command exits or is interrupted")
    parser.add_argument("--no-wait", action="store_true", help="exit 75 instead of waiting when there's no capacity")
    parser.add_argument("--owner", default=os.environ.get("OTTO_HEAVY_OWNER")
                        or f"{os.environ.get('USER', '?')} pid {os.getppid()} in {os.getcwd()}",
                        help="who holds the lease (default $OTTO_HEAVY_OWNER, or the caller's pid and directory)")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    if not command:
        parser.error("no command after --")
    return run(command, weight=args.weight, purpose=args.purpose or " ".join(command)[:120],
               max_minutes=None if args.no_deadline else args.max_minutes,
               wait=not args.no_wait, owner=args.owner)


if __name__ == "__main__":
    raise SystemExit(main())

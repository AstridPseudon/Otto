"""ottoctl heavy: many agents share the machine's heavy capacity with recorded process custody.

Heavy jobs (frame captures, renders, real-film journeys, full test suites) take slots from the
machine's capacity; light work (edits, checks, show) takes none:

    ottoctl heavy [--weight N] [--purpose TEXT] [--max-minutes N] [--no-wait] -- CMD [ARGS...]
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

**Cleanup:** CMD runs in a private session. Its group and observed descendants are recorded with
process birth identities in the holder record. TERM + CONT, a grace period, then KILL apply only to
verified members of that lease. An unresolved dead holder keeps its capacity claim until recovery
can verify that its processes are gone. ``OTTO_HEAVY_LEASE`` only lets nested heavy calls reuse slots.
An arbitrary child that forks, leaves the group, and is reparented entirely between observations
cannot be attributed by portable process-table APIs. Such commands need cooperative custody or
kernel containment to guarantee cleanup; the lease never signals a process based on its environment.

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
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

from otto.portfolio.native_caller_ingress import process_identity

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


def _birth_at(pid: int, ppid: int, pgid: int) -> list[int] | None:
    """Join the ancestry snapshot to the same live kernel process occurrence."""
    try:
        identity = process_identity(pid)
        if identity.parent == ppid and os.getpgid(pid) == pgid:
            return list(identity.birth)
    except (OSError, PermissionError):
        pass
    return None


def _processes() -> dict[int, dict] | None:
    """One ancestry snapshot, with exact kernel birth identity for signal authority."""
    if Path("/proc").is_dir():
        processes = {}
        try:
            entries = os.listdir("/proc")
        except OSError:
            return None
        for entry in entries:
            if not entry.isdigit():
                continue
            try:
                stat = Path("/proc", entry, "stat").read_text().rsplit(") ", 1)[1].split()
                if stat[0] != "Z":
                    processes[int(entry)] = {"ppid": int(stat[1]), "pgid": int(stat[2]),
                                             "birth": None}
            except (OSError, IndexError, ValueError):
                # The PID was in the complete /proc listing. An unreadable stat is
                # uncertain for a tracked process, not proof that it disappeared.
                processes[int(entry)] = {"ppid": None, "pgid": None, "birth": None}
        for pid, info in processes.items():
            if info["ppid"] is not None:
                info["birth"] = _birth_at(pid, info["ppid"], info["pgid"])
        return processes
    try:
        result = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    processes = {}
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+)", line)
        if match and not match[4].startswith("Z"):
            pid = int(match[1])
            ppid, pgid = int(match[2]), int(match[3])
            processes[pid] = {"ppid": ppid, "pgid": pgid,
                              "birth": _birth_at(pid, ppid, pgid)}
    return processes


def _observe(record: dict, processes: dict[int, dict], *, seed_root: bool = False) -> bool:
    """Add descendants reached through an already verified process, including new private groups."""
    known = record.setdefault("processes", {})
    root = int(record.get("pid") or 0)
    changed = False
    if seed_root and root in processes and processes[root]["birth"] is not None and str(root) not in known:
        known[str(root)] = {"birth": processes[root]["birth"], "pgid": processes[root]["pgid"]}
        changed = True
    pending = set(record.get("unidentified", []))
    present = pending & processes.keys()
    if present != pending:
        changed = True
    pending = present
    while True:
        live = {int(pid) for pid, identity in known.items()
                if int(pid) in processes and processes[int(pid)]["birth"] == identity["birth"]}
        group_anchored = any(processes[pid]["pgid"] == record.get("pgid") for pid in live)
        found = {pid: info for pid, info in processes.items()
                 if (info["ppid"] in live or
                     (info["pgid"] == record.get("pgid") and group_anchored))
                 and ((info["birth"] is None and pid not in pending)
                      or (info["birth"] is not None and
                          known.get(str(pid), {}).get("birth") != info["birth"]))}
        if not found:
            if pending:
                record["unidentified"] = sorted(pending)
            else:
                record.pop("unidentified", None)
            return changed
        for pid, info in found.items():
            if info["birth"] is None:
                pending.add(pid)
            else:
                known[str(pid)] = {"birth": info["birth"], "pgid": info["pgid"]}
                pending.discard(pid)
        changed = True


def _write_holder(path: Path, record: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=1))
    os.replace(temporary, path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _holder_alive(holder: dict) -> bool:
    pid = int(holder.get("holder_pid") or 0)
    if not _alive(pid):
        return False
    birth = holder.get("holder_birth")
    if birth is None:
        return True
    try:
        return list(process_identity(pid).birth) == birth
    except (OSError, PermissionError):
        return True  # uncertain: retain the claim until identity can be checked


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_lease(record: dict, holder_file: Path | None = None) -> dict:
    """Signal only live identities in this record and its verified private process group."""
    pgid = record.get("pgid")

    def targets() -> tuple[set[int], bool, bool, set[int], bool]:
        processes = _processes()
        if processes is None:
            return set(), False, False, set(), False
        if _observe(record, processes) and holder_file is not None:
            _write_holder(holder_file, record)
        live = {int(pid) for pid, identity in record.get("processes", {}).items()
                if int(pid) in processes and processes[int(pid)]["birth"] == identity["birth"]}
        unverified = {int(pid) for pid in record.get("processes", {})
                      if int(pid) in processes and processes[int(pid)]["birth"] is None}
        group = bool(pgid and any(processes[pid]["pgid"] == pgid for pid in live))
        root = record.get("pid")
        root_unverified = bool(root and int(root) in processes and str(root) not in record.get("processes", {}))
        return live, group, True, unverified, root_unverified

    def signal_all(sig: int) -> None:
        live, group, scanned, _, _ = targets()
        if not scanned:
            return
        if group:
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        for pid in live:
            # Recheck directly before signalling, since a PID can have exited since the snapshot.
            current = _processes()
            if current is not None and pid in current and current[pid]["birth"] == record["processes"][str(pid)]["birth"]:
                if group and current[pid]["pgid"] == pgid:
                    continue
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass

    before, group, scanned, unverified, root_unverified = targets()
    if before or group:
        signal_all(signal.SIGTERM)
        signal_all(signal.SIGCONT)
        deadline = time.monotonic() + GRACE_SECONDS
        while time.monotonic() < deadline:
            live, group, scanned, unverified, root_unverified = targets()
            if not live and not group:
                break
            time.sleep(0.2)
    killed, group, scanned, unverified, root_unverified = targets()
    if killed or group:
        signal_all(signal.SIGKILL)
        time.sleep(0.2)
    remaining, group, scanned, unverified, root_unverified = targets()
    unresolved = sorted(remaining) + [f"identity-unavailable:{pid}" for pid in sorted(unverified)]
    unresolved += [f"unidentified:{pid}" for pid in record.get("unidentified", [])]
    if root_unverified:
        unresolved.append("root-identity-unavailable")
    if pgid and not group and _group_alive(pgid):
        unresolved.append(f"group:{pgid}")
    if not scanned and (record.get("pid") or record.get("processes") or (pgid and _group_alive(pgid))):
        unresolved.append("process-table-unavailable")
    return {"reaped": sorted(before), "needed_kill": sorted(killed), "remaining": unresolved,
            "sweep": "complete" if scanned else "unavailable"}


def _holders(directory: Path) -> list[dict]:
    out = []
    for path in sorted((directory / "holders").glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out


def _reap_dead_holders(directory: Path) -> list[dict]:
    """Recover dead holders; retain unresolved claims for later attempts and capacity accounting."""
    cleaned = []
    with open(directory / "reap.lock", "a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        for holder in _holders(directory):
            if holder.get("holder_pid") and not _holder_alive(holder):
                path = directory / "holders" / f"{holder['lease_id']}.json"
                result = stop_lease(holder, path)
                if result.get("remaining") or result.get("sweep") == "unavailable":
                    holder["unresolved"] = result
                    _write_holder(path, holder)
                else:
                    path.unlink(missing_ok=True)
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
        running = _holders(directory)
        if ahead is None or (blocked and running):
            return None, ahead or 0, running
        if cap - sum(int(h.get("weight", 1)) for h in running) < weight:
            return None, ahead, running
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
    holders = _holders(directory)
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


def run(command: list[str], *, weight: int, purpose: str, max_minutes: float, wait: bool, owner: str) -> int:
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
    try:
        holder_birth = list(process_identity(os.getpid()).birth)
    except (OSError, PermissionError):
        holder_birth = None
    record = {"lease_id": lease_id, "owner": owner, "purpose": purpose, "weight": weight, "capacity": cap,
              "holder_birth": holder_birth,
              "holder_pid": os.getpid(), "command": command}
    holder_file = directory / "holders" / f"{lease_id}.json"

    def claim(backfill: bool) -> None:
        now = time.time()
        record.update(backfill=backfill, admitted_ns=time.time_ns(), waited_seconds=round(now - queued_at, 1),
                      started_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                      expires_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + max_minutes * 60)))
        _write_holder(holder_file, record)
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
    birth = _birth_at(child.pid, os.getpid(), child.pid)
    if birth is not None:
        record["processes"] = {str(child.pid): {"birth": birth, "pgid": child.pid}}
    processes = _processes()
    if processes is not None:
        _observe(record, processes, seed_root=True)
    _write_holder(holder_file, record)

    outcome, code = "exited", None
    stop_signal: list[int] = []

    def on_signal(signum, _frame):
        stop_signal.append(signum)

    previous_handlers = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            deadline = time.monotonic() + max_minutes * 60
            while True:
                if stop_signal:
                    break
                processes = _processes()
                if processes is not None and _observe(record, processes, seed_root=child.poll() is None):
                    _write_holder(holder_file, record)
                try:
                    code = child.wait(timeout=min(0.1, max(0, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
        except subprocess.TimeoutExpired:
            outcome, code = "timed_out", EXIT_TIMEOUT
            print(f"heavy: time ran out after {max_minutes:g} min; stopping the lease's processes", file=sys.stderr)
        if stop_signal:
            outcome = "interrupted"
            code = 128 + stop_signal[0]
    finally:
        sweep = stop_lease(record, holder_file)
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
        if sweep.get("remaining") or sweep.get("sweep") == "unavailable":
            record["unresolved"] = sweep
            _write_holder(holder_file, record)
        else:
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
        print("usage: ottoctl heavy [--weight N] [--purpose TEXT] [--max-minutes N] [--no-wait] -- CMD [ARGS...]\n"
              "       ottoctl heavy status", file=sys.stderr)
        return 2
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="ottoctl heavy", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weight", type=int, default=1,
                        help="slots this job takes (frame 1, journey or test suite 2, full render 3)")
    parser.add_argument("--purpose", help="what this heavy job is for (shown to whoever waits)")
    parser.add_argument("--max-minutes", type=float, default=60.0, help="stop everything after this long (default 60)")
    parser.add_argument("--no-wait", action="store_true", help="exit 75 instead of waiting when there's no capacity")
    parser.add_argument("--owner", default=os.environ.get("OTTO_HEAVY_OWNER")
                        or f"{os.environ.get('USER', '?')} pid {os.getppid()} in {os.getcwd()}",
                        help="who holds the lease (default $OTTO_HEAVY_OWNER, or the caller's pid and directory)")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    if not command:
        parser.error("no command after --")
    return run(command, weight=args.weight, purpose=args.purpose or " ".join(command)[:120],
               max_minutes=args.max_minutes, wait=not args.no_wait, owner=args.owner)


if __name__ == "__main__":
    raise SystemExit(main())

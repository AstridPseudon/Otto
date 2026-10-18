"""Runner core: one admission queue for heavy commands, each run under custody, each result sealed before its units return."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any, Callable

from .. import custody
from .admission import Entry, Holder, pick
from .commit import git_commit_identity
from .store import RUN_ID, ResultStore, StoreError

EXIT_UNKNOWN = 70
_TIMEOUT_EXIT = 124
_MAX_SECONDS = 86400
_PURPOSE_CHARS = 120


class Lease:
    """A run that holds units (a nested run holds none) from its start until its tree is gone."""

    def __init__(self, run_id: str, ticket: str | None, units: int, backfill: bool, record: dict[str, Any]) -> None:
        self.run_id = run_id
        self.ticket = ticket
        self.units = units
        self.backfill = backfill
        self.record = record
        self.custody: Any = None
        self.children: list[str] = []
        self.lock = threading.Lock()
        self.started_at: float | None = None
        self.interrupted = False
        self.closed = False
        self.done = False


class Runner:
    """Admits heavy commands through the pool, runs each under custody, and seals its result."""

    def __init__(self, pool: Any, store: ResultStore, *, state_dir: Any,
                 resolve_commit: Callable[[str], str | None] = git_commit_identity,
                 census_fn: Callable[[], dict | None] | None = None, environ: Mapping[str, str] | None = None,
                 grace_seconds: float = 1.0, clock: Callable[[], float] = time.time,
                 launch: Callable[..., Any] | None = None, poll_seconds: float = 0.5) -> None:
        self._pool = pool
        self._store = store
        self._state_dir = os.fspath(state_dir)
        self._latches = os.path.join(self._state_dir, "latches")
        self._usage = os.path.join(self._state_dir, "usage")
        for path in (self._latches, self._usage):
            os.makedirs(path, mode=0o700, exist_ok=True)
        self._resolve_commit = resolve_commit
        self._census_fn = census_fn
        self._environ = environ
        self._grace = grace_seconds
        self._clock = clock
        self._launch = launch
        self._poll = poll_seconds
        self._capacity = pool.policy.heavy_headroom
        self._cond = threading.Condition(threading.RLock())
        self._queue: list[Entry] = []
        self._queued: dict[str, dict[str, Any]] = {}
        self._leases: dict[str, Lease] = {}
        self._started = False
        self._stopped = False
        self._halt = threading.Event()
        self._ticker: threading.Thread | None = None
        self.invalid: list[str] = []
        self.reconcile()

    # -- requests ----------------------------------------------------------------------------

    def submit(self, request: Mapping[str, Any], peer_pid: int | None = None) -> dict[str, Any]:
        """Admit one command, or answer an existing run_id without launching anything."""
        if not isinstance(request, Mapping):
            return _error("bad_request", "request must be an object")
        try:
            req = self._parse(request)
        except ValueError as exc:
            return _error("bad_request", str(exc))
        snap = self._census_for(peer_pid)
        commit = self._resolve_commit(req["cwd"])
        if commit is None:
            return _error("no_commit", "cwd is not a git work tree with a commit")
        binding = self._store.binding(req["argv"], req["cwd"], commit)
        run_id = req["request_id"] or "run-" + uuid.uuid4().hex[:12]
        with self._cond:
            try:
                existing = self._store.get(run_id)
            except StoreError as exc:
                return _error("evidence_invalid", str(exc))
            if existing is not None:
                if existing["binding"] != binding:
                    return _error("binding_mismatch", "run_id %s names a different command" % run_id)
                return {"ok": True, "run_id": run_id, "state": existing["state"], "existing": True,
                        "binding": binding, "commit": commit}
            parent = self._parent_lease(peer_pid, snap)
            units = 0 if parent is not None else req["units"]
            record = {
                "run_id": run_id, "seq": self._store.next_seq(), "binding": binding,
                "argv": req["argv"], "cwd": req["cwd"], "commit": commit,
                "task": req["task"], "purpose": req["purpose"], "units": units,
                "weight_requested": req["weight"], "max_seconds": req["max_seconds"],
                "state": "queued", "outcome": None, "exit_code": None,
                "nested_in": None if parent is None else parent.run_id, "backfill": False,
                "submitted_at": self._clock(), "started_at": None, "settled_at": None,
                "seconds": None, "unit_seconds": None, "tokens": 0, "custody": None,
                "output_sha256": None, "output_bytes": None,
            }
            try:
                self._store.put(record)
            except StoreError as exc:
                return _error("evidence_invalid", str(exc))
            if parent is None:
                self._queued[run_id] = record
                self._queue.append(Entry(run_id, units, record["seq"]))
                self.pump()
            else:
                lease = Lease(run_id, None, 0, False, record)
                self._leases[run_id] = lease
                parent.children.append(run_id)
                self._start(lease)
            return {"ok": True, "run_id": run_id, "state": record["state"], "nested": parent is not None,
                    "binding": binding, "commit": commit}

    def await_run(self, run_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Wait until the run's record is terminal, or until the timeout passes."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                try:
                    record = self._store.get(run_id)
                except StoreError:
                    return {"ok": False, "error": "evidence_invalid"}
                if record is None:
                    return {"ok": False, "error": "unknown_run"}
                if record["state"] in ("settled", "unknown"):
                    code = record["exit_code"] if record["state"] == "settled" else EXIT_UNKNOWN
                    return {"ok": True, "done": True, "record": record, "exit_code": code}
                if deadline is None:
                    self._cond.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"ok": True, "done": False, "state": record["state"]}
                self._cond.wait(remaining)

    def status(self, run_id: str | None = None) -> dict[str, Any]:
        """Capacity, holders, waiters and the pool ledger, plus one run's record when asked."""
        with self._cond:
            leases = list(self._leases.values())
            used = sum(lease.units for lease in leases if lease.ticket is not None)
            out: dict[str, Any] = {
                "ok": True, "capacity": self._capacity, "used": used, "free": self._capacity - used,
                "holders": [{"run_id": lease.run_id, "units": lease.units, "backfill": lease.backfill,
                             "task": lease.record["task"], "purpose": lease.record["purpose"],
                             "started_at": lease.started_at} for lease in leases],
                "waiting": [{"run_id": entry.run_id, "units": entry.units,
                             "task": self._queued[entry.run_id]["task"],
                             "purpose": self._queued[entry.run_id]["purpose"]} for entry in self._queue],
                "pool": self._pool.snapshot(), "record": None,
            }
            if run_id is not None:
                try:
                    out["record"] = self._store.get(run_id)
                except StoreError as exc:
                    return _error("evidence_invalid", str(exc))
        return out

    def report(self, task: str | None = None) -> dict[str, Any]:
        """Per-task sums over the verified records, and the totals over all of them."""
        records, invalid = self._store.all_records()
        tasks: dict[str, dict[str, Any]] = {}
        totals = _empty_row()
        for record in records:
            _add_row(tasks.setdefault(record["task"], _empty_row()), record)
            _add_row(totals, record)
        if task is not None:
            tasks = {task: tasks[task]} if task in tasks else {}
        return {"ok": True, "tasks": tasks, "totals": totals, "invalid": invalid}

    # -- lifecycle ---------------------------------------------------------------------------

    def reconcile(self) -> None:
        """Settle what an earlier life left behind, before anything can launch. Never relaunches a run."""
        records, invalid = self._store.all_records()
        self.invalid = invalid
        running = {record["run_id"] for record in records if record["state"] == "running"}
        by_id = {record["run_id"]: record for record in records}
        unresolved: list[dict[str, Any]] = []
        for record in records:
            if record["state"] == "running":
                disposition = custody.resume_cleanup(self._latch_path(record["run_id"]), self._grace, self._census_fn)
                self._put_record(record, state="unknown", outcome="lost_in_restart", exit_code=None,
                                 custody=_custody_state(disposition), settled_at=self._clock())
                if not disposition.gone:
                    unresolved.append(record)
            elif record["state"] == "unknown" and record.get("custody") == "uncertain":
                # Unknown is terminal evidence, but an uncertain custody result still holds capacity.
                unresolved.append(record)
        for record in records:
            if record["state"] != "queued":
                continue
            if record["nested_in"] is not None:
                self._put_record(record, state="unknown", outcome="lost_in_restart", exit_code=None,
                                 settled_at=self._clock())
            elif self._resolve_commit(record["cwd"]) == record["commit"]:
                self._queued[record["run_id"]] = record
                self._queue.append(Entry(record["run_id"], min(record["units"], self._capacity), record["seq"]))
            else:
                self._put_record(record, state="unknown", outcome="stale_commit", exit_code=None,
                                 settled_at=self._clock())
        for name in sorted(os.listdir(self._latches)):
            if name.endswith(".json") and name[:-len(".json")] not in running:
                custody.resume_cleanup(os.path.join(self._latches, name), self._grace, self._census_fn)
        heavy = self._pool.snapshot()["heavy"]
        for ticket in heavy["leases"] + heavy["waiting"]:
            self._pool.release_heavy(ticket)
        self._restore_nested_holds(unresolved, by_id)

    def _restore_nested_holds(self, children: list[dict[str, Any]],
                              records: Mapping[str, dict[str, Any]]) -> None:
        """Recreate capacity claims for nested trees whose custody remains uncertain."""
        roots: dict[str, dict[str, Any]] = {}
        fallbacks: dict[str, dict[str, Any]] = {}
        for record in children:
            root = self._verified_scope_root(record, records)
            if root is not None:
                roots[root["run_id"]] = root
            else:
                # Without a complete, verified ancestry chain, retain this run's own claim.
                fallbacks[record["run_id"]] = record
        for root_id, root in roots.items():
            units = min(max(1, int(root.get("units", 1))), self._capacity)
            self._install_recovery_holder(root_id, root, units, "parent")
        for run_id, record in fallbacks.items():
            requested = record.get("weight_requested", 1)
            units = min(max(1, requested if type(requested) is int else 1), self._capacity)
            self._install_recovery_holder(run_id, record, units, "child")

    @staticmethod
    def _verified_scope_root(record: dict[str, Any],
                             records: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
        """Return the top verified ancestor of a recovery scope, rejecting gaps and cycles."""
        current = record
        seen: set[str] = set()
        while True:
            run_id = current.get("run_id")
            if not isinstance(run_id, str) or run_id in seen:
                return None
            seen.add(run_id)
            parent_id = current.get("nested_in")
            if parent_id is None:
                units = current.get("units")
                return current if type(units) is int and units > 0 else None
            if not isinstance(parent_id, str):
                return None
            parent = records.get(parent_id)
            if parent is None:
                return None
            current = parent

    def _install_recovery_holder(self, run_id: str, record: dict[str, Any], units: int,
                                 kind: str) -> None:
        holder = Lease(run_id, None, units, False, record)
        holder.ticket = self._claim_recovery("runner:recovery-%s:%s" % (kind, run_id), units)
        holder.done = holder.closed = True
        self._leases[run_id] = holder

    def _claim_recovery(self, owner: str, units: int) -> str:
        ticket = self._pool.queue_heavy(owner, units, pid=None)
        if not self._pool.claim_heavy(ticket):
            self._pool.release_heavy(ticket)
            # A valid custody claim must remain visible even if other adopted work fills the pool.
            # The runner pool is the accounting authority, so fail closed on an impossible overcommit.
            raise RuntimeError("could not restore unresolved runner capacity")
        return ticket

    def start(self) -> None:
        """Begin admitting queued runs, and keep pumping while any wait."""
        with self._cond:
            if self._stopped or self._started:
                return
            self._started = True
            self.pump()
            self._ticker = threading.Thread(target=self._tick, name="runner-ticker", daemon=True)
            self._ticker.start()

    def stop(self) -> None:
        """Stop admitting, interrupt every live run, and settle each one unknown/interrupted."""
        self._halt.set()
        with self._cond:
            self._stopped = True
            leases = list(self._leases.values())
            for lease in leases:
                lease.closed = True
        for lease in leases:
            self._interrupt(lease)
        if self._ticker is not None:
            self._ticker.join(timeout=self._poll + 1.0)

    def pump(self) -> None:
        """Start queued runs in arrival order, backfilling where admission allows, until nothing more fits."""
        with self._cond:
            if self._stopped or not self._started:
                return
            self._pool.prune_dead_heavy()
            while True:
                holders = [Holder(lease.units, lease.backfill) for lease in self._leases.values()
                           if lease.ticket is not None]
                choice = pick(self._queue, holders, self._capacity)
                if choice is None:
                    return
                entry, backfill = choice
                ticket = self._pool.queue_heavy("runner:" + entry.run_id, entry.units, pid=None)
                try:
                    claimed = self._pool.claim_heavy(ticket)
                except KeyError:
                    claimed = False
                if not claimed:
                    self._pool.release_heavy(ticket)
                    return
                self._queue.remove(entry)
                lease = Lease(entry.run_id, ticket, entry.units, backfill, self._queued.pop(entry.run_id))
                self._leases[entry.run_id] = lease
                self._start(lease)

    # -- execution ---------------------------------------------------------------------------

    def _execute(self, lease: Lease) -> None:
        try:
            self._run(lease)
        except Exception:
            self._abandon(lease)
        finally:
            self._finish(lease)

    def _run(self, lease: Lease) -> None:
        record = lease.record
        run_id = lease.run_id
        if self._resolve_commit(record["cwd"]) != record["commit"]:
            with self._cond:
                self._write(lease, state="unknown", outcome="stale_commit", exit_code=None,
                            settled_at=self._clock())
            return
        started = self._clock()
        with self._cond:
            if not self._write(lease, state="running", started_at=started, backfill=lease.backfill,
                               units=lease.units):
                return
            lease.started_at = started
        env = dict(os.environ if self._environ is None else self._environ)
        env["RUNNER_USAGE_PATH"] = self._usage_path(run_id)
        extra = {} if self._census_fn is None else {"census_fn": self._census_fn}
        launcher = self._launch or custody.Custody.launch
        failed = False
        with open(self._store.output_path(run_id), "wb") as out:
            with lease.lock:
                if lease.interrupted:
                    return
                try:
                    lease.custody = launcher(record["argv"], latch_path=self._latch_path(run_id),
                                             cwd=record["cwd"], env=env, stdin=subprocess.DEVNULL,
                                             stdout=out, stderr=subprocess.STDOUT, **extra)
                except Exception:
                    failed = True
        if failed:
            with self._cond:
                self._write(lease, state="unknown", outcome="launch_failed", exit_code=None,
                            settled_at=self._clock())
            return
        process = lease.custody.process
        try:
            process.wait(timeout=record["max_seconds"])
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
        with self._cond:
            lease.closed = True
        with lease.lock:
            if timed_out:
                disposition = lease.custody.terminate(self._grace)
                code = None
            else:
                disposition = lease.custody.release()
                code = process.returncode
            interrupted = lease.interrupted
        if interrupted:
            outcome, exit_code, state = "interrupted", None, "unknown"
        elif timed_out:
            outcome, exit_code, state = "timed_out", _TIMEOUT_EXIT, "settled"
        else:
            outcome, exit_code, state = "exited", (code if code >= 0 else 128 - code), "settled"
        seconds, unit_seconds = self._elapsed(lease)
        digest, size = _digest(self._store.output_path(run_id))
        with self._cond:
            self._write(lease, state=state, outcome=outcome, exit_code=exit_code,
                        custody=_custody_state(disposition), tokens=_usage_tokens(self._usage_path(run_id)),
                        output_sha256=digest, output_bytes=size, settled_at=self._clock(),
                        seconds=seconds, unit_seconds=unit_seconds)

    def _abandon(self, lease: Lease) -> None:
        try:
            with self._cond:
                self._write(lease, state="unknown", outcome="interrupted", exit_code=None,
                            settled_at=self._clock())
        except StoreError:
            pass

    def _finish(self, lease: Lease) -> None:
        """Retire the lease: interrupt its unfinished children, then return its units and admit the next run."""
        with self._cond:
            lease.closed = True
            children = [self._leases[child] for child in lease.children if child in self._leases]
            children = [child for child in children if not child.done]
        for child in children:
            self._interrupt(child)
        with self._cond:
            self._leases.pop(lease.run_id, None)
            if lease.ticket is not None:
                self._pool.release_heavy(lease.ticket)
            self._cond.notify_all()
            self.pump()

    def _interrupt(self, lease: Lease) -> None:
        """Stop a lease's tree and settle its run unknown/interrupted, unless the run has already settled."""
        with self._cond:
            if lease.done:
                return
            lease.closed = True
        with lease.lock:
            lease.interrupted = True
            disposition = None if lease.custody is None else lease.custody.terminate(self._grace)
        seconds, unit_seconds = self._elapsed(lease)
        with self._cond:
            self._write(lease, state="unknown", outcome="interrupted", exit_code=None,
                        custody=_custody_state(disposition), settled_at=self._clock(),
                        seconds=seconds, unit_seconds=unit_seconds)

    def _write(self, lease: Lease, **fields: Any) -> bool:
        """Persist a change to a run's record (caller holds the condition). A terminal record is final."""
        if lease.done:
            return False
        terminal = fields.get("state") in ("settled", "unknown")
        self._put_record(lease.record, **fields)
        if terminal:
            lease.done = True
            lease.closed = True
            self._cond.notify_all()
        return True

    def _put_record(self, record: dict[str, Any], **fields: Any) -> None:
        record.update(fields)
        self._store.put(record)

    def _elapsed(self, lease: Lease) -> tuple[float | None, float | None]:
        if lease.started_at is None:
            return None, None
        seconds = round(self._clock() - lease.started_at, 3)
        return seconds, round(lease.units * seconds, 3)

    def _start(self, lease: Lease) -> None:
        threading.Thread(target=self._execute, args=(lease,), name="runner-" + lease.run_id, daemon=True).start()

    def _tick(self) -> None:
        while not self._halt.wait(self._poll):
            with self._cond:
                if self._queue:
                    self.pump()

    # -- nesting -----------------------------------------------------------------------------

    def _census_for(self, peer_pid: int | None) -> dict | None:
        if peer_pid is None:
            return None
        return (self._census_fn or custody.census)()

    def _parent_lease(self, peer_pid: int | None, snap: dict | None) -> Lease | None:
        """The open lease whose process tree holds the peer, matched by pid and birth; None means standalone."""
        if peer_pid is None or not snap or peer_pid not in snap:
            return None
        peer = snap[peer_pid]
        for lease in self._leases.values():
            if lease.closed:
                continue
            with lease.lock:
                if lease.custody is None:
                    continue
                live = lease.custody.observe(snap) or {}
            if live.get(peer_pid) == peer.birth:
                return lease
        return None

    # -- helpers -----------------------------------------------------------------------------

    def _parse(self, request: Mapping[str, Any]) -> dict[str, Any]:
        argv = request.get("argv")
        if not isinstance(argv, (list, tuple)) or not argv or not all(
                isinstance(arg, str) and "\0" not in arg for arg in argv):
            raise ValueError("argv must be a non-empty list of strings without NUL")
        cwd = request.get("cwd")
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            raise ValueError("cwd must name an existing directory")
        weight = _optional(request, "weight", 1)
        if type(weight) is not int:
            raise ValueError("weight must be an integer")
        task = _optional(request, "task", "untasked")
        purpose = _optional(request, "purpose", " ".join(argv)[:_PURPOSE_CHARS])
        if not isinstance(task, str) or not isinstance(purpose, str):
            raise ValueError("task and purpose must be strings")
        max_seconds = _optional(request, "max_seconds", 3600)
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) \
                or not 0 < max_seconds <= _MAX_SECONDS:
            raise ValueError("max_seconds must be a number above 0 and at most 86400")
        request_id = _optional(request, "request_id", None)
        if request_id is not None and (not isinstance(request_id, str) or not RUN_ID.fullmatch(request_id)):
            raise ValueError("request_id is not a valid run identifier")
        return {"argv": list(argv), "cwd": os.path.realpath(cwd), "weight": weight,
                "units": max(1, min(weight, self._capacity)), "task": task, "purpose": purpose,
                "max_seconds": float(max_seconds), "request_id": request_id}

    def _latch_path(self, run_id: str) -> str:
        return os.path.join(self._latches, run_id + ".json")

    def _usage_path(self, run_id: str) -> str:
        return os.path.join(self._usage, run_id + ".json")


def _error(code: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "detail": detail}


def _optional(request: Mapping[str, Any], key: str, default: Any) -> Any:
    value = request.get(key)
    return default if value is None else value


def _custody_state(disposition: Any) -> str | None:
    if disposition is None:
        return None
    return "gone" if disposition.gone else "uncertain"


def _usage_tokens(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return 0
    value = data.get("tokens") if isinstance(data, dict) else None
    return value if type(value) is int and value >= 0 else 0


def _digest(path: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _empty_row() -> dict[str, Any]:
    return {"runs": 0, "settled": 0, "unknown": 0, "seconds": 0.0, "unit_seconds": 0.0, "tokens": 0}


def _add_row(row: dict[str, Any], record: Mapping[str, Any]) -> None:
    row["runs"] += 1
    row["settled"] += int(record["state"] == "settled")
    row["unknown"] += int(record["state"] == "unknown")
    if record["seconds"] is not None:
        row["seconds"] += record["seconds"]
    if record["unit_seconds"] is not None:
        row["unit_seconds"] += record["unit_seconds"]
    row["tokens"] += record["tokens"]

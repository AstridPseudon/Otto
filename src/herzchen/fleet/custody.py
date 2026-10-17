"""Private process-group custody with a birth-fenced recovery record.

A caller that launches a command through ``Custody.launch`` owns its private process group.
The rules for group signal authority and settlement are:

* Identity is ``(pid, birth)``, never a bare pid. ``birth`` is the process start time from the census.
* A group id is signalled only while it is provably ours: our unreaped leader still holds it, or a
  tracked member whose birth still matches is alive in it. A group id is reusable only once its group is
  empty, so a live proven member means nobody else can hold it. A reaped leader is never enough.
* A leader pid that the census shows with a different birth proves the old group is gone. That group id
  now belongs to someone else and is never signalled.
* The census is evidence only when it is non-empty and contains this very process. An empty or missing
  census is *uncertain*, never "all gone". Only a clean census with nothing of ours left is ``gone``.
* A census gap while a group is live latches doubt; a later clean census cannot erase that gap.
* The latch records launch intent before spawning and group identity before cleanup signals. A crashed
  cleanup resumes with ``resume_cleanup`` and the latch is removed only on ``gone``.

An accidentally detached process that was not recorded while it belonged to the group is outside this
scope's evidence. An already recorded escaped identity keeps settlement unresolved, but is not signalled
through ancestry or a bare pid; it needs its own private-group scope for cleanup.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

_REAL_POPEN = subprocess.Popen     # the census must keep working when a caller patches subprocess.Popen

GONE = "gone"
UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    birth: str
    zombie: bool = False


@dataclass(frozen=True)
class Disposition:
    """What custody can prove about a tree. ``gone`` is the only state that frees its owner."""

    state: str
    reason: str = ""
    remaining: tuple = ()

    @property
    def gone(self) -> bool:
        return self.state == GONE


def census() -> Optional[dict]:
    """``pid -> Proc`` for every process, or ``None`` when the census cannot be trusted.

    A census that is empty, or that does not list this process, is a broken census, not an empty machine.
    """
    ps = next((p for p in ("/bin/ps", "/usr/bin/ps") if os.path.isfile(p)), "ps")
    try:
        with _REAL_POPEN([ps, "-axo", "pid=,ppid=,pgid=,stat=,lstart="], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True) as proc:
            try:
                out, _ = proc.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return None
            code = proc.returncode
    except (OSError, subprocess.SubprocessError):
        return None
    if code != 0:
        return None
    table: dict = {}
    for line in out.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) != 5:
            continue
        try:
            pid, ppid, pgid = (int(value) for value in fields[:3])
        except ValueError:
            continue
        table[pid] = Proc(pid, ppid, pgid, fields[4], fields[3].startswith("Z"))
    if not table or os.getpid() not in table:
        return None
    return table


def _write_latch(path: str, record: Mapping[str, Any]) -> None:
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _sync_parent(path)


def _sync_parent(path: str) -> None:
    directory = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_launch_intent(path: str) -> None:
    # Exclusive creation preserves any previous unresolved scope at this path.
    with open(path, "x", encoding="utf-8") as handle:
        json.dump({"pgid": None, "leader_birth": None, "state": "launching", "members": {}}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_parent(path)


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    else:
        _sync_parent(path)


class Custody:
    """One launched tree: its group, its leader's birth, and every descendant identity seen so far."""

    def __init__(self, process: Any, pgid: int, leader_birth: Optional[str], members: Mapping[int, str],
                 latch_path: Optional[str] = None, census_fn: Optional[Callable[[], Optional[dict]]] = None,
                 doubt: Optional[str] = None, state: str = "running") -> None:
        self.process = process
        self.pgid = pgid
        self.leader_birth = leader_birth
        self.known: dict = dict(members)
        self.latch_path = latch_path
        census_fn = census_fn or (lambda: census())     # looked up per call so a patched census applies
        self._census = lambda: census_fn() or None     # an empty census is no census
        self.doubt = doubt
        self.state = state

    # -- birth -------------------------------------------------------------------------------
    @classmethod
    def launch(cls, argv: Any, *, latch_path: Optional[str] = None, popen: Optional[Callable[..., Any]] = None,
               census_fn: Optional[Callable[[], Optional[dict]]] = None, **kwargs: Any) -> "Custody":
        """Record intent, then start ``argv`` as a fresh session leader and fence its identity."""
        if latch_path is not None:
            # A crash between spawn and identity capture leaves an unresolved launch intent.
            _write_launch_intent(latch_path)
        kwargs["start_new_session"] = True
        try:
            process = (subprocess.Popen if popen is None else popen)(argv, **kwargs)  # patches apply
        except Exception:
            # Popen did not return a process handle, so this invocation owns no signallable group.
            if latch_path is not None:
                _remove(latch_path)
            raise
        custody = cls(process, process.pid, None, {}, latch_path, census_fn)
        snap = custody._census()
        leader = snap.get(process.pid) if snap else None
        if leader is None or leader.pgid != process.pid:
            custody.doubt = "leader identity not captured at birth"
        else:
            custody.leader_birth = leader.birth
            custody.known[process.pid] = leader.birth
        custody._persist("running")
        return custody

    @classmethod
    def from_latch(cls, latch_path: str, census_fn: Optional[Callable[[], Optional[dict]]] = None) -> "Custody":
        """Rebuild custody from a latch a crashed owner left behind."""
        try:
            with open(latch_path, encoding="utf-8") as handle:
                record = json.load(handle)
            members = {int(pid): str(birth) for pid, birth in record["members"].items()}
            return cls(None, int(record["pgid"]), record.get("leader_birth"), members, latch_path,
                       census_fn, doubt=record.get("doubt"), state=record.get("state", "running"))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return cls(None, -1, None, {}, latch_path, census_fn, doubt="latch unreadable: %s" % type(exc).__name__)

    def _persist(self, state: str) -> None:
        if self.latch_path is None or self.pgid < 0:
            return
        if self.state == "terminating":
            state = "terminating"
        try:
            _write_latch(self.latch_path, {"pgid": self.pgid, "leader_birth": self.leader_birth, "state": state,
                                           "members": {str(pid): birth for pid, birth in self.known.items()},
                                           "doubt": self.doubt})
            self.state = state
        except OSError:
            self.doubt = self.doubt or "cleanup latch could not be written"

    # -- census ------------------------------------------------------------------------------
    def _live(self, snap: Mapping[int, Proc], pid: int) -> bool:
        info = snap.get(pid)
        return info is not None and not info.zombie and info.birth == self.known.get(pid)

    def _record_census_gap(self) -> None:
        if self.doubt is None:
            self.doubt = "census unavailable while scope was unresolved"
            self._persist(self.state)

    def _group_state(self, snap: Mapping[int, Proc]) -> str:
        """``ours`` (provably), ``reused`` (the old group is provably gone), ``empty`` or ``unproven``."""
        if self.pgid < 0:
            return "unproven"
        members = [i for i in snap.values() if i.pgid == self.pgid and not i.zombie]
        leader = snap.get(self.pgid)
        if leader is not None and self.leader_birth is not None and leader.birth != self.leader_birth:
            return "reused"                    # the leader pid was recycled: the old group was empty
        if self.process is not None and self.process.poll() is None:
            return "ours"                      # our unreaped leader still holds the group id
        if any(self._live(snap, i.pid) for i in members):
            return "ours"
        return "unproven" if members else "empty"

    def observe(self, snap: Optional[Mapping[int, Proc]] = None) -> Optional[dict]:
        """Record proven group members and return live recorded identities.

        ``None`` means the census failed and latches doubt for this scope.
        A parent pid or environment tag alone never grants signal authority.
        """
        snap = self._census() if snap is None else snap
        if snap is None:
            self._record_census_gap()
            return None
        before = len(self.known)
        if self._group_state(snap) == "ours":
            for info in snap.values():
                if info.pgid == self.pgid and not info.zombie and info.pid not in self.known:
                    self.known[info.pid] = info.birth
        if len(self.known) != before:
            self._persist("running")
        return {pid: birth for pid, birth in self.known.items() if self._live(snap, pid)}

    # -- signals -----------------------------------------------------------------------------
    def _send(self, sig: int) -> None:
        """Signal the proven private group after a fresh census."""
        snap = self._census()
        if snap is None:
            self._record_census_gap()
            return
        self.observe(snap)
        grouped = self._group_state(snap) == "ours"
        if grouped:
            try:
                os.killpg(self.pgid, sig)
            except OSError:
                pass

    def signal_group(self, sig: int) -> bool:
        """Signal the group only while it is provably ours. Returns whether a signal was sent."""
        snap = self._census()
        if snap is None:
            self._record_census_gap()
            return False
        if self._group_state(snap) != "ours":
            return False
        try:
            os.killpg(self.pgid, sig)
        except OSError:
            return False
        return True

    def status(self) -> Disposition:
        """Fail closed: ``gone`` only from a clean census with nothing of ours in it."""
        snap = self._census()
        if snap is None:
            self._record_census_gap()
            return Disposition(UNCERTAIN, "census unavailable")
        live = self.observe(snap)
        if live:
            return Disposition("alive", "tracked processes remain", tuple(sorted(live)))
        state = self._group_state(snap)
        if state == "unproven":
            return Disposition(UNCERTAIN, "group id held by members that cannot be proven ours")
        if state == "ours":
            return Disposition("alive", "group members remain")
        if self.process is not None and self.process.poll() is None:
            return Disposition("alive", "leader not yet reaped")
        if self.doubt:
            return Disposition(UNCERTAIN, self.doubt)
        if self.pgid < 0 or (self.leader_birth is None and not self.known):
            return Disposition(UNCERTAIN, "no identity was ever captured")
        return Disposition(GONE)

    def terminate(self, grace_seconds: float = 1.0) -> Disposition:
        """Stop the whole tree: TERM, a bounded wait, KILL, then prove it absent."""
        if self.pgid < 0:
            return Disposition(UNCERTAIN, self.doubt or "no identity was ever captured")
        self.observe()
        self._persist("terminating")             # before any signal, so a crash here is resumable
        self._send(signal.SIGTERM)
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while time.monotonic() < deadline and self.status().state == "alive":
            time.sleep(0.02)
        kill_deadline = time.monotonic() + max(1.0, grace_seconds)
        verdict = self.status()
        while verdict.state == "alive" and time.monotonic() < kill_deadline:
            self._send(signal.SIGKILL)
            time.sleep(0.02)
            verdict = self.status()
        return self._settle(verdict)

    def release(self) -> Disposition:
        """The leader finished on its own: sweep anything it left behind and retire the latch."""
        return self.terminate(grace_seconds=0.2)

    def _settle(self, verdict: Disposition) -> Disposition:
        if self.process is not None:
            try:
                self.process.wait(timeout=0)
            except subprocess.TimeoutExpired:
                return Disposition(UNCERTAIN, "leader survived bounded termination")
            if verdict.state == "alive":
                verdict = self.status()
        if verdict.state == "alive":
            return Disposition(UNCERTAIN, "processes survived bounded termination", verdict.remaining)
        if verdict.state == GONE and self.latch_path is not None:
            _remove(self.latch_path)
        return verdict


def resume_cleanup(latch_path: str, grace_seconds: float = 1.0,
                   census_fn: Optional[Callable[[], Optional[dict]]] = None) -> Disposition:
    """Finish a cleanup a crashed owner began. Identities that no longer match are left alone."""
    if not os.path.exists(latch_path):
        return Disposition(GONE, "no latch")
    return Custody.from_latch(latch_path, census_fn).terminate(grace_seconds)

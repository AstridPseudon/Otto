"""Fleet capacity: one pool of units for turns and heavy work, held on ``limits`` reservations.

The pool is pure fleet mechanism. It takes its process-identity probe as an
injected callable, so it imports nothing from Otto.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import threading
from typing import Any, Callable, Mapping
import uuid

_UNBOUNDED_ALLOWANCE = 10 ** 15  # reusable capacity: the cumulative allowance never limits it


@dataclass(frozen=True)
class CapacityPolicy:
    """The pool's units. A turn weighs one unit; heavy work weighs what it asks.

    ``turn_units`` are shared by workers and managers. Three tiers are protected:
    ``manager_reserve`` units are taken by managers only (a manager always gets a
    slot, whatever the workers hold); ``heavy_headroom`` units are taken by heavy
    work only, so turns cannot starve a check a turn-holding worker needs; and
    ``worker_floor`` shared units can never be taken by managers, so a manager
    flood cannot starve workers.
    """

    turn_units: int = 6
    manager_reserve: int = 2
    heavy_headroom: int = 3
    worker_floor: int = 2

    def __post_init__(self) -> None:
        for name in ("turn_units", "manager_reserve", "heavy_headroom", "worker_floor"):
            value = getattr(self, name)
            minimum = 0 if name in ("manager_reserve", "worker_floor") else 1
            if type(value) is not int or value < minimum:
                raise ValueError("capacity policy %s must be an integer of at least %d" % (name, minimum))
        if self.worker_floor > self.turn_units:
            raise ValueError("capacity policy worker_floor cannot exceed turn_units")

    @property
    def total_units(self) -> int:
        return self.turn_units + self.manager_reserve + self.heavy_headroom

    @property
    def total_turn_units(self) -> int:
        return self.turn_units + self.manager_reserve

    @property
    def worker_units(self) -> int:
        return self.turn_units

    @property
    def manager_units(self) -> int:
        return self.turn_units + self.manager_reserve - self.worker_floor

    def admits_turn(self, role: str, workers: int, managers: int) -> bool:
        """Whether one more turn of ``role`` fits beside ``workers`` and ``managers``.

        Managers fill their reserve first, so only the managers beyond it use
        shared units. Any role other than manager counts as a worker.
        """
        if role == "manager":
            return (managers + 1 <= self.manager_units
                    and workers + managers + 1 <= self.total_turn_units)
        return workers + max(0, managers - self.manager_reserve) + 1 <= self.turn_units


def _owner_alive(pid: Any, birth: Any, process_birth: Callable[[int], Any] | None) -> bool:
    """False only when the process is provably gone or its pid was reused."""
    if process_birth is None or type(pid) is not int or pid <= 0:
        return True
    try:
        live = list(process_birth(pid))
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    except (OSError, ValueError, IndexError):
        return True  # unreadable is no proof
    return not isinstance(birth, list) or live == birth


def _parse_heavy_rid(rid: str) -> tuple[int | None, list[int] | None]:
    """The pid and birth a heavy reservation id names; ``-`` marks an unknown part."""
    try:
        _, pid_text, birth_text, _ = rid.split(":")
        pid = None if pid_text == "-" else int(pid_text)
        birth = None if birth_text == "-" else [int(value) for value in birth_text.split("-")]
    except ValueError:
        return None, None
    return pid, birth


class _MemoryLedger:
    """The limits contract for a pool that was not given an owner Store."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.rows: dict[str, dict[str, Any]] = {}

    def reserve(self, rid: str, units: int) -> None:
        if self.totals()["held_units"] + units > self.capacity:
            raise RuntimeError("reusable capacity is exhausted")
        self.rows[rid] = {"units": units, "status": "held", "charged": 0}

    def uncertain(self, rid: str) -> None:
        if self.rows[rid]["status"] == "held":
            self.rows[rid]["status"] = "uncertain"

    def settle(self, rid: str, units: int) -> None:
        self.rows[rid].update(status="consumed", charged=units)

    def release(self, rid: str) -> None:
        self.rows[rid].update(status="released", charged=0)

    def status(self, rid: str) -> str | None:
        row = self.rows.get(rid)
        return None if row is None else row["status"]

    def totals(self) -> dict[str, int]:
        return {"capacity_units": self.capacity,
                "held_units": sum(r["units"] for r in self.rows.values() if r["status"] in ("held", "uncertain")),
                "cumulative_used_units": sum(r["charged"] for r in self.rows.values())}


class _StoreLedger:
    """Reservations on kernel ``limits``, kept in the owner Store."""

    def __init__(self, store: Any, capacity: int) -> None:
        from herzchen.contracts import ResourceRef
        from herzchen.kernel import LimitService
        self._store, self._ref_type = store, ResourceRef
        self._pool = ResourceRef(store.authority, "limit", "host-capacity")
        self._service = LimitService(store)
        existing = self._service.get_pool(self._pool)
        if existing is None:
            self._service.create_pool(self._pool, capacity_units=capacity,
                cumulative_allowance_units=_UNBOUNDED_ALLOWANCE, logical_request_key="host-capacity:pool")
        elif existing.capacity_units != capacity:
            raise ValueError("existing host capacity pool differs from the adopted policy")
        self._records: dict[str, Any] = {}

    def _record(self, rid: str) -> Any:
        if rid not in self._records:
            found = self._service.get_reservation(self._ref_type(self._store.authority, "reservation", rid))
            if found is None:
                return None
            self._records[rid] = found
        return self._records[rid]

    def reserve(self, rid: str, units: int) -> None:
        self._records[rid] = self._service.reserve(self._pool, rid, units, logical_request_key="host-capacity:%s:reserve" % rid)

    def uncertain(self, rid: str) -> None:
        record = self._record(rid)
        if record.status.value == "held":
            self._records[rid] = self._service.mark_uncertain(record, logical_request_key="host-capacity:%s:uncertain" % rid)

    def settle(self, rid: str, units: int) -> None:
        self._records[rid] = self._service.settle(self._record(rid), units, logical_request_key="host-capacity:%s:settle" % rid)

    def release(self, rid: str) -> None:
        self._records[rid] = self._service.release(self._record(rid), logical_request_key="host-capacity:%s:release" % rid)

    def status(self, rid: str) -> str | None:
        record = self._record(rid)
        return None if record is None else record.status.value

    def totals(self) -> dict[str, int]:
        pool = self._service.get_pool(self._pool)
        return {"capacity_units": pool.capacity_units, "held_units": pool.held_units,
                "cumulative_used_units": pool.cumulative_used_units}

    def held_reservations(self) -> dict[str, Mapping[str, Any]]:
        """This pool's reservations whose latest status is held or uncertain, with their latest effects."""
        from herzchen.kernel.limits import LIMIT_STREAM, RESERVATION_KIND
        pool, latest = self._pool.to_dict(), {}
        for event in self._store.list_events(stream=LIMIT_STREAM):  # durable order: later events win
            effects = event.effects or {}
            if effects.get("record_type") == RESERVATION_KIND and effects.get("pool_ref") == pool:
                latest[event.subject.id] = effects
        return {rid: effects for rid, effects in latest.items()
                if effects.get("status") in ("held", "uncertain")}


class CapacityPool:
    """One pool for turns and heavy work, accounted on ``limits`` reservations.

    Admission is tiered over the policy's units (see CapacityPolicy); every
    admitted turn or heavy lease also holds a reservation, so the ledger shows
    the same load the tiers admit against. Heavy work queues in arrival order,
    and a waiter or holder whose process is gone stops counting.

    The reservation id carries the identity a restart needs (``turn:<key>:<hex>``,
    ``heavy:<pid>:<birth>:<hex>``). With a Store, a new pool adopts the held
    reservations the store's ``limits`` stream names, so no index file is kept.
    ``process_birth(pid)`` returns the process start identity; without it every
    owner counts as alive.
    """

    def __init__(self, policy: CapacityPolicy, *, store: Any = None,
                 process_birth: Callable[[int], Any] | None = None) -> None:
        self.policy = policy
        self._lock = threading.RLock()
        self._process_birth = process_birth
        self._ledger = _MemoryLedger(policy.total_units) if store is None else _StoreLedger(store, policy.total_units)
        self._turns: dict[str, str] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._waiting: list[dict[str, Any]] = []
        if store is not None:
            self._adopt()

    def _adopt(self) -> None:
        """Take up the reservations an earlier life of this pool left held or uncertain."""
        for rid, effects in self._ledger.held_reservations().items():
            if rid.startswith("turn:"):
                key = rid[len("turn:"):].rpartition(":")[0]
                superseded = self._turns.get(key)
                if superseded is not None and superseded != rid:
                    self._ledger.release(superseded)  # a later life's reservation stands for the key
                self._turns[key] = rid
            elif rid.startswith("heavy:"):
                pid, birth = _parse_heavy_rid(rid)
                if pid is None:
                    self._ledger.release(rid)  # no owner to prove gone, and no holder knows the new ticket
                    continue
                ticket = "heavy-" + uuid.uuid4().hex
                self._leases[ticket] = {"rid": rid, "units": int(effects["declared_units"]),
                                        "owner": "restored", "pid": pid, "birth": birth}

    def _reserve(self, rid: str, units: int, table: dict[str, Any], key: str, value: Any) -> None:
        self._ledger.reserve(rid, units)  # the ledger refuses first; nothing is recorded on failure
        table[key] = value

    # Turns -------------------------------------------------------------

    def ensure_turn(self, key: str, *, uncertain: bool = False) -> None:
        with self._lock:
            rid = self._turns.get(key)
            if rid is None or self._ledger.status(rid) not in ("held", "uncertain"):
                rid = "turn:" + key + ":" + uuid.uuid4().hex
                self._reserve(rid, 1, self._turns, key, rid)
            if uncertain:
                self._ledger.uncertain(rid)

    def settle_turn(self, key: str) -> None:
        with self._lock:
            rid = self._turns.pop(key, None)
            if rid is not None and self._ledger.status(rid) in ("held", "uncertain"):
                self._ledger.settle(rid, 1)

    def release_turn(self, key: str) -> None:
        with self._lock:
            rid = self._turns.pop(key, None)
            if rid is not None and self._ledger.status(rid) in ("held", "uncertain"):
                self._ledger.release(rid)

    def sweep_turns(self, active: set[str]) -> list[str]:
        """Release reservations of turns that are no longer running or held."""
        with self._lock:
            orphans = [key for key in self._turns if key not in active]
            for key in orphans:
                self.release_turn(key)
            return orphans

    # Heavy work --------------------------------------------------------

    def _heavy_used(self) -> int:
        return sum(row["units"] for row in self._leases.values())

    def _alive(self, pid: Any, birth: Any) -> bool:
        return _owner_alive(pid, birth, self._process_birth)

    def prune_dead_heavy(self) -> list[str]:
        """Drop waiters and holders whose owner process is provably gone."""
        with self._lock:
            gone = [row["ticket"] for row in self._waiting if not self._alive(row["pid"], row["birth"])]
            self._waiting = [row for row in self._waiting if row["ticket"] not in gone]
            for ticket, row in list(self._leases.items()):
                if not self._alive(row.get("pid"), row.get("birth")):
                    if self._ledger.status(row["rid"]) in ("held", "uncertain"):
                        self._ledger.release(row["rid"])
                    del self._leases[ticket]
                    gone.append(ticket)
            return gone

    def queue_heavy(self, owner: str, units: int, *, pid: int | None = None) -> str:
        """Join the heavy queue; an oversize request is clamped to the headroom."""
        units = max(1, min(int(units), self.policy.heavy_headroom))
        birth = None
        if pid is not None and self._process_birth is not None:
            try:
                birth = list(self._process_birth(pid))
            except (OSError, ValueError, IndexError):
                birth = None
        with self._lock:
            ticket = "heavy-" + uuid.uuid4().hex
            self._waiting.append({"ticket": ticket, "owner": owner, "units": units, "pid": pid, "birth": birth})
            return ticket

    def claim_heavy(self, ticket: str) -> bool:
        """Take the ticket's units now if it is first in line and they fit."""
        with self._lock:
            if ticket in self._leases:
                return True
            self.prune_dead_heavy()
            if not self._waiting or self._waiting[0]["ticket"] != ticket:
                if not any(row["ticket"] == ticket for row in self._waiting):
                    raise KeyError("heavy ticket is not queued (its owner was gone, or it was released)")
                return False
            row = self._waiting[0]
            if self._heavy_used() + row["units"] > self.policy.heavy_headroom:
                return False
            pid, birth = row["pid"], row["birth"]
            rid = "heavy:%s:%s:%s" % ("-" if pid is None else pid,
                                      "-" if birth is None else "-".join(str(value) for value in birth),
                                      uuid.uuid4().hex)
            lease = {"rid": rid, "units": row["units"], "owner": row["owner"], "pid": pid, "birth": birth}
            self._reserve(rid, row["units"], self._leases, ticket, lease)
            self._waiting.pop(0)
            return True

    def release_heavy(self, ticket: str) -> None:
        with self._lock:
            self._waiting = [row for row in self._waiting if row["ticket"] != ticket]
            row = self._leases.pop(ticket, None)
            if row is not None and self._ledger.status(row["rid"]) in ("held", "uncertain"):
                self._ledger.settle(row["rid"], row["units"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"pool": self._ledger.totals(),
                    "policy": {"turn_units": self.policy.turn_units, "manager_reserve": self.policy.manager_reserve,
                               "heavy_headroom": self.policy.heavy_headroom, "worker_floor": self.policy.worker_floor},
                    "turns": {"reserved": len(self._turns)},
                    "heavy": {"used": self._heavy_used(), "limit": self.policy.heavy_headroom,
                              "leases": sorted(self._leases), "waiting": [row["ticket"] for row in self._waiting]}}

"""The ONE running owner service: it holds the Store; every host is its client.

``ottoctl service run`` is the operator's single command (the user, or the
controller that already owns the Store). The process opens the Store once,
under its exclusive writer lock, and keeps it for its whole life. Nothing
else opens the file: a host's ``ottoctl`` writes a request into its own lane
and reads the response (see ``lanes``). The service performs every write as
the principal the lane is bound to:

* the owner lane (``<service home>/owner-lane``): operator actions, e.g.
  admitting a host (``ottoctl service admit-host``), which assigns the host's
  own orchestrator principal and creates its lane in the host's client home;
* one host lane per admitted host (``<client home>/lanes/<kind>``): the host
  principal registers and syncs drafts, activates, reads, answers escalations
  and relays owner-custody manager commands (start-manager, status, ...);
* the manager lanes of the attached project (``serve.HostOwnerService``):
  the launched manager's file lane and caller socket.

All lane work serializes on one command lock (shared with the attached
project's ExecutionHost; during a manager turn finite operations run on the
owner's pump between transport polls). The service publishes its status
(holder, generation, heartbeat, attached project, manager turn, in-flight
requests) into the service home and every host lane, so "is the owner busy?"
is a supported read (``ottoctl service status``), never an inspection of
another host's folders. Starting it starts no Due and calls no provider.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping, Optional

from herzchen.contracts import ResourceRef

from . import config as host_config
from . import lanes
from .owner import HostSession, join_host, runtime_dirs, service_store

STATUS_SCHEMA = "otto.owner-service-status.v1"
_RELAYED = object()


def owner_lane(home: Path) -> Path:
    return Path(home) / "owner-lane"


def stop_marker(home: Path) -> Path:
    return Path(home) / "run" / "service-stop"


def status_path(home: Path) -> Path:
    return Path(home) / "run" / "service.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_status(path: Path) -> dict[str, Any]:
    """Interpret a published status file: running, stale (holder gone) or not running."""
    try:
        value = lanes.read_private_json(path)
    except (OSError, ValueError) as exc:
        return {"outcome": "unavailable", "reason": str(exc), "provider_called": False}
    if value is None:
        return {"outcome": "not_running", "status_path": str(path), "provider_called": False,
                "next_action": "the operator starts the one owner service: `ottoctl --home <service home> service run`"}
    pid = (value.get("holder") or {}).get("pid")
    alive = False
    try:
        os.kill(int(pid), 0)
        alive = True
    except PermissionError:
        alive = True
    except (ProcessLookupError, TypeError, ValueError):
        alive = False
    try:
        age = time.time() - datetime.fromisoformat(value["heartbeat_at"]).timestamp()
    except (KeyError, ValueError):
        age = None
    fresh = age is not None and age <= 3 * float(value.get("heartbeat_seconds") or 1) + 2
    running = value.get("state") == "serving" and alive and fresh
    busy = bool(value.get("manager_turn_active") or (value.get("in_flight") or {}).get("lane_requests")
                or (value.get("in_flight") or {}).get("relays"))
    return {**value, "outcome": "running" if running else ("closed" if value.get("state") == "closed" else "stale"),
            "busy": busy if running else False, "heartbeat_age_seconds": None if age is None else round(age, 2),
            "holder_alive": alive, "provider_called": False}


class OwnerService:
    def __init__(self, config: Mapping[str, Any], *, adapter_factory: Optional[Callable[..., Any]] = None,
                 poll_seconds: float = 0.05, heartbeat_seconds: float = 1.0) -> None:
        self.config = dict(config)
        self.home = Path(config["home"])
        self.lock = threading.RLock()
        self.adapter_factory = adapter_factory
        self.poll_seconds, self.heartbeat_seconds = poll_seconds, heartbeat_seconds
        self.journey: Any = None
        self.store: Any = None
        self.relays: dict[str, dict[str, Any]] = {}
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.last_completed: Optional[dict[str, Any]] = None
        self.served = 0
        self.generation = 0
        self.started_at = None
        self._stopping = threading.Event()

    # -- lifecycle ------------------------------------------------------------------
    def run(self, *, emit: Callable[[Mapping[str, Any]], None], project: Optional[str] = None) -> Mapping[str, Any]:
        runtime_dirs(self.config)
        lanes.private_dir(owner_lane(self.home))
        stop = stop_marker(self.home)
        with HostSession(self.config) as root:
            # Holding the writer lock proves no other owner process is live,
            # so a retained stop marker from the previous run is stale.
            stale_stop = stop.exists()
            stop.unlink(missing_ok=True)
            self.store = root.store
            self.generation = self._next_generation()
            self.started_at = _now()
            heartbeat = threading.Thread(target=self._heartbeat, name="otto-service-status", daemon=True)
            try:
                if project:
                    self.call(lambda: self._attach(project, host_kind=None))
                self._publish()
                heartbeat.start()
                emit({"outcome": "ready", "pid": os.getpid(), "generation": self.generation,
                      "owner": self.config["owner"]["actor"], "hosts": sorted(self._host_lanes()),
                      "owner_lane": str(owner_lane(self.home)), "status": str(status_path(self.home)),
                      "stop_file": str(stop), "stale_stop_marker_removed": stale_stop,
                      "attached_project": self._attached(), "provider_called": False, "dues_started": 0})
                while not stop.exists():
                    self._poll(owner_lane(self.home), "owner", self._owner_command)
                    for kind, lane in self._host_lanes().items():
                        self._poll(lane, kind, self._host_command)
                    self._poll_relays()
                    time.sleep(self.poll_seconds)
            finally:
                self._stopping.set()
                if heartbeat.is_alive():
                    heartbeat.join(timeout=5)
                if self.journey is not None:
                    self.journey.execution_host.begin_drain()
                    self.journey.execution_host.close()
                self._publish(state="closed")
        return {"outcome": "closed", "generation": self.generation, "requests_served": self.served,
                "relays_open": len(self.relays), "provider_called": False}

    def _next_generation(self) -> int:
        path = self.home / "run" / "generation"
        try:
            value = int(path.read_text().strip()) + 1
        except (OSError, ValueError):
            value = 1
        path.write_text(str(value) + "\n")
        os.chmod(path, 0o600)
        return value

    def call(self, operation: Callable[[], Any], *, hold_during_turn: bool = False) -> Any:
        """Run one finite owner operation, serialized with every other Store write."""
        def run() -> Any:
            with service_store(self.store):
                return operation()
        journey = self.journey
        if journey is not None:
            host = journey.execution_host
            if hold_during_turn and host._external_waiting:
                return {"outcome": "held", "provider_called": False, "retry": True,
                        "reason": "a manager turn is in progress; this operation changes the running project's "
                                  "execution, so it waits until the turn settles",
                        "next_action": "check `ottoctl service status` (manager_turn_active) and repeat"}
            return host._status_read({"command": "owner-operation"}, run)
        with self.lock:
            return run()

    # -- lanes ------------------------------------------------------------------------
    def _host_lanes(self) -> dict[str, Path]:
        return {kind: Path(entry["lane"]) for kind, entry in (self.config.get("hosts") or {}).items()
                if entry.get("lane")}

    def _poll(self, lane: Path, who: str, handler: Callable[..., Any]) -> None:
        for token, path in list(lanes.requests(lane)):
            if token in self.in_flight or token in self.relays:
                continue
            pending = None
            try:
                pending = lanes.read_private_json(lane / ("pending-" + token + ".json"))
            except (OSError, ValueError):
                pending = None
            if pending and pending.get("manager_token") and pending.get("ipc"):
                # Retained relay from a previous service run: resume, never resend.
                self.relays[token] = {"lane": lane, "ipc": Path(pending["ipc"]),
                                      "manager_token": pending["manager_token"], "who": who,
                                      "command": pending.get("command")}
                continue
            self.in_flight[token] = {"lane": who, "since": _now()}
            try:
                request = lanes.read_private_json(path)
                self.in_flight[token]["command"] = [request.get("command"), request.get("sub")]
                lanes.mark_pending(lane, token, "processing", lane_principal=who)
                result = handler(who, request, token, lane)
            except Exception as exc:  # report, never crash the owner
                result = {"outcome": "error", "error": {"code": type(exc).__name__, "message": str(exc)},
                          "provider_called": False}
            finally:
                entry = self.in_flight.pop(token, {})
            self.served += 1
            self.last_completed = {"token": token, "lane": who, "command": entry.get("command"), "at": _now()}
            if result is not _RELAYED:
                lanes.respond(lane, token, result if isinstance(result, Mapping) else {"outcome": "ok", "value": result})
            self._publish()

    def _poll_relays(self) -> None:
        for token, relay in list(self.relays.items()):
            response = relay["ipc"] / ("response-" + relay["manager_token"] + ".json")
            try:
                value = json.loads(response.read_text())
            except (FileNotFoundError, ValueError):
                continue
            lanes.respond(relay["lane"], token, {**value, "relayed": {
                "from": "manager lane", "manager_request_id": relay["manager_token"], "command": relay.get("command")}})
            self.relays.pop(token, None)
            self._publish()

    def _relay(self, journey: Any, request: Mapping[str, Any], *, token: str, lane: Path, who: str,
               grant_principal: Optional[str] = None) -> Any:
        manager_token = lanes.new_token()
        if grant_principal is not None:
            journey.grant_reply(manager_token, request, grant_principal)
        lanes.mark_pending(lane, token, "relayed", manager_token=manager_token, ipc=str(journey.paths["ipc"]),
                           command=request.get("command"))
        lanes.submit(journey.paths["ipc"], request, token=manager_token)
        self.relays[token] = {"lane": lane, "ipc": journey.paths["ipc"], "manager_token": manager_token,
                              "who": who, "command": request.get("command")}
        return _RELAYED

    # -- owner (operator) commands --------------------------------------------------------
    def _owner_command(self, who: str, request: Mapping[str, Any], token: str, lane: Path) -> Any:
        command, args = request.get("command"), dict(request.get("args") or {})
        if command == "admit-host":
            return self.call(lambda: self._admit_host(args))
        if command == "attach":
            return self.call(lambda: self._attach(args["project"], host_kind=None))
        if command == "status":
            return self._status()
        return {"outcome": "unavailable", "reason": "unknown owner command " + repr(command), "provider_called": False}

    def _admit_host(self, args: Mapping[str, Any]) -> Mapping[str, Any]:
        """The owner action that admits an agent CLI host as its OWN principal."""
        from otto.agents.claude_cli import VERSION
        from otto.agents.host_profiles import profile_for_host
        kind = args["host"]
        config = host_config.load(self.home)
        client_home = Path(args.get("client_home") or self.home).absolute()
        if host_config.forbidden_runtime(client_home):
            raise host_config.HostConfigError("refusing a client home inside another host's receiving tree")
        lane = client_home / "lanes" / kind
        if kind in config.get("hosts", {}):
            entry = config["hosts"][kind]
            outcome = "replayed"
            if not entry.get("lane"):
                entry.update(lane=str(lane), client_home=str(client_home))
                host_config.write(self.home, config, replace=True)
        else:
            qualified = ([VERSION] + [v for v in args.get("qualify_versions") or () if v != VERSION]
                         if kind == "claude-code" else [])
            entry = host_config.host_entry(kind, principal=args.get("principal") or kind + "-orchestrator",
                                           launcher=args.get("launcher"), qualified_versions=qualified,
                                           model_profile=profile_for_host(kind), conversation=args.get("conversation"))
            entry.update(lane=str(lane), client_home=str(client_home))
            entry = join_host(config, entry)
            host_config.write(self.home, config, replace=True)
            outcome = "admitted"
        self.config = config
        lanes.private_dir(client_home)
        lanes.private_dir(Path(entry["lane"]))
        host_config.write_client(client_home, kind, {"principal": entry["principal"], "lane": entry["lane"],
                                                     "status": str(Path(entry["lane"]) / lanes.STATUS_FILE)})
        self._publish()
        return {"outcome": outcome, "host": entry, "client_home": str(client_home), "provider_called": False,
                "next_action": "as that host: `ottoctl --home " + str(client_home) + " whoami`"}

    # -- host commands ----------------------------------------------------------------
    def _host_command(self, kind: str, request: Mapping[str, Any], token: str, lane: Path) -> Any:
        from .cli import HOST_OPERATIONS
        if request.get("schema") != lanes.REQUEST_SCHEMA:
            raise ValueError("not an " + lanes.REQUEST_SCHEMA + " request")
        command, sub = request.get("command"), request.get("sub")
        args = {key: value for key, value in dict(request.get("args") or {}).items() if key not in {"home", "host"}}
        if (command, sub) == ("service", "ping"):
            return self._status()
        if (command, sub) == ("manager", None):
            return self._relay_manager(kind, args, token, lane)
        if (command, sub) == ("help", "read"):
            request = {"command": "read-help", **({"delivery_id": args["delivery_id"]} if args.get("delivery_id") else {})}
            return self._relay_manager(kind, {"project": args["project"], "request": request}, token, lane)
        if (command, sub) == ("help", "respond"):
            return self._relay_reply(kind, args, token, lane)
        handler = HOST_OPERATIONS.get((command, sub))
        if handler is None:
            return {"outcome": "unavailable", "provider_called": False,
                    "reason": "no host operation " + repr([command, sub])}
        namespace = argparse.Namespace(**args, home=str(self.home), host=kind)
        hold = ((command, sub) == ("project", "activate")
                or (command == "operating-setup" and args.get("operation", "read") != "read"))
        return self.call(lambda: handler(namespace), hold_during_turn=hold)

    def _journey_for(self, kind: str, project: Optional[str]) -> Any:
        if project is None:
            if self.journey is None:
                raise LookupError("no project is attached; name it with --project")
            project = self.journey.state["project_ref"]["id"]
        return self.call(lambda: self._attach(project, host_kind=kind))

    def _relay_manager(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        from otto.portfolio.manager_journey_client import read_command_status, requires_native_caller
        from .serve import HOST_SOCKET_READS
        request = dict(args.get("request") or {})
        command = request.get("command")
        if not isinstance(command, str) or requires_native_caller(command) or command in HOST_SOCKET_READS:
            raise PermissionError(repr(command) + " is identity-bearing: only a process the owner launched "
                                  "(the manager or a worker) may send it, over the caller socket")
        if command == "respond-help":
            raise PermissionError("answer an escalation with `ottoctl help respond`")
        journey = self._journey_for(kind, args.get("project"))
        if command == "command-status":
            return read_command_status(journey.paths["ipc"], request["request_id"]) or {
                "outcome": "unavailable", "terminal": False, "request_id": request["request_id"], "retry": False}
        return self._relay(journey, request, token=token, lane=lane, who=kind)

    def _relay_reply(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        journey = self._journey_for(kind, args.get("project"))
        request = {"command": "respond-help", "request_key": args["request_key"], "issue_id": args["issue_id"],
                   "authority_source": args["authority_source"], "response": args["response"],
                   "proposed_solution": args["proposed_solution"], "next_action": args["next_action"]}
        principal = self.config["hosts"][kind]["principal"]
        return self._relay(journey, request, token=token, lane=lane, who=kind, grant_principal=principal)

    def _attach(self, project: str, *, host_kind: Optional[str]) -> Any:
        """Attach one activated project's manager lanes (once; one project at a time)."""
        from .cli import _resolve_project
        from .serve import attach
        with HostSession(self.config) as session:
            record = _resolve_project(session, project)
        supervisor = ((record.payload.get("metadata") or {}).get("otto_orchestrator") or {}).get("assignment_ref") or {}
        hosts = self.config.get("hosts") or {}
        owner_kind = next((kind for kind, entry in hosts.items()
                           if (entry.get("root_assignment_ref") or {}).get("id") == supervisor.get("id")), None)
        if host_kind is not None and host_kind != owner_kind:
            raise PermissionError("project " + project + " is supervised by another principal, not this host's")
        if self.journey is not None:
            if self.journey.state["project_ref"]["id"] == record.ref.id:
                return self.journey
            raise RuntimeError("this owner service has project " + self.journey.run_id + " attached; one project's "
                               "manager lanes at a time (restart with `service run --project`)")
        if owner_kind is None:
            raise LookupError("project " + project + " has no admitted host supervising it")
        session = HostSession(self.config, host=hosts[owner_kind], project_ids=(record.ref.id,)).__enter__()
        self.journey = attach(session, record, command_lock=self.lock, adapter_factory=self.adapter_factory)
        self._publish()
        return self.journey

    def _attached(self) -> Optional[dict[str, Any]]:
        if self.journey is None:
            return None
        return {"project_id": self.journey.state["project_ref"]["id"], "run_id": self.journey.run_id,
                "manager": self.journey.state["manager"], "manager_ipc": str(self.journey.paths["ipc"]),
                "caller_socket": str(self.journey.paths["socket"])}

    # -- status -------------------------------------------------------------------------
    def _status(self, state: str = "serving") -> dict[str, Any]:
        journey = self.journey
        queued = 0
        if journey is not None:
            queued = sum(1 for _ in lanes.requests(journey.paths["ipc"]))
        return {"schema": STATUS_SCHEMA, "state": state, "outcome": "serving" if state == "serving" else state,
                "holder": {"pid": os.getpid(), "owner_actor": self.config["owner"]["actor"],
                           "started_at": self.started_at},
                "generation": self.generation, "heartbeat_at": _now(), "heartbeat_seconds": self.heartbeat_seconds,
                "store": {"authority": self.config["store"]["authority"],
                          "domain_descriptor_digest": self.config["store"].get("domain_descriptor_digest")},
                "hosts": sorted((self.config.get("hosts") or {})), "attached_project": self._attached(),
                "manager_turn_active": bool(journey is not None and journey.execution_host._external_waiting),
                "in_flight": {"lane_requests": [{"token": t, **v} for t, v in list(self.in_flight.items())],
                              "relays": [{"token": t, "lane": v["who"], "command": v.get("command")}
                                         for t, v in list(self.relays.items())],
                              "manager_lane_queued": queued},
                "last_completed": self.last_completed, "requests_served": self.served, "provider_called": False}

    def _publish(self, state: str = "serving") -> None:
        value = self._status(state)
        lanes.atomic_json(status_path(self.home), value)
        for lane in self._host_lanes().values():
            if lane.is_dir():
                lanes.atomic_json(lane / lanes.STATUS_FILE, value)

    def _heartbeat(self) -> None:
        while not self._stopping.wait(self.heartbeat_seconds):
            try:
                self._publish()
            except OSError:
                pass

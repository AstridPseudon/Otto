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
* the manager lanes of each attached project (``serve.HostOwnerService``):
  that launched manager's file lane and caller socket.

Finite lane work serializes on one command lock shared by all project
ExecutionHosts. Native waits release it; owner callbacks reacquire it. The
service publishes its status
(holder, generation, heartbeat, attached projects, active/queued turns, in-flight
requests) into the service home and every host lane, so "is the owner busy?"
is a supported read (``ottoctl service status``), never an inspection of
another host's folders. Starting it starts no Due and calls no provider.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from contextlib import contextmanager
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
_DEFAULT_PRESENCE = object()


def owner_lane(home: Path) -> Path:
    return Path(home) / "owner-lane"


def stop_marker(home: Path) -> Path:
    return Path(home) / "run" / "service-stop"


def _requested_closure(home: Path) -> Optional[dict[str, str]]:
    """Read the operator's optional explanation for closing the service."""
    try:
        value = lanes.read_private_json(stop_marker(home))
    except (OSError, ValueError):
        return None
    if not isinstance(value, Mapping):
        return None
    closure = {key: value[key] for key in ("reason", "expected_return")
               if isinstance(value.get(key), str) and value[key].strip()}
    return closure or None


def with_lane_advice(status: Mapping[str, Any], *, lane: str, owner_actor: Optional[str] = None,
                     service_home: Optional[Path] = None) -> dict[str, Any]:
    """Add safe next-step advice for the owner or an admitted client lane."""
    result = dict(status)
    actor = owner_actor or (status.get("holder") or {}).get("owner_actor") or "owner"
    outcome = status.get("outcome")
    closure = status.get("closure") if isinstance(status.get("closure"), Mapping) else {}
    reason = closure.get("reason") if isinstance(closure.get("reason"), str) else None
    if outcome in {"closed", "draining", "stale", "not_running", "unavailable"}:
        result["reason"] = reason or {
            "closed": "the owner service closed",
            "draining": "the owner service is draining",
            "stale": "the owner process is not responding",
            "not_running": "the owner service is not running",
            "unavailable": str(status.get("reason") or "owner status is unavailable"),
        }.get(outcome, "the owner service is not running")
        restart_home = service_home or (Path(str(status["service_home"])) if status.get("service_home") else None)
        if lane == "owner" and restart_home is not None:
            result["restart_command"] = "ottoctl --home " + str(restart_home) + " service run"
        elif lane == "client" and restart_home is not None:
            result["restart_command"] = "ottoctl --home " + str(restart_home) + " service run"
    if lane == "client":
        result["owner_actor"] = actor
        if outcome in {"closed", "draining", "stale", "not_running", "unavailable"}:
            guidance = ("the owner service is owned by " + actor + "; ask that owner to restore it and check "
                        "`ottoctl service status`")
            if result.get("restart_command"):
                guidance += "; restart command: `" + result["restart_command"] + "`"
            result["next_action"] = guidance
    elif lane == "owner":
        if outcome == "draining":
            result["next_action"] = "wait for the owner service to finish draining; check `ottoctl service status`"
        elif outcome in {"closed", "stale", "not_running", "unavailable"}:
            home = str(service_home or "<service home>")
            command = "ottoctl --home " + home + " service run"
            result["restart_command"] = command
            result["next_action"] = "the owner starts the one service: `" + command + "`"
    return result


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
    draining = value.get("state") == "draining" and alive and fresh
    busy = bool(value.get("manager_turn_active") or (value.get("in_flight") or {}).get("lane_requests")
                or (value.get("in_flight") or {}).get("relays"))
    outcome = "running" if running else "draining" if draining else "closed" if value.get("state") == "closed" else "stale"
    return {**value, "outcome": outcome,
            "busy": busy if running or draining else False, "heartbeat_age_seconds": None if age is None else round(age, 2),
            "holder_alive": alive, "provider_called": False}


class OwnerService:
    def __init__(self, config: Mapping[str, Any], *, adapter_factory: Optional[Callable[..., Any]] = None,
                 poll_seconds: float = 0.05, heartbeat_seconds: float = 1.0,
                 max_active_manager_turns: Optional[int] = None,
                 presence_prover: Any = _DEFAULT_PRESENCE) -> None:
        self.config = dict(config)
        self.home = Path(config["home"])
        self.lock = threading.RLock()
        self.adapter_factory = adapter_factory
        if presence_prover is _DEFAULT_PRESENCE:
            from .presence import LocalAuthenticationProver
            presence_prover = LocalAuthenticationProver()
        self.presence_prover = presence_prover
        self.poll_seconds, self.heartbeat_seconds = poll_seconds, heartbeat_seconds
        self.journey: Any = None
        # A project is attached once and keeps its own manager service and
        # authentication scope.  The singular ``journey`` remains a
        # compatibility view of the first attached project for older callers.
        self.journeys: dict[str, Any] = {}
        self._project_sessions: dict[str, HostSession] = {}
        configured_limit = (max_active_manager_turns if max_active_manager_turns is not None
                            else self.config.get("max_active_manager_turns", 3))
        # Default 3 suits a small machine; 16 is the most project views one
        # owner composes (ProjectServices' bound), so it is the ceiling here.
        if type(configured_limit) is not int or not 1 <= configured_limit <= 16:
            raise ValueError("max_active_manager_turns must be an integer from 1 through 16")
        self.max_active_manager_turns = configured_limit
        self._turn_slots = threading.BoundedSemaphore(self.max_active_manager_turns)
        self._turn_lock = threading.Lock()
        self._turn_active: set[str] = set()
        self._turn_queued: dict[str, int] = {}
        self._turn_context = threading.local()
        self._draining_projects: set[str] = set()
        self.store: Any = None
        self.relays: dict[str, dict[str, Any]] = {}
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.last_completed: Optional[dict[str, Any]] = None
        self.served = 0
        self.generation = 0
        self.started_at = None
        self._stopping = threading.Event()
        self._dispatch_context = threading.local()

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
                for journey in list(self.journeys.values()):
                    journey.execution_host.begin_drain()
                for journey in list(self.journeys.values()):
                    journey.execution_host.close()
                for session in self._project_sessions.values():
                    session.__exit__(None, None, None)
                self._project_sessions.clear()
                self._publish(state="closed")
        return {"outcome": "closed", "generation": self.generation, "requests_served": self.served,
                "relays_open": len(self.relays), "owner_exit_requested": stop.exists(),
                "closure": _requested_closure(self.home), "provider_called": False}

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
        project_id = getattr(self._dispatch_context, "project_id", None)
        with self.lock:
            journey = self.journeys.get(project_id) if project_id else None
            if journey is None and project_id:
                journey = next((item for item in self.journeys.values() if item.run_id == project_id), None)
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

    def _poll(self, lane: Path, who: str, handler: Callable[..., Any], *,
              allowed_commands: Optional[set[str]] = None) -> None:
        for token, path in list(lanes.requests(lane)):
            if token in self.in_flight or token in self.relays:
                continue
            request = None
            if allowed_commands is not None:
                try:
                    request = lanes.read_private_json(path)
                except (OSError, ValueError):
                    # In a read-only poll, even malformed retained work stays
                    # untouched for its ordinary owner-side recovery path.
                    continue
                if not isinstance(request, Mapping) or request.get("command") not in allowed_commands:
                    continue
            if request is None:
                try:
                    request = lanes.read_private_json(path)
                except (OSError, ValueError):
                    request = None
            if isinstance(request, Mapping) and self._defer_request(lane, who, token, request):
                continue
            pending = None
            try:
                pending = lanes.read_private_json(lane / ("pending-" + token + ".json"))
            except (OSError, ValueError):
                pending = None
            if pending and pending.get("manager_token") and pending.get("ipc"):
                if allowed_commands is not None:
                    continue
                # Retained relay from a previous service run: resume, never resend.
                self.relays[token] = {"lane": lane, "ipc": Path(pending["ipc"]),
                                      "manager_token": pending["manager_token"], "who": who,
                                      "command": pending.get("command")}
                continue
            if allowed_commands is None:
                try:
                    request = lanes.read_private_json(path)
                except ValueError:
                    # A writer that does not link its request into place may still
                    # be writing: retry on the next poll, answer only if it stays bad.
                    if time.time() - path.stat().st_mtime < 10:
                        continue
                    request = None
            # A held owner may answer a narrow read lane while retaining every
            # other request byte-for-byte. Filter before claiming it, creating
            # a pending receipt, or invoking any handler.
            self.in_flight[token] = {"lane": who, "since": _now()}
            prior_project = getattr(self._dispatch_context, "project_id", None)
            args = (request or {}).get("args") or {}
            if who == "owner" and (request or {}).get("command") == "portfolio-operation":
                args = args.get("args") or {}
            project_id = args.get("project") if isinstance(args, Mapping) else None
            if project_id is None and isinstance(args, Mapping) and isinstance(args.get("request"), Mapping):
                project_id = args["request"].get("project")
            self._dispatch_context.project_id = project_id
            try:
                if request is None:
                    raise ValueError("the request is not a JSON object")
                self.in_flight[token]["command"] = [request.get("command"), request.get("sub")]
                lanes.mark_pending(lane, token, "processing", lane_principal=who)
                result = handler(who, request, token, lane)
            except Exception as exc:  # report, never crash the owner
                result = {"outcome": "error", "error": {"code": type(exc).__name__, "message": str(exc)},
                          "provider_called": False}
            except KeyboardInterrupt:
                raise
            except BaseException as exc:  # a request's SystemExit (e.g. argparse) must not close the shared owner
                result = {"outcome": "error", "error": {"code": type(exc).__name__,
                          "message": "the request exited (%s); usage is answered client-side" % (exc,)},
                          "provider_called": False}
            finally:
                self._dispatch_context.project_id = prior_project
                entry = self.in_flight.pop(token, {})
            if (who == "owner" and (request or {}).get("command") == "admit"
                    and isinstance(result, Mapping) and result.get("outcome") == "held"
                    and result.get("retry")):
                # Dispatch may open after _defer_request's check. Keep the
                # exact request/token live and let the next poll retry it once
                # the boundary closes; presence has not been checked yet.
                (lane / ("pending-" + token + ".json")).unlink(missing_ok=True)
                self._publish()
                continue
            self.served += 1
            self.last_completed = {"token": token, "lane": who, "command": entry.get("command"), "at": _now()}
            if result is not _RELAYED:
                lanes.respond(lane, token, result if isinstance(result, Mapping) else {"outcome": "ok", "value": result})
            self._publish()

    def _defer_request(self, lane: Path, who: str, token: str, request: Mapping[str, Any]) -> bool:
        """Leave operator admission queued until every dispatch boundary is closed.

        Admission must not prompt for presence and then return ``held``: the
        operator would have to repeat the request (and authenticate again).
        Deferring before claiming the lane keeps its exact request and key for
        the ordinary owner path once dispatch settles.
        """
        if who == "owner" and request.get("command") == "admit":
            with self.lock:
                dispatching = any(journey.execution_host._external_waiting
                                  for journey in self.journeys.values())
            return bool(dispatching)
        return False

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
        command, raw_args = request.get("command"), request.get("args") or {}
        if command == "admit":
            return self.call(lambda: self._admit_revision(raw_args), hold_during_turn=True)
        args = dict(raw_args)
        if command == "admit-host":
            return self.call(lambda: self._admit_host(args))
        if command == "attach":
            return self.call(lambda: self._attach(args["project"], host_kind=None))
        if command in {"drain", "drain-project"}:
            return self._drain_project(str(args["project"]))
        if command == "status":
            return self._status()
        if command == "portfolio-operation":
            from .cli import HOST_OPERATIONS
            from .portfolio import OWNER_PORTFOLIO_COMMANDS, OWNER_PROJECT_OPERATIONS
            # Owner custody is established by this lane, never a client argument.
            operation = (args.get("command"), args.get("sub"))
            if operation == ("portfolio", None):
                # Any other portfolio subcommand (admit, complete-task, apply, ...) is refused, not run with owner authority.
                first = (dict(args.get("args") or {}).get("portfolio_args") or [None])[0]
                if not isinstance(first, str) or first not in OWNER_PORTFOLIO_COMMANDS:
                    raise PermissionError("the owner lane admits only save, show and read for the portfolio command")
            elif operation not in OWNER_PROJECT_OPERATIONS:
                raise PermissionError("operation is not an owner portfolio command")
            values = {key: value for key, value in dict(args.get("args") or {}).items()
                      if key not in {"home", "host", "owner_authorized", "service_status", "project_operation"}}
            portfolio = values.get("portfolio")
            entries = [entry for entry in self.config.get("hosts", {}).values()
                       if entry.get("portfolio_ref", {}).get("id") == portfolio]
            if len(entries) != 1:
                raise LookupError("%d admitted portfolios match %r: name exactly one admitted portfolio with --portfolio"
                                  % (len(entries), portfolio))
            namespace = argparse.Namespace(**values, home=str(self.home), host=entries[0]["kind"],
                owner_authorized=True, service_status=self._status(), project_operation=operation[1])
            result = self.call(lambda: self._run_operation(HOST_OPERATIONS[operation], namespace, operation),
                               hold_during_turn=operation == ("project", "activate"))
            if operation == ("project", "detach") and result.get("outcome") not in {"error", "held"}:
                drain = self._drain_project(str(values["project"]))
                return {**result, "service_drain": drain}
            return result
        return {"outcome": "unavailable", "reason": "unknown owner command " + repr(command), "provider_called": False}

    def _admit_revision(self, args: Mapping[str, Any]) -> Mapping[str, Any]:
        """Prove presence here, then write as the installation's operator."""
        from .owner import HostSession
        from .presence import PresenceResult
        from otto.portfolio.admit import admit_task

        if not isinstance(args, Mapping):
            args = {}
        allowed = {"task_ref", "revision", "review_ref", "request_key"}
        proof = "not_run"
        outcome = "refused"
        task, review = args.get("task_ref"), args.get("review_ref")
        try:
            if set(args) != allowed:
                raise PermissionError("admit accepts only task_ref, revision, review_ref and request_key")
            if (not isinstance(task, Mapping) or not isinstance(review, Mapping)
                    or not isinstance(args["revision"], str) or not args["revision"].strip()
                    or not isinstance(args["request_key"], str) or not args["request_key"].strip()):
                raise ValueError("admit requires exact task, revision, review and request key")
            task_ref, review_ref = ResourceRef.from_dict(task), ResourceRef.from_dict(review)
            if (task_ref.authority != self.config["store"]["authority"] or task_ref.kind != "work.task"
                    or review_ref.authority != task_ref.authority or review_ref.revision is None):
                raise ValueError("admit requires a local task and exact local review")
            reason = f"Admit Otto task {task_ref.id} at revision {args['revision'][:12]}"
            try:
                result = (self.presence_prover.prove(reason=reason, timeout_seconds=30)
                          if self.presence_prover is not None else PresenceResult("unavailable"))
            except TimeoutError:
                result = PresenceResult("timeout")
            except Exception:
                result = PresenceResult("unavailable")
            proof = result.status if isinstance(result, PresenceResult) else "unavailable"
            if proof != "approved":
                outcome = "rejected"
                return {"outcome": outcome, "error": {"code": "presence_" + proof,
                                                       "message": "local operator presence was not proved"},
                        "provider_called": False, "dispatch": False}
            with HostSession(self.config) as session:
                answer = admit_task(session, task_ref=task_ref, revision=args["revision"],
                                    review_ref=review_ref, request_key=args["request_key"],
                                    actor=session.owner.operator_actor)
            outcome = answer["outcome"]
            return {**answer, "provider_called": False}
        finally:
            self._admission_log({"task": task.get("id") if isinstance(task, Mapping) else None,
                                 "revision": args.get("revision"),
                                 "review": review.get("id") if isinstance(review, Mapping) else None,
                                 "prover_result": proof, "outcome": outcome})

    def _admission_log(self, entry: Mapping[str, Any]) -> None:
        path = self.home / "run" / "operator-admission.jsonl"
        data = (json.dumps({"at": _now(), **entry}, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

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
            if entry["principal"] == config["operator"]["actor"]:
                raise host_config.HostConfigError("host principal must differ from the operator principal")
            entry.update(lane=str(lane), client_home=str(client_home))
            entry = join_host(config, entry)
            host_config.write(self.home, config, replace=True)
            outcome = "admitted"
        self.config = config
        lanes.private_dir(client_home)
        lanes.private_dir(Path(entry["lane"]))
        host_config.write_client(client_home, kind, {"principal": entry["principal"], "lane": entry["lane"],
                                                     "owner_actor": self.config["owner"]["actor"],
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
        args = {key: value for key, value in dict(request.get("args") or {}).items()
                if key not in {"home", "host", "owner_authorized", "service_status", "project_operation"}}
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
        namespace = argparse.Namespace(**args, home=str(self.home), host=kind,
            owner_authorized=False, service_status=self._status(), project_operation=sub)
        hold = ((command, sub) == ("project", "activate")
                or (command == "operating-setup" and args.get("operation", "read") != "read"))
        result = self.call(lambda: self._run_operation(handler, namespace, (command, sub)), hold_during_turn=hold)
        if (command, sub) == ("project", "detach") and result.get("outcome") not in {"error", "held"}:
            return {**result, "service_drain": self._drain_project(str(args["project"]))}
        return result

    def _run_operation(self, handler: Callable[..., Any], namespace: Any, operation: tuple) -> Any:
        """Run under the shared command lock, fencing detach against admission."""
        if operation == ("project", "detach"):
            namespace.service_status = self._status()
        result = handler(namespace)
        if operation == ("project", "detach") and result.get("outcome") == "detached":
            project_id = result["project_ref"]["id"]
            journey = self.journeys.get(project_id)
            if journey is not None:
                self._draining_projects.add(project_id)
                journey.execution_host.begin_drain()
        return result

    def _journey_for(self, kind: str, project: Optional[str]) -> Any:
        if project is None:
            if not self.journeys:
                raise LookupError("no project is attached; name it with --project")
            if len(self.journeys) != 1:
                raise ValueError("--project is required when multiple projects are attached")
            project = next(iter(self.journeys))
        return self.call(lambda: self._attach(project, host_kind=kind))

    def _relay_manager(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        from otto.portfolio.manager_journey_client import read_command_status, requires_native_caller
        from .serve import HOST_SOCKET_READS
        request = dict(args.get("request") or {})
        command = request.get("command")
        if command in {"status", "read-help"}:
            # The host lane is an authenticated supervisor, not a native
            # manager. Keep native ingress strict and project reads separate.
            journey = self._journey_for(kind, args.get("project"))
            return self.call(lambda: self._supervisor_read(kind, journey, request))
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

    def _supervisor_read(self, kind: str, journey: Any, request: Mapping[str, Any]) -> Any:
        command = request["command"]
        allowed = {"status": {"command"}, "read-help": {"command", "delivery_id"}}
        if set(request) - allowed[command]:
            raise PermissionError("supervisor read cannot override project or actor")
        entry = self.config["hosts"][kind]
        supervisor = journey.help_delivery.readers.current_supervisor(journey.state["project_ref"])
        if (supervisor is None or supervisor.principal != entry["principal"]
                or supervisor.ref.to_dict() != entry["root_assignment_ref"]
                or supervisor.generation != entry["root_generation"]):
            raise PermissionError("host is not this project's current accountable supervisor")
        if command == "status":
            result = journey.execution_host.handler._status(request)
        elif request.get("delivery_id"):
            result = journey.portfolio._issue_loop().recover_delivery(
                project_ref=journey.state["project_ref"], delivery_id=request["delivery_id"])
        else:
            result = journey.portfolio.read_issues(project_ref=journey.state["project_ref"])
        return {**result, "supervisor_ref": supervisor.ref.to_dict(),
                "supervisor_principal": supervisor.principal, "read_only": True,
                "relayed": {"from": "manager lane", "authority": "authenticated supervisor projection",
                            "command": command}}

    def _relay_reply(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        journey = self._journey_for(kind, args.get("project"))
        request = {"command": "respond-help", "request_key": args["request_key"], "issue_id": args["issue_id"],
                   "authority_source": args["authority_source"], "response": args["response"],
                   "proposed_solution": args["proposed_solution"], "next_action": args["next_action"]}
        principal = self.config["hosts"][kind]["principal"]
        return self._relay(journey, request, token=token, lane=lane, who=kind, grant_principal=principal)

    def _attach(self, project: str, *, host_kind: Optional[str]) -> Any:
        """Attach one activated project's isolated manager lanes once."""
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
        if owner_kind is None:
            raise LookupError("project " + project + " has no admitted host supervising it")
        project_id = record.ref.id
        with self.lock:
            if project_id in self._draining_projects:
                raise RuntimeError("project " + project + " is draining; retry after service status clears it")
            if project_id in self.journeys:
                return self.journeys[project_id]
        session = HostSession(self.config, host=hosts[owner_kind], project_ids=(project_id,)).__enter__()
        journey = attach(session, record, command_lock=self.lock, adapter_factory=self.adapter_factory,
                         turn_admission=lambda: self._manager_turn(project_id))
        with self.lock:
            self._project_sessions[project_id] = session
            self.journeys[project_id] = journey
            if self.journey is None:
                self.journey = journey
        self._publish()
        return journey

    @contextmanager
    def _manager_turn(self, project_id: str):
        """Bound provider-bearing manager dispatches across all project lanes."""
        nested = set(getattr(self._turn_context, "projects", ()))
        if project_id in nested:
            # A retained worker/help result can be serviced by this same
            # project's owner pump during the current turn. Reuse its slot.
            yield
            return
        # Publish admission under the same fence as detach's activity check.
        # Release it before waiting for capacity, so other projects can settle.
        with self.lock:
            if project_id in self._draining_projects:
                raise RuntimeError("project " + project_id + " is draining")
            with self._turn_lock:
                self._turn_queued[project_id] = self._turn_queued.get(project_id, 0) + 1
        # Wait for a slot without blocking a drain or stop of this project.
        while not self._turn_slots.acquire(timeout=0.2):
            if project_id in self._draining_projects or self._stopping.is_set():
                with self._turn_lock:
                    waiting = self._turn_queued.get(project_id, 1) - 1
                    if waiting:
                        self._turn_queued[project_id] = waiting
                    else:
                        self._turn_queued.pop(project_id, None)
                raise RuntimeError("project " + project_id + " is draining; its queued manager turn was not started")
        with self._turn_lock:
            waiting = self._turn_queued.get(project_id, 1) - 1
            if waiting:
                self._turn_queued[project_id] = waiting
            else:
                self._turn_queued.pop(project_id, None)
            self._turn_active.add(project_id)
        nested.add(project_id)
        self._turn_context.projects = nested
        try:
            yield
        finally:
            nested.remove(project_id)
            self._turn_context.projects = nested
            with self._turn_lock:
                self._turn_active.discard(project_id)
            self._turn_slots.release()

    def _drain_project(self, project: str) -> Mapping[str, Any]:
        """Stop accepting work on one project's lanes and close its retained view."""
        from .cli import _resolve_project
        with self.lock, service_store(self.store):
            with HostSession(self.config) as session:
                record = _resolve_project(session, project)
            project_id = record.ref.id
            journey = self.journeys.get(project_id)
            if journey is not None:
                self._draining_projects.add(project_id)
                self.journeys.pop(project_id, None)
        if journey is None:
            return {"outcome": "already_detached", "project_id": project_id, "provider_called": False}
        # Do not hold the shared Store lock while close joins command threads;
        # they may be finishing a finite owner callback under that lock.
        journey.execution_host.begin_drain()
        journey.execution_host.close()
        session = self._project_sessions.pop(project_id, None)
        if session is not None:
            session.__exit__(None, None, None)
        with self.lock:
            self._draining_projects.discard(project_id)
            if self.journey is journey:
                self.journey = next(iter(self.journeys.values()), None)
        self._publish()
        return {"outcome": "drained", "project_id": project_id, "provider_called": False}

    def _attached(self) -> Optional[dict[str, Any]]:
        with self.lock:
            journey = self.journey
        if journey is None:
            return None
        return {"project_id": journey.state["project_ref"]["id"], "run_id": journey.run_id,
                "manager": journey.state["manager"], "manager_ipc": str(journey.paths["ipc"]),
                "caller_socket": str(journey.paths["socket"])}

    def _attached_projects(self) -> list[dict[str, Any]]:
        with self.lock:
            journeys = dict(self.journeys)
            draining = set(self._draining_projects)
        rows = [{"project_id": project_id, "run_id": journey.run_id,
                 "manager": journey.state["manager"], "manager_ipc": str(journey.paths["ipc"]),
                 "caller_socket": str(journey.paths["socket"])}
                for project_id, journey in sorted(journeys.items())]
        rows.extend({"project_id": project_id, "state": "draining"} for project_id in sorted(draining))
        return rows

    # -- status -------------------------------------------------------------------------
    def _status(self, state: str = "serving", closure: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
        projects = self._attached_projects()
        with self.lock:
            journeys = dict(self.journeys)
        lane_queued = {project_id: sum(1 for _ in lanes.requests(journey.paths["ipc"]))
                       for project_id, journey in journeys.items()}
        with self._turn_lock:
            manager_turns = {"active": len(self._turn_active), "active_projects": sorted(self._turn_active),
                "queued": sum(self._turn_queued.values()), "queued_by_project": dict(self._turn_queued),
                "limit": self.max_active_manager_turns}
        value = {"schema": STATUS_SCHEMA, "state": state, "outcome": "serving" if state == "serving" else state,
                "service_home": str(self.home),
                "holder": {"pid": os.getpid(), "owner_actor": self.config["owner"]["actor"],
                           "started_at": self.started_at},
                "generation": self.generation, "heartbeat_at": _now(), "heartbeat_seconds": self.heartbeat_seconds,
                "store": {"authority": self.config["store"]["authority"],
                          "domain_descriptor_digest": self.config["store"].get("domain_descriptor_digest")},
                "hosts": sorted((self.config.get("hosts") or {})), "attached_project": self._attached(),
                "attached_projects": projects, "projects": projects, "manager_turns": manager_turns,
                "manager_turn_active": manager_turns["active"] > 0,
                "in_flight": {"lane_requests": [{"token": t, **v} for t, v in list(self.in_flight.items())],
                              "relays": [{"token": t, "lane": v["who"], "command": v.get("command")}
                                         for t, v in list(self.relays.items())],
                              "manager_lane_queued": lane_queued},
                "last_completed": self.last_completed, "requests_served": self.served, "provider_called": False}
        if closure:
            value["closure"] = dict(closure)
        return value

    def _publish(self, state: str = "serving") -> None:
        value = self._status(state, closure=_requested_closure(self.home))
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

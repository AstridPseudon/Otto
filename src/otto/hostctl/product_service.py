"""The product start of ``ottoctl service run``: one owner over one Store.

This composes the same owner the live shared-operating wrapper composes, from
the supported owner APIs only: ONE open Store, ONE shared bounded
``ExecutionHost``, one ``ManagerJourneyService`` view per activated project
behind the ``ProjectServices`` router, the router's startup settlement BEFORE
the host starts, the dispatch hold, a startup-refusal record with exit 78, and
a close that releases the host and the Store before the status reads closed.
Retained runner commands are admitted only after recovery and host custody.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import subprocess
import threading
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, Mapping, Optional
from urllib.parse import unquote

from herzchen.fleet.capacity import CapacityPolicy
from herzchen.fleet.labs import LabFleet
from herzchen.fleet.runner.store import ResultStore
from herzchen.fleet.tools.facade import SettlingOwnerPort as _OwnerExecutorPort

from . import lanes
from .owner import HostSession, host_domains, runtime_dirs, service_store
from .project_service import ProjectOwnerService
from .serve import HostOwnerService, request_digest, socket_path
from .service import _RELAYED, _requested_closure, owner_lane, stop_marker, status_path

EXIT_STARTUP_REFUSED = 78
REFUSAL_SCHEMA = 'otto.owner-startup-refusal.v1'
CLOSEOUT_RECORD_LIMIT = 100
GRANT_SCHEMA = 'otto.shared-lane-grant.v1'
MAX_PROJECT_VIEWS = 16
FIELDS = {name: (name,) for name in ('schedule_id', 'project_ref', 'owner', 'interval_seconds', 'stop_state')}


class StartupStopped(RuntimeError):
    """An explicit stop was requested while the owner was still composing."""


def _start_owner_host(owner: Any) -> None:
    """Start serving first, then retry landed-lab cleanup under owner custody."""
    owner.host.start()
    if owner.host._owns_owner_file and owner.fleet_registry is not None:
        owner.fleet_registry.startup_landed_sweep = owner.fleet_registry.sweep_landed_at_start()
    runner = getattr(owner, 'runner', None)
    if runner is not None and not owner.hold_dispatch:
        if not owner.host._owns_owner_file:
            raise RuntimeError('runner admission requires host owner-file custody')
        runner.start()


def capacity_policy(config: Mapping[str, Any]) -> CapacityPolicy:
    """The pool's per-role limits from the installation; defaults when absent."""
    if 'capacity' not in config:
        return CapacityPolicy()
    raw = config['capacity']
    allowed = {'turn_units', 'manager_reserve', 'heavy_headroom', 'worker_floor'}
    if not isinstance(raw, Mapping) or set(raw) - allowed:
        raise ValueError('capacity must name only ' + ', '.join(sorted(allowed)))
    return CapacityPolicy(**raw)


def observe_project_schedules(owner: Any, project_id: str) -> dict[str, Any]:
    """Finite owner-only observation of one project's Due records; no recovery, no mutation."""
    if not isinstance(project_id, str) or not project_id:
        raise PermissionError('exact project identity required')
    actor = owner.owner_actor.actor
    reader = owner.store.consumer()
    refs = reader.find_identity_refs(kind='otto.due-record', payload_matches={('project_ref',): project_id})
    coverage = {'authority': owner.store.authority, 'project_id': project_id,
                'source': 'complete project-scoped public Due list', 'record_count': len(refs),
                'observed_at': datetime.now(timezone.utc).isoformat(), 'complete': False}
    unavailable = {'mode': 'unknown', 'pm_owned_schedule_ids': None, 'unknown_ownership': True,
                   'coverage': coverage, 'shared_records': [], 'records_modified': False, 'provider_called': False}
    # Bound the read before projecting: an oversize project is unknown, never partially trusted.
    if len(refs) > CLOSEOUT_RECORD_LIMIT:
        return {**unavailable, 'reason': 'project Due metadata exceeds finite 100-record bound'}
    rows = reader.project_identity_fields_for_refs(list(refs), fields=FIELDS, max_refs=100,
                                                   max_projection_bytes=32768)
    if len(rows) != len(refs) or any(row['state'] != 'available' for row in rows):
        return {**unavailable, 'reason': 'project Due metadata missing, stale or over bound'}
    owned, shared, unknown = [], [], False
    for ref, row in zip(refs, rows):
        fields, present = row['fields'], row.get('present') or {}
        if (fields.get('schedule_id') != ref.id or fields.get('project_ref') != project_id
                or not all(present.get(name) for name in FIELDS)
                or not isinstance(fields.get('owner'), str)
                or fields.get('stop_state') not in {'active', 'stopped', 'completed'}
                or (fields['interval_seconds'] is not None
                    and (type(fields['interval_seconds']) is not int or fields['interval_seconds'] <= 0))):
            unknown = True
            continue
        # The PM recurring-schedule ownership contract: finite native turns are
        # preserved as shared records and never settled or captured here.
        recurring = fields['interval_seconds'] is not None
        if recurring and fields['owner'] != actor:
            unknown = True
        if recurring and fields['owner'] == actor and fields['stop_state'] != 'completed':
            owned.append(ref.id)
        else:
            shared.append({'schedule_id': ref.id, 'status': 'preserved'})
    coverage['complete'] = not unknown
    return {'mode': 'unknown' if unknown else ('owned-schedule' if owned else 'no-owned-schedule'),
            'pm_owned_schedule_ids': owned, 'unknown_ownership': unknown, 'coverage': coverage,
            'shared_records': shared, 'records_modified': False, 'provider_called': False}


def closeout_observer(owner: Any, expected_project_id: str) -> Callable[[str], dict[str, Any]]:
    """A view's observer: it answers only for the one project its view was composed for."""
    def observe(project_id: str) -> dict[str, Any]:
        if project_id != expected_project_id:
            raise PermissionError('closeout observer project differs from fixed view')
        return observe_project_schedules(owner, project_id)
    return observe


def write_startup_refusal(home: Path, error: BaseException, trace: Mapping[str, Any]) -> Path:
    """Record a refusal before any native admission; it never claims canonical effects were absent."""
    run = lanes.private_dir(Path(home) / 'run')
    target = run / ('owner-startup-refusal-' + str(os.getpid()) + '.json')
    value = {'schema': REFUSAL_SCHEMA, 'pid': os.getpid(), 'native_admission_started': False,
             'canonical_effects': 'preserved-not-inferred',
             'error': {'code': type(error).__name__, 'message': str(error)[:4096]},
             'startup_store_observation': {**trace.get('store', {}),
                                           'phase_timings': list(trace.get('phases', []))}}
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return target


class SharedLaneRelay:
    """Owner-installed relay and routing for the shared host's file lane."""

    def __init__(self, home: Path, host: Any) -> None:
        self.home = Path(home)
        # Created with the first grant and removed at close once empty, so an owner that relayed
        # nothing leaves nothing behind.
        self.grants_dir = self.home / 'run' / 'shared-grants'
        self.host = host
        self.service: Any = None  # set once the ProjectOwnerService exists

    def protected_relay(self, *, kind: str, view: Any, request: Mapping[str, Any], token: str,
                        lane: Path, installation: Mapping[str, Any]) -> Any:
        """Issue an exact owner grant for one forwarded request, then retain and submit it."""
        manager_token = lanes.new_token()
        key = view.server.state['project_ref']['id']
        principal = installation['hosts'][kind]['principal']
        command = request.get('command')
        if command == 'respond-help':
            view.server.grant_reply(manager_token, request, principal)
        # The router's owner_route trusts only this grant: it names the exact
        # view and the digest of the exact request that is about to be relayed.
        lanes.private_dir(self.grants_dir)
        lanes.atomic_json(self.grants_dir / (manager_token + '.json'),
                          {'schema': GRANT_SCHEMA, 'token': manager_token, 'view': key,
                           'digest': request_digest(request), 'command': command})
        lanes.mark_pending(lane, token, 'relayed', manager_token=manager_token,
                           ipc=str(self.host.directory), command=command)
        lanes.submit(self.host.directory, request, token=manager_token)
        self.service.relays[token] = {'lane': lane, 'ipc': self.host.directory,
                                      'manager_token': manager_token, 'who': kind, 'command': command}
        return _RELAYED

    def owner_route(self, request: Mapping[str, Any]) -> str:
        """The router's trusted port: the one view key this exact owner request was granted for."""
        handle = self.host.command_handle() or {}
        token = handle.get('request_id') if handle.get('transport') == 'file-ipc' else None
        if not token or not lanes.valid_token(token):
            raise PermissionError('unbound owner command requires an authenticated exact project target')
        path = self.grants_dir / (token + '.json')
        grant = lanes.read_private_json(path)
        if (grant is None or grant.get('schema') != GRANT_SCHEMA or grant.get('token') != token
                or grant.get('digest') != request_digest(request)):
            raise PermissionError('unbound owner command requires an authenticated exact project target')
        path.unlink(missing_ok=True)  # single use
        return grant['view']

    def release(self) -> None:
        """Remove the grants directory when no grant is outstanding; a pending grant is retained custody."""
        try:
            self.grants_dir.rmdir()
        except OSError:
            pass


@dataclass
class ProductOwner:
    store: Any
    host: Any
    router: Any
    service: Any
    relay: Any
    root: Any
    sessions: list
    views: dict
    skipped: list
    reconciliation: Mapping[str, Any]
    policy: CapacityPolicy
    hold_dispatch: bool
    stale_stop: bool
    fleet_registry: Any = None
    result_store: Any = None
    runner: Any = None

    def close(self) -> None:
        registry = self.fleet_registry
        if registry is not None:
            registry.close()
        if self.runner is not None:
            self.runner.stop()


class _TaskContextPort:
    """The worker task tool reads only the task selected by its token assignment."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def call(self, operation: str, assignment: str, args: Mapping, *, feedback: bool) -> Mapping:
        context = self.registry.assignment_context(assignment)
        task = context["task"]
        return {"ok": True, "task_id": context["task_id"], "title": task.title,
                "instructions": task.payload.get("fields", {}).get("instructions"),
                "acceptance": task.payload.get("fields", {}).get("acceptance"),
                "repo": context["repo_name"], "branch": context["branch"],
                "check": task.payload.get("fields", {}).get("check")}


class _DirectRunnerClient:
    """The landing protocol over the in-process owner Runner."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("op") == "submit":
            return self.runner.submit(request)
        if request.get("op") == "await":
            result = self.runner.await_run(request.get("run_id"), request.get("timeout"))
            if result.get("ok") and result.get("done"):
                return result
            return {"ok": False, "done": False}
        return {"ok": False, "error": "unknown_op"}


class _InactiveDispatch(LookupError):
    """A fixed public refusal for a token with no live owner dispatch."""

    code = "owner_unavailable"
    message = "LookupError: assignment has no active dispatch record"

    def __init__(self) -> None:
        super().__init__("assignment has no active dispatch record")


class OwnerFleetRegistry:
    """Owner-custodied fleet pieces, indexed by the task's admitted repo and branch.

    Dispatch is deliberately injected: the registry never reconstructs an assignment from a
    worker request. A token is resolved by the dispatcher's TokenBook, then the retained dispatch
    record identifies the task and its admitted revision. Current task metadata selects the
    checkout and branch; callers cannot override either value.
    """

    def __init__(self, owner: Any, config: Mapping[str, Any], home: Any, result_store: Any,
                 *, checkpoint: Callable[..., Any], landing_factory: Optional[Callable[..., Any]] = None,
                 due_port: Any = None) -> None:
        self.owner, self.config, self.home = owner, config, Path(home)
        self.result_store = result_store
        self.checkpoint = checkpoint
        self.landing_factory = landing_factory
        self.due_port = due_port
        self.views_provider: Callable[[], Mapping[str, Any]] = lambda: {}
        self.runner = None
        self.dispatcher = None
        self.facade_server = None
        self.facade_socket = self.home / "run" / "t.sock"
        self.owner_executor: Optional[Callable[[Callable[[], Any]], Any]] = None
        self._pairs: dict[tuple[str, str], tuple[Any, Any]] = {}
        self._pair_lock = threading.RLock()
        from herzchen.fleet.tools.tokens import TokenBook
        self.tokens = TokenBook()
        self.records: dict[str, Any] = {}
        self._due_keys: dict[tuple[str, str], str] = {}
        self._due_bindings: dict[tuple[str, str], tuple[int, str]] = {}
        self._active_due: dict[str, str] = {}
        self._lock = threading.RLock()
        self._start_facade()
        self.startup_landed_sweep: Optional[list] = None

    def _captured_worker_due(self, due: Mapping[str, Any], *, task_ref: Mapping[str, Any] | None = None,
                             assignment_ref: Mapping[str, Any] | None = None,
                             generation: int | None = None,
                             published: Mapping[str, Any] | None = None) -> bool:
        """One exact retained-capture predicate shared by callback and startup sweep."""
        evidence = due.get("host_evidence") if isinstance(due.get("host_evidence"), Mapping) else {}
        attempt = evidence.get("gateway_attempt") if isinstance(evidence.get("gateway_attempt"), Mapping) else {}
        result = attempt.get("result") if isinstance(attempt.get("result"), Mapping) else {}
        target = due.get("target") if isinstance(due.get("target"), Mapping) else {}
        due_task = target.get("task_ref")
        due_assignment = due.get("assignment_ref")
        due_generation = due.get("generation")
        summary = evidence.get("captured_result_summary") if isinstance(evidence.get("captured_result_summary"), Mapping) else {}
        artifacts = evidence.get("captured_artifacts")
        bound = result.get("task_bound_evidence") if isinstance(result.get("task_bound_evidence"), Mapping) else {}
        operation_result = bound.get("operation_result") if isinstance(bound.get("operation_result"), Mapping) else {}
        output = operation_result.get("output") if isinstance(operation_result.get("output"), Mapping) else {}
        captured = output.get("artifacts")
        summary_result_ref = summary.get("result_ref")
        operation_result_ref = operation_result.get("result_ref")
        result_refs_match = (not isinstance(summary_result_ref, (Mapping, str))
                             or not isinstance(operation_result_ref, type(summary_result_ref))
                             or summary_result_ref == operation_result_ref)
        if (due.get("role") != "worker" or attempt.get("state") != "result"
                or result.get("outcome") != "succeeded" or not isinstance(due_task, Mapping)
                or not isinstance(due_assignment, Mapping) or type(due_generation) is not int
                or not attempt.get("logical_request_key")
                or attempt.get("logical_request_key") != result.get("logical_request_key")
                or summary.get("logical_request_key") != attempt.get("logical_request_key")
                or summary.get("assignment_ref") != due_assignment
                or summary.get("generation") != due_generation
                or not isinstance(artifacts, list) or not artifacts
                or not isinstance(captured, list) or not captured
                or not isinstance(summary.get("verification"), Mapping)
                or summary["verification"].get("context_digest_verified") is not True
                or not summary_result_ref or not operation_result_ref or not result_refs_match
                or summary.get("result_digest") != bound.get("result_digest")
                or bound.get("task_ref") != due_task
                or bound.get("assignment_ref") != due_assignment or bound.get("generation") != due_generation):
            return False
        if task_ref is not None and dict(due_task) != dict(task_ref):
            return False
        if assignment_ref is not None and dict(due_assignment) != dict(assignment_ref):
            return False
        if generation is not None and due_generation != generation:
            return False
        if published is not None and (published.get("result_ref") != summary.get("result_ref")
                                       or published.get("result_digest") != summary.get("result_digest")):
            return False
        return True

    def settle_landed_worker(self, *, task_ref: Mapping[str, Any], assignment_ref: Mapping[str, Any],
                             generation: int, schedule_id: str,
                             published: Mapping[str, Any]) -> Mapping[str, Any]:
        """Remove a landed worker lab after its exact turn result is captured."""
        if self.due_port is None:
            return {"cleanup_pending": True, "reason": "owner Due capture reader is unavailable"}
        from herzchen.contracts import ResourceRef
        due = self.due_port.read_due(schedule_id)
        if (not isinstance(due, Mapping) or not self._captured_worker_due(
                due, task_ref=task_ref, assignment_ref=assignment_ref,
                generation=generation, published=published)):
            return {"cleanup_pending": True, "reason": "exact captured worker Due is unavailable"}
        task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
        plan_data = task.payload.get("metadata_namespaces", {}).get("otto.plan", {})
        repo_name, branch = plan_data.get("repo"), plan_data.get("branch")
        repositories = self.config.get("repositories")
        if (not isinstance(repo_name, str) or not isinstance(branch, str)
                or not isinstance(repositories, Mapping) or repo_name not in repositories):
            return {"cleanup_pending": True, "reason": "current admitted task plan is unavailable"}
        repo = Path(repositories[repo_name]).resolve()
        with self._pair_lock:
            fleet, _landing = self._pair((repo_name, branch), repo, branch)
            lab_name = task_ref.get("id")
            if lab_name not in fleet.names():
                return {"cleanup_pending": False}
            line_ref = "refs/heads/" + branch
            results = fleet.sweep_landed(line_ref, lambda name, commit: self._captured_worker_due(
                due, task_ref=task_ref, assignment_ref=assignment_ref,
                generation=generation, published=published) and name == lab_name)
            remains = lab_name in fleet.names()
        failed = remains or any(item.name == lab_name and item.action != "removed" for item in results)
        return {"cleanup_pending": failed}

    def sweep_landed_at_start(self) -> list:
        """Retry marker-indexed cleanup from exact captured worker Due records."""
        if self.due_port is None:
            return []
        from herzchen.contracts import ResourceRef
        outcomes = []
        try:
            retained_dues = self.due_port.list_due()
        except Exception as exc:
            return [{"action": "kept-error", "detail": repr(exc)}]
        for due in retained_dues:
            if not isinstance(due, Mapping) or not self._captured_worker_due(due):
                continue
            target = due.get("target") or {}
            task_ref = target.get("task_ref") if isinstance(target, Mapping) else None
            if not isinstance(task_ref, Mapping):
                continue
            try:
                task = self.owner.graph.reader.get_identity(ResourceRef.from_dict(task_ref))
                plan_data = task.payload.get("metadata_namespaces", {}).get("otto.plan", {})
                repo_name, branch = plan_data.get("repo"), plan_data.get("branch")
                repositories = self.config.get("repositories")
                if (not isinstance(repo_name, str) or not isinstance(branch, str)
                        or not isinstance(repositories, Mapping) or repo_name not in repositories):
                    continue
                repo = Path(repositories[repo_name]).resolve()
                with self._pair_lock:
                    fleet, _landing = self._pair((repo_name, branch), repo, branch)
                eligible = lambda name, commit, raw=due, selected=task_ref: (
                    name == selected.get("id") and self._captured_worker_due(
                        raw, task_ref=selected,
                        assignment_ref=raw.get("assignment_ref"),
                        generation=raw.get("generation")))
                outcomes.extend(fleet.sweep_landed("refs/heads/" + branch, eligible))
            except Exception as exc:
                outcomes.append({"schedule_id": due.get("schedule_id"), "action": "kept-error",
                                 "detail": repr(exc)})
        return outcomes

    def _start_facade(self) -> None:
        from herzchen.fleet.tools import AllowlistedPort, FacadeServer, FeedbackLedger, ToolFacade
        from herzchen.fleet.tools.facade import LandingOwnerPort
        from otto.agents.claude_cli import TOOL_SPECS
        tools = tuple(TOOL_SPECS)
        self.facade = ToolFacade(tools, {"worker": tuple(spec.name for spec in tools)},
                                 AllowlistedPort(_OwnerExecutorPort(
                                     LandingOwnerPort(self.assignment_context, fallback=_TaskContextPort(self)),
                                     lambda: self.owner_executor, self.settle_assignment,
                                     self.retain_landing_refusal),
                                                 tuple(spec.operation for spec in tools)),
                                 self.tokens, FeedbackLedger())
        self.facade_server = FacadeServer(self.facade, str(self.facade_socket))
        self.facade_server.start()

    def bind_dispatcher(self, dispatcher: Any) -> None:
        """Bind routine selection and its live grants to the retained Due authority."""
        if not hasattr(dispatcher, "tokens") or not hasattr(dispatcher, "records"):
            raise TypeError("fleet dispatcher must expose tokens and retained records")
        if self.records and dispatcher.tokens is not self.tokens:
            raise PermissionError("existing worker grants require the same owner TokenBook")
        for assignment, record in self.records.items():
            prior = dispatcher.records.get(assignment)
            if prior is not None and prior is not record:
                raise PermissionError("dispatcher record conflicts with retained worker authority")
            dispatcher.records[assignment] = record
        self.dispatcher = dispatcher
        self.tokens = dispatcher.tokens
        self.records = dispatcher.records
        if self.facade_server is not None:
            self.facade_server.stop()
        self._start_facade()

    def close(self) -> None:
        if self.facade_server is not None:
            self.facade_server.stop()
            self.facade_server = None

    def bind_owner_executor(self, executor: Callable[[Callable[[], Any]], Any]) -> None:
        if not callable(executor):
            raise TypeError("owner executor must be callable")
        self.owner_executor = executor

    def bind_views(self, views_provider: Callable[[], Mapping[str, Any]]) -> None:
        if not callable(views_provider):
            raise TypeError("views provider must be callable")
        self.views_provider = views_provider

    def bind_runner(self, runner: Any) -> None:
        self.runner = runner

    @staticmethod
    def _task_id(task: Any) -> str:
        if isinstance(task, str) and task:
            return task
        ref = getattr(task, "ref", None)
        value = getattr(ref, "id", None) if ref is not None else None
        if not value and isinstance(task, Mapping):
            ref = task.get("ref")
            value = ref.get("id") if isinstance(ref, Mapping) else task.get("id")
        if not isinstance(value, str) or not value:
            raise LookupError("dispatch record has no task id")
        return value

    def _task_pin_matches(self, pinned_ref: Any, current: Any) -> bool:
        """Validate a task pin by retained authored content under the owner Store."""
        from herzchen.domains.work import admission
        from herzchen.contracts import ResourceRef

        try:
            pin = ResourceRef.from_dict(pinned_ref) if isinstance(pinned_ref, Mapping) else pinned_ref
            current_ref = getattr(current, "ref", None)
            if (not isinstance(pin, ResourceRef) or current_ref is None
                    or (pin.authority, pin.kind, pin.id) !=
                       (current_ref.authority, current_ref.kind, current_ref.id)):
                return False
            return admission.task_content_matches(getattr(self.owner, "store", None), pin,
                                                  current.payload, current_ref=current_ref)
        except (AttributeError, KeyError, LookupError, TypeError, ValueError):
            return False

    def _record_for_assignment(self, assignment_id: str) -> Any:
        record = self.records.get(assignment_id)
        if record is None or record.state not in {"admitted", "launched", "unknown"}:
            raise _InactiveDispatch()
        return record

    def assignment_context(self, assignment_id: str, token: Any = None) -> dict[str, Any]:
        """Resolve one active dispatch record to its current task, repo, line and lab."""
        with self._lock:
            return self._resolve_assignment_context(assignment_id, token)

    def assignment_lookup(self, assignment_id: str, token: Any = None) -> dict[str, Any]:
        """Resolve exact assignment/task/project pins without constructing a fleet pair."""
        with self._lock:
            record = self._record_for_assignment(assignment_id)
            if token is not None:
                grant = self.tokens.resolve(token)
                if grant.assignment != assignment_id or record.token != token:
                    raise PermissionError("worker token does not belong to this assignment")
            task_id = self._task_id(record.task)
            task_ref = getattr(getattr(record, "task", None), "ref", None)
            authority = getattr(task_ref, "authority", None) or self.config["store"]["authority"]
            from herzchen.contracts import ResourceRef
            current = self.owner.graph.current(ResourceRef(authority, "work.task", task_id))
            from herzchen.domains.work.admission import admitted_revision
            admitted = admitted_revision(current.payload)
            if admitted != record.admitted_revision:
                raise LookupError("task admission no longer matches the dispatch record")
            project_ref = current.payload.get("project_ref") if isinstance(current.payload, Mapping) else None
            if not isinstance(project_ref, Mapping):
                raise LookupError("admitted task has no exact project reference")
            parent = ResourceRef.from_dict(project_ref)
            if parent.authority != authority or parent.kind != "work.project" or not parent.revision:
                raise LookupError("admitted task has no exact owner project reference")
            current_project = self.owner.graph.current(ResourceRef(parent.authority, parent.kind, parent.id))
            if (current_project.ref.authority, current_project.ref.kind, current_project.ref.id) != (
                    parent.authority, parent.kind, parent.id):
                raise LookupError("admitted task project identity is not current")
            assignment = self.owner.assignments.get(ResourceRef(authority, "wrk.assignment", assignment_id))
            if (assignment.role != "executor"
                    or (assignment.scope.authority, assignment.scope.kind, assignment.scope.id) !=
                       (current.ref.authority, current.ref.kind, current.ref.id)):
                raise PermissionError("dispatch record assignment does not own its admitted task")
            views = self.views_provider()
            view = views.get(parent.id) if isinstance(views, Mapping) else None
            return {"record": record, "assignment_id": record.assignment, "task": current, "task_id": task_id,
                    "admitted_revision": admitted, "assignment_ref": assignment.ref.to_dict(),
                    "generation": assignment.generation, "task_ref": current.ref.to_dict(),
                    "project_ref": current_project.ref.to_dict(), "view": view,
                    "project_state": getattr(getattr(view, "server", None), "state", None)}

    def prepare_worker_lab(self, project_ref: Any, task_ref: Any) -> dict[str, Any]:
        """Prepare the lab from the owner's current admitted task plan.

        This is called before assignment creation so the worker adapter can be
        constructed with its only writable workspace. The task pin is checked
        against the project view and the current admission; no launch request
        field participates in repository, branch, lab, or assessment selection.
        """
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import admitted_revision
        project = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        task = ResourceRef.from_dict(task_ref) if isinstance(task_ref, Mapping) else task_ref
        if not isinstance(project, ResourceRef) or not isinstance(task, ResourceRef):
            raise PermissionError("worker lab requires exact owner project and task references")
        current = self.owner.graph.current(ResourceRef(task.authority, "work.task", task.id))
        if not self._task_pin_matches(task, current):
            raise PermissionError("worker task reference is stale")
        payload = current.payload
        task_project = payload.get("project_ref") if isinstance(payload, Mapping) else None
        if not isinstance(task_project, Mapping):
            raise PermissionError("worker task does not belong to the requested project")
        recorded_project = ResourceRef.from_dict(task_project)
        project_identity = (project.authority, project.kind, project.id)
        if (recorded_project.authority, recorded_project.kind, recorded_project.id) != project_identity:
            raise PermissionError("worker task does not belong to the requested project")
        current_project = self.owner.graph.current(ResourceRef(project.authority, "work.project", project.id))
        if (current_project.ref.authority, current_project.ref.kind, current_project.ref.id) != project_identity:
            raise PermissionError("worker project identity is not current")
        linked = current_project.payload.get("tasks") if isinstance(current_project.payload, Mapping) else None
        if not isinstance(linked, (list, tuple)) or not any(
                (candidate.authority, candidate.kind, candidate.id) ==
                (task.authority, task.kind, task.id)
                for candidate in (ResourceRef.from_dict(raw) if isinstance(raw, Mapping) else raw
                                  for raw in linked) if isinstance(candidate, ResourceRef)):
            raise PermissionError("worker task is not linked by the current project")
        admitted = admitted_revision(payload)
        if not isinstance(admitted, str):
            raise PermissionError("worker task has no current admitted revision")
        metadata = payload.get("metadata_namespaces") if isinstance(payload, Mapping) else None
        plan = metadata.get("otto.plan") if isinstance(metadata, Mapping) else None
        if not isinstance(plan, Mapping):
            raise LookupError("task plan metadata is missing otto.plan")
        repo_name, branch = plan.get("repo"), plan.get("branch")
        for key, value in (("repo", repo_name), ("branch", branch)):
            if not isinstance(value, str) or not value.strip():
                raise LookupError("task plan is missing otto.plan." + key)
        repositories = self.config.get("repositories")
        if not isinstance(repositories, Mapping) or repo_name not in repositories:
            raise LookupError("unknown repo: " + repo_name)
        repo = Path(repositories[repo_name]).resolve()
        if not repo.is_dir():
            raise LookupError("repo " + repo_name + " checkout does not exist")
        check = subprocess.run(["git", "-C", str(repo), "check-ref-format", "--branch", branch],
                               capture_output=True, text=True)
        exists = subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet",
                                 "refs/heads/" + branch])
        if check.returncode != 0 or exists.returncode != 0:
            raise LookupError("repo " + repo_name + " has no valid branch " + branch)
        pair_key = (repo_name, branch)
        with self._pair_lock:
            fleet, landing = self._pair(pair_key, repo, branch)
            lab_name = task.id
            lab = (fleet.get(lab_name) if lab_name in fleet.names()
                   else fleet.create(lab_name, base="refs/heads/" + branch))
        return {"task_id": task.id, "admitted_revision": admitted, "repo_name": repo_name,
                "repo_path": str(repo), "branch": branch, "line_ref": "refs/heads/" + branch,
                "lab_name": lab_name, "lab": lab, "workspace": str(lab.path),
                "fleet": fleet, "landing": landing, "service": landing}

    def worker_context_for_due(self, due: Any) -> dict[str, Any]:
        """Resolve and validate the exact owner Due before returning its lab."""
        grant = self.grant_for_due(due)
        assignment = due.get("assignment_ref") if isinstance(due, Mapping) else getattr(due, "assignment_ref", None)
        assignment_id = assignment.get("id") if isinstance(assignment, Mapping) else getattr(assignment, "id", None)
        if not isinstance(assignment_id, str) or not assignment_id:
            raise PermissionError("worker Due has no assignment identity")
        return self.assignment_context(assignment_id, token=grant.token)

    def _pair(self, key: tuple[str, str], repo: Path, branch: str) -> tuple[Any, Any]:
        pair = self._pairs.get(key)
        if pair is not None:
            return pair
        from herzchen.fleet.labs import LabFleet
        branch_key = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:20]
        labs_root = repo.parent / (repo.name + ".otto-labs") / branch_key
        fleet = LabFleet(repo, labs_root, checkpoint=self.checkpoint)
        factory = self.landing_factory
        if factory is None:
            from .fleet_landing import make_landing_service
            factory = make_landing_service
        landing = factory(fleet=fleet, result_store=self.result_store, runner=self.runner,
                          repo_name=key[0], repo_path=repo, branch=branch, owner=self.owner,
                          views_provider=self.views_provider, assignment_lookup=self.assignment_lookup)
        pair = (fleet, landing)
        self._pairs[key] = pair
        return pair

    def _resolve_assignment_context(self, assignment_id: str, token: Any = None) -> dict[str, Any]:
        record = self._record_for_assignment(assignment_id)
        if token is not None:
            grant = self.tokens.resolve(token)
            if grant.assignment != assignment_id or record.token != token:
                raise PermissionError("worker token does not belong to this assignment")
        task_id = self._task_id(record.task)
        ref = record.task.ref if hasattr(record.task, "ref") else None
        authority = getattr(ref, "authority", None) or self.config["store"]["authority"]
        from herzchen.contracts import ResourceRef
        current = self.owner.graph.current(ResourceRef(authority, "work.task", task_id))
        payload = current.payload
        project_ref = payload.get("project_ref") if isinstance(payload, Mapping) else None
        if not isinstance(project_ref, Mapping):
            raise LookupError("admitted task has no exact project reference")
        from herzchen.contracts import ResourceRef
        assignment = self.owner.assignments.get(ResourceRef(authority, "wrk.assignment", assignment_id))
        if (assignment.role != "executor"
                or (assignment.scope.authority, assignment.scope.kind, assignment.scope.id) !=
                   (current.ref.authority, current.ref.kind, current.ref.id)):
            raise PermissionError("dispatch record assignment does not own its admitted task")
        from herzchen.domains.work.admission import admitted_revision
        admitted = admitted_revision(payload)
        if admitted != record.admitted_revision:
            raise LookupError("task admission no longer matches the dispatch record")
        metadata = payload.get("metadata_namespaces") if isinstance(payload, Mapping) else None
        plan = metadata.get("otto.plan") if isinstance(metadata, Mapping) else None
        if not isinstance(plan, Mapping):
            raise LookupError("task plan metadata is missing otto.plan")
        for key in ("repo", "branch"):
            if not isinstance(plan.get(key), str) or not plan[key].strip():
                raise LookupError("task plan is missing otto.plan." + key)
        repo_name, branch = plan["repo"], plan["branch"]
        repositories = self.config.get("repositories")
        if not isinstance(repositories, Mapping) or repo_name not in repositories:
            raise LookupError("unknown repo: " + repo_name)
        repo_path = repositories[repo_name]
        if not isinstance(repo_path, (str, os.PathLike)):
            raise LookupError("repo " + repo_name + " has no local checkout path")
        key = (repo_name, branch)
        with self._pair_lock:
            repo = Path(repo_path).resolve()
            if not repo.is_dir():
                raise LookupError("repo " + repo_name + " checkout does not exist")
            check = subprocess.run(["git", "-C", str(repo), "check-ref-format", "--branch", branch],
                                   capture_output=True, text=True)
            exists = subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet",
                                     "refs/heads/" + branch])
            if check.returncode != 0 or exists.returncode != 0:
                raise LookupError("repo " + repo_name + " has no valid branch " + branch)
            pair = self._pair(key, repo, branch)
        fleet, landing = pair
        if task_id not in fleet.names():
            raise LookupError("dispatch assignment has no prepared task lab")
        lab = fleet.get(task_id)
        trusted = self.assignment_lookup(assignment_id, token=token)
        return {"record": record, "assignment_id": record.assignment, "task": current, "task_id": task_id,
                "admitted_revision": admitted, "repo_name": repo_name, "repo_path": str(repo_path),
                "branch": branch, "line_ref": "refs/heads/" + branch, "lab_name": task_id,
                "lab": lab, "workspace": str(lab.path),
                "fleet": fleet, "landing": landing, "service": landing,
                **{key: trusted[key] for key in ("assignment_ref", "generation", "task_ref", "project_ref", "view", "project_state")}}

    def grant_for_due(self, due: Any) -> Any:
        """Resolve a worker Due to the token held by its live dispatch record."""
        due_role = due.get("role") if isinstance(due, Mapping) else getattr(due, "role", None)
        if due_role != "worker":
            raise PermissionError("worker grant requires a worker Due")
        assignment = getattr(due, "assignment_ref", None)
        assignment_id = getattr(assignment, "id", None)
        if assignment_id is None and isinstance(due, Mapping):
            assignment = due.get("assignment_ref")
            assignment_id = assignment.get("id") if isinstance(assignment, Mapping) else None
        if not isinstance(assignment_id, str) or not assignment_id:
            raise PermissionError("worker Due has no assignment identity")
        assignment_ref = due.get("assignment_ref") if isinstance(due, Mapping) else getattr(due, "assignment_ref", None)
        assignment_ref = (assignment_ref if isinstance(assignment_ref, Mapping) else
                          assignment_ref.to_dict() if callable(getattr(assignment_ref, "to_dict", None)) else None)
        generation = due.get("generation") if isinstance(due, Mapping) else getattr(due, "generation", None)
        schedule_id = due.get("schedule_id") if isinstance(due, Mapping) else getattr(due, "schedule_id", None)
        if (not isinstance(assignment_ref, Mapping) or assignment_ref.get("id") != assignment_id
                or type(generation) is not int or generation < 1
                or not isinstance(schedule_id, str) or not schedule_id):
            raise PermissionError("worker Due lacks exact assignment, generation or schedule identity")
        dispatcher = self.dispatcher
        # A task match alone is not authority: a retry or a second assignment may target the
        # same task. The durable assignment identity must match the dispatch record exactly.
        target = due.get("target") if isinstance(due, Mapping) else getattr(due, "target", None)
        target = target if isinstance(target, Mapping) else {}
        task_ref = target.get("task_ref") or target.get("task")
        if not isinstance(task_ref, Mapping) or not all(
                isinstance(task_ref.get(key), str) and task_ref[key]
                for key in ("authority", "id", "revision")):
            raise PermissionError("worker Due lacks the exact task reference and revision")
        task_id = task_ref["id"]
        if target.get("assignment_ref") is not None and target.get("assignment_ref") != assignment_ref:
            raise PermissionError("worker Due target assignment differs from its exact assignment reference")
        from herzchen.contracts import ResourceRef
        owner_assignment = self.owner.assignments.get(ResourceRef.from_dict(assignment_ref))
        if owner_assignment.ref.to_dict() != dict(assignment_ref):
            raise PermissionError("worker Due assignment reference is stale")
        if owner_assignment.generation != generation or owner_assignment.role != "executor":
            raise PermissionError("worker Due assignment generation or role is stale")
        recipient = due.get("recipient") if isinstance(due, Mapping) else getattr(due, "recipient", None)
        if recipient != owner_assignment.principal:
            raise PermissionError("worker Due recipient does not match its assignment principal")
        scope = owner_assignment.scope
        if ((scope.authority, scope.kind, scope.id) !=
                (task_ref.get("authority"), task_ref.get("kind", "work.task"), task_id)):
            raise PermissionError("worker Due task does not match its assignment scope")
        current = self.owner.graph.current(ResourceRef(task_ref["authority"], "work.task", task_id))
        if not self._task_pin_matches(task_ref, current):
            raise PermissionError("worker Due task revision is stale")
        from herzchen.domains.work.admission import admitted_revision
        revision = admitted_revision(current.payload)
        if not isinstance(revision, str):
            raise PermissionError("worker task has no current admitted revision")
        with self._lock:
            record = self.records.get(assignment_id)
            due_key = (assignment_id, str(due.get("schedule_id") if isinstance(due, Mapping)
                                          else getattr(due, "schedule_id", "")))
            if record is None:
                # An authenticated manager may have prepared this occurrence before the
                # routine selector saw it. The exact Due checks above remain the source
                # of authority for that route; it shares the same grant ledger.
                record = self._record_from_due(due, assignment_id, task_id, due_key)
            elif (record.state not in {"admitted", "launched", "unknown"}
                  or getattr(record, "role", None) != "worker"):
                raise PermissionError("worker Due does not identify a live worker dispatch record")
            elif dispatcher is None:
                binding = self._due_bindings.get(due_key)
                generation = due.get("generation") if isinstance(due, Mapping) else getattr(due, "generation", None)
                if binding != (generation, task_id) or self._due_keys.get(due_key) != assignment_id:
                    raise PermissionError("worker Due schedule or generation is not bound to this dispatch record")
            else:
                generation = due.get("generation") if isinstance(due, Mapping) else getattr(due, "generation", None)
                binding = self._due_bindings.setdefault(due_key, (generation, task_id))
                if binding != (generation, task_id):
                    raise PermissionError("worker Due schedule or generation changed")
            if task_id is not None and self._task_id(record.task) != task_id:
                raise PermissionError("worker Due task pin does not match its dispatch record")
            record_task_ref = getattr(record.task, "ref", None)
            if (record.admitted_revision != revision or record_task_ref is None
                    or not self._task_pin_matches(record_task_ref, current)):
                raise PermissionError("worker dispatch record does not match the exact admitted task revision")
            if record.token is None:
                raise PermissionError("worker dispatch has no live issued token")
            grant = self.tokens.resolve(record.token)
            if grant.assignment != record.assignment:
                raise PermissionError("worker token does not match its dispatch record")
        self.assignment_context(record.assignment, token=record.token)
        with self._lock:
            self._active_due[assignment_id] = schedule_id
        if self.facade_server is None:
            raise PermissionError("owner worker tool facade is not composed")
        from herzchen.fleet.hosts.contract import McpGrant, McpServer
        python = self.config.get("python")
        if not isinstance(python, str) or not os.path.isabs(python):
            raise PermissionError("owner Python executable is not configured")
        tools = tuple(spec.name for spec in __import__("otto.agents.claude_cli", fromlist=["TOOL_SPECS"]).TOOL_SPECS)
        return McpGrant(servers=(McpServer(name="otto", command=python,
                                            args=("-m", "herzchen.fleet.tools.stdio_server", "--socket",
                                                  str(self.facade_socket), "--token-env", "OTTO_WORKER_TOKEN"),
                                            tools=tools),),
                        token_env="OTTO_WORKER_TOKEN", token=record.token,
                        token_env_prefix="OTTO_WORKER_")

    def retain_landing_refusal(self, assignment_id: str, error: Any) -> None:
        """CAS a tool refusal onto the exact active owner Due, if still current."""
        from dataclasses import replace
        from otto.attention import DueRecord
        if self.due_port is None:
            return
        with self._lock:
            schedule_id = self._active_due.get(assignment_id)
        if not schedule_id:
            return
        raw = self.due_port.read_due(schedule_id)
        if not isinstance(raw, Mapping):
            return
        due = DueRecord.from_dict(raw)
        context = self.assignment_context(assignment_id)
        attempt = (due.host_evidence or {}).get("gateway_attempt") or {}
        authorization = attempt.get("delivery_authorization") or {}
        admission = attempt.get("delivery_admission") or {}
        if (due.role != "worker" or due.assignment_ref != context["assignment_ref"]
                or due.generation != context["generation"]
                or due.target.get("task_ref") != context["task_ref"]
                or due.stop_state != "active" or not due.in_flight_request
                or attempt.get("logical_request_key") != due.in_flight_request
                or authorization.get("status") != "authorized"
                or authorization.get("assignment_ref") != due.assignment_ref
                or authorization.get("generation") != due.generation
                or authorization.get("task_ref") != due.target.get("task_ref")
                or admission.get("native_turn_started") is not True
                or admission.get("physical_session_id") != authorization.get("physical_session_id")
                or (due.host_evidence or {}).get("landing_success") is True):
            return
        refusal = {"schema": "otto.worker-landing-refusal.v1",
                   "schedule_id": schedule_id, "assignment_ref": due.assignment_ref,
                   "generation": due.generation, "task_ref": due.target["task_ref"],
                   "lab_path": context["workspace"], "message": str(error),
                   "settled": getattr(error, "settled", None) is True,
                   "outcome": "conflict" if str(error).startswith("rebase conflict") else "failed"}
        evidence = {**(due.host_evidence or {}), "landing_refusal": refusal}
        self.due_port.save_due(schedule_id, replace(due, host_evidence=evidence).to_dict(),
            request_id="worker-landing-refusal:" + hashlib.sha256(json.dumps(
                refusal, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            expected_version=due.version)

    def _record_from_due(self, due: Any, assignment_id: str, task_id: Any,
                         due_key: tuple[str, str]) -> Any:
        """Retain the exact current worker occurrence as the product's dispatch authority.

        This bridge runs only after owner Due identity and worker role have been checked. It does
        not launch work; ManagerJourneyService remains the launch authority.
        """
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import admitted_revision
        from herzchen.fleet.dispatch import DispatchRecord
        assignment_ref = due.get("assignment_ref") if isinstance(due, Mapping) else getattr(due, "assignment_ref", None)
        generation = due.get("generation") if isinstance(due, Mapping) else getattr(due, "generation", None)
        schedule_id = due_key[1]
        if (not isinstance(assignment_ref, Mapping) or assignment_ref.get("id") != assignment_id
                or type(generation) is not int or generation < 1 or not schedule_id):
            raise PermissionError("worker Due lacks exact assignment, generation or schedule identity")
        if task_id is None:
            raise PermissionError("worker Due lacks its owner task pin")
        target = due.get("target") if isinstance(due, Mapping) else getattr(due, "target", None)
        task_ref = target.get("task_ref") if isinstance(target, Mapping) else None
        if not isinstance(task_ref, Mapping) or task_ref.get("id") != task_id:
            raise PermissionError("worker Due lacks the exact task reference")
        owner_assignment = self.owner.assignments.get(ResourceRef.from_dict(assignment_ref))
        if owner_assignment.generation != generation or owner_assignment.role != "executor":
            raise PermissionError("worker Due assignment generation or role is stale")
        recipient = due.get("recipient") if isinstance(due, Mapping) else getattr(due, "recipient", None)
        if recipient != owner_assignment.principal:
            raise PermissionError("worker Due recipient does not match its assignment principal")
        scope = owner_assignment.scope
        if ((scope.authority, scope.kind, scope.id) !=
                (task_ref.get("authority"), task_ref.get("kind", "work.task"), task_id)):
            raise PermissionError("worker Due task does not match its assignment scope")
        current = self.owner.graph.current(ResourceRef(task_ref["authority"], "work.task", task_id))
        if not self._task_pin_matches(task_ref, current):
            raise PermissionError("worker Due task revision is stale")
        revision = admitted_revision(current.payload)
        if not isinstance(revision, str):
            raise PermissionError("worker task has no current admitted revision")
        existing_key = self._due_keys.get(due_key)
        if existing_key is not None:
            existing = self.records.get(existing_key)
            if existing is not None and self._task_id(existing.task) == task_id:
                return existing
            raise PermissionError("worker Due schedule was already bound to another task")
        if assignment_id in self.records:
            raise PermissionError("worker assignment already has another live dispatch")
        if any(getattr(other, "state", None) in {"admitted", "launched", "unknown"}
               and getattr(other, "role", None) == "worker"
               and self._task_id(other.task) == task_id
               for other_id, other in self.records.items() if other_id != assignment_id):
            raise PermissionError("task already has a live worker assignment bound to its lab")
        token = self.tokens.issue(assignment_id, "worker")
        record = DispatchRecord(assignment_id, current, "worker", revision,
                                state="admitted", token=token)
        self.records[assignment_id] = record
        self._due_keys[due_key] = assignment_id
        self._due_bindings[due_key] = (generation, task_id)
        return record

    def settle_assignment(self, assignment_id: str) -> None:
        """Revoke a worker token after its owner landing has settled."""
        with self._lock:
            self._active_due.pop(assignment_id, None)
            if callable(getattr(self.dispatcher, "finish", None)):
                self.dispatcher.finish(assignment_id)
                return
            self.tokens.revoke(assignment_id)
            record = self.records.get(assignment_id)
            if record is not None:
                record.state = "settled"
                record.token = None


def bind_automatic_dispatch(host: Any, registry: OwnerFleetRegistry, views: Mapping[str, Any]) -> Any:
    """Select admitted project tasks on the serialized owner capacity pump."""
    from herzchen.contracts import ResourceRef
    from herzchen.domains.work.admission import admitted_revision
    from herzchen.domains.work.readiness import ready as work_ready
    from herzchen.fleet.dispatch import DispatchError, FleetDispatcher
    from otto.agents.claude_cli import TOOL_SPECS
    from otto.portfolio.dependencies import PortfolioDependencies

    owner = registry.owner
    dependencies = PortfolioDependencies(owner.graph, owner.store.consumer(),
                    actor=owner.owner_actor, owner_actor=owner.owner_actor)

    def current(task: Any, **_context: Any) -> Any:
        return owner.graph.current(ResourceRef(task.ref.authority, "work.task", task.ref.id))

    def plan(task: Any) -> Mapping[str, Any]:
        payload = task.payload
        namespaces = payload.get("metadata_namespaces") if isinstance(payload, Mapping) else None
        value = namespaces.get("otto.plan") if isinstance(namespaces, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    def request_key(task: Any) -> str:
        project = task.payload["project_ref"]
        revision = admitted_revision(task.payload)
        identity = {field: project[field] for field in ("authority", "kind", "id")}
        raw = json.dumps([identity, task.ref.id, revision], sort_keys=True, separators=(",", ":"))
        return "autodispatch-" + hashlib.sha256(raw.encode()).hexdigest()

    def assignment_id(task: Any) -> str:
        key = request_key(task) + ":assign"
        return "assignment-" + hashlib.sha256((task.ref.authority + ":" + key).encode()).hexdigest()[:28]

    def candidates() -> list[Any]:
        tasks = []
        for view in tuple(views.values()):
            state = view.server.state
            for alias, raw in tuple(state.get("task_refs", {}).items()):
                try:
                    task = owner.graph.current(ResourceRef.from_dict(raw))
                except (LookupError, ValueError, KeyError):
                    continue
                if task.ref.to_dict() != raw:
                    view._refresh_refs()
                    if view.server.state["task_refs"].get(alias) != task.ref.to_dict():
                        continue
                prior = (state.get("workers") or {}).get(alias)
                if prior is not None and not isinstance(prior, Mapping):
                    continue
                if isinstance(prior, Mapping):
                    schedule = prior.get("schedule_id")
                    if not isinstance(schedule, str) or not schedule:
                        continue
                    due = view.server.due_port.read_due(schedule)
                    previous_ref = ((due or {}).get("target") or {}).get("task_ref")
                    try:
                        previous = (owner.graph.reader.get_identity(ResourceRef.from_dict(previous_ref))
                                    if isinstance(previous_ref, Mapping) else None)
                    except (LookupError, ValueError, TypeError, KeyError):
                        previous = None
                    if (not due or due.get("completion_state") != "succeeded" or previous is None
                            or admitted_revision(previous.payload) == admitted_revision(task.payload)):
                        continue
                failure = (state.get("automatic_dispatch_failures") or {}).get(alias)
                if (isinstance(failure, Mapping)
                        and failure.get("admitted_revision") == admitted_revision(task.payload)):
                    continue
                if plan(task).get("route") in {"normal", "xhard"}:
                    tasks.append(task)
        return tasks

    def ready(task: Any, **_context: Any) -> Any:
        lifecycle = getattr(task, "lifecycle", None)
        lifecycle = getattr(lifecycle, "value", lifecycle)
        readiness = task.payload.get("readiness")
        readiness_state = (readiness.get("state", readiness.get("status"))
                           if isinstance(readiness, Mapping) else readiness)
        if lifecycle in {"paused", "waiting"} or readiness_state in {"paused", "waiting"}:
            return {"ready": False, "blockers": ["task is paused or waiting"]}
        result = work_ready(task, read_record=lambda ref: owner.graph.current(ref),
                            read_revision=lambda ref: owner.graph.reader.get_identity(ref),
                            project_readiness=lambda ref: dependencies.readiness(ref, observe=False))
        if not result["ready"]:
            return result
        project = task.payload.get("project_ref")
        view = views.get(project.get("id")) if isinstance(project, Mapping) else None
        if (view is None or task.ref.to_dict() not in view.server.state.get("task_refs", {}).values()
                or plan(task).get("route") not in {"normal", "xhard"}):
            return {"ready": False, "blockers": ["task has no current configured project worker route"]}
        return result

    def active_counts() -> tuple[int, int]:
        active = list(host.capacity_holds().values())
        active.extend(value["scope"] for value in host._executions.values() if value["running"])
        managers = sum(scope["role"] == "manager" for scope in active)
        return len(active) - managers, managers

    def launch(task: Any, context: Mapping[str, Any]) -> Mapping[str, Any]:
        project = task.payload["project_ref"]
        view = views[project["id"]]
        aliases = [alias for alias, ref in view.server.state["task_refs"].items() if ref["id"] == task.ref.id]
        if len(aliases) != 1:
            return {"outcome": "known-pre-effect-failure", "failure": {
                "outcome": "rejected", "reason": "task has no unique current project alias",
                "provider_called": False, "effects_started": False}, "alias": None,
                "project_id": project["id"], "admitted_revision": admitted_revision(task.payload)}
        focus = (task.payload.get("fields", {}).get("instructions")
                 or task.payload.get("outcome") or task.title)
        if not isinstance(focus, str) or not focus.strip() or len(focus) > 4000:
            return {"outcome": "known-pre-effect-failure", "failure": {
                "outcome": "rejected", "reason": "task has no bounded worker intent",
                "provider_called": False, "effects_started": False}, "alias": aliases[0],
                "project_id": project["id"], "admitted_revision": admitted_revision(task.payload)}
        result = view._submit_worker({"command": "run-worker", "task": aliases[0],
            "route": plan(task)["route"], "principal": "worker-" + task.ref.id,
            "request_key": request_key(task), "focus": focus}, automatic=True,
            automatic_revision=admitted_revision(task.payload))
        if (result.get("outcome") not in {"admitted", "prepared", "retained"}
                or result.get("assignment_ref", {}).get("id") != context["assignment"]):
            # Only an explicit pre-effect refusal is safe to settle here. Any
            # ambiguous result leaves FleetDispatcher's UNKNOWN fence intact.
            previous_worker = (view.server.state.get("workers") or {}).get(aliases[0])
            previous_due = (view.server.due_port.read_due(previous_worker.get("schedule_id"))
                            if isinstance(previous_worker, Mapping)
                            and isinstance(previous_worker.get("schedule_id"), str) else None)
            previous_unsettled = bool(previous_due and previous_due.get("completion_state") != "succeeded")
            if (isinstance(result, Mapping) and result.get("outcome") in {"held", "rejected", "partial"}
                    and result.get("provider_called") is False
                    and result.get("effects_started") is False
                    and not result.get("schedule_id") and not result.get("assignment_ref")
                    and not previous_unsettled):
                return {"outcome": "known-pre-effect-failure", "failure": dict(result),
                        "alias": aliases[0], "project_id": project["id"],
                        "admitted_revision": admitted_revision(task.payload)}
            raise DispatchError("owner worker preparation did not retain the selected assignment")
        return result

    dispatcher = FleetDispatcher(host.capacity, registry.tokens, ready=ready,
        role_for=lambda _task: "worker", policy_for=lambda _role: host.capacity.policy,
        active_counts=active_counts, make_spec=None, launch=launch,
        mcp_server_name="otto", mcp_tools=tuple(spec.name for spec in TOOL_SPECS), assignment_id=assignment_id,
        read_current=current)
    registry.bind_dispatcher(dispatcher)

    def settle_automatic_failure(project_id: str, alias: str, schedule_id: str,
                                 result: Mapping[str, Any]) -> Mapping[str, Any]:
        """Settle only an exact retained automatic launch proven to have no effects."""
        if (not isinstance(result, Mapping) or result.get("outcome") in {"succeeded", "replayed"}
                or result.get("provider_called") is not False
                or result.get("effects_started") is not False):
            raise PermissionError("automatic failure lacks explicit pre-effect evidence")
        view = views.get(project_id)
        if view is None:
            raise PermissionError("automatic failure project is no longer configured")
        state = view.server.state
        raw_ref = state.get("task_refs", {}).get(alias)
        worker = (state.get("workers") or {}).get(alias)
        if (not isinstance(raw_ref, Mapping) or not isinstance(worker, Mapping)
                or worker.get("automatic") is not True or worker.get("schedule_id") != schedule_id):
            raise PermissionError("automatic failure does not match the current retained worker")
        task = owner.graph.current(ResourceRef.from_dict(raw_ref))
        revision = admitted_revision(task.payload)
        if worker.get("automatic_revision") != revision:
            raise PermissionError("automatic failure task generation is no longer current")
        due = view.server.due_port.read_due(schedule_id)
        target = (due or {}).get("target") or {}
        evidence = (due or {}).get("host_evidence") or {}
        if (not isinstance(due, Mapping) or target.get("task_ref") != raw_ref
                or target.get("project_ref") != state.get("project_ref")
                or due.get("assignment_ref") != worker.get("assignment_ref")
                or evidence.get("gateway_attempt") is not None):
            raise PermissionError("automatic failure occurrence is missing, foreign, or uncertain")
        assignment = assignment_id(task)
        dispatch_record = dispatcher.records.get(assignment)
        if (dispatch_record is None or dispatch_record.state not in {"launched", "unknown"}
                or dispatch_record.task.ref.to_dict() != task.ref.to_dict()):
            raise PermissionError("automatic failure has no matching dispatched task generation")
        save_state = getattr(view.server, "_save_state", None)
        if not callable(save_state):
            raise PermissionError("automatic failure reason cannot be persisted by this project view")
        failures = state.setdefault("automatic_dispatch_failures", {})
        previous_failure = failures.get(alias)
        failures[alias] = {
            "admitted_revision": revision,
            "schedule_id": schedule_id,
            "reason": str((result.get("error") or {}).get("message")
                          or result.get("reason") or result.get("outcome"))[:512],
            "outcome": result.get("outcome"),
        }
        try:
            save_state()
        except Exception:
            if previous_failure is None:
                failures.pop(alias, None)
            else:
                failures[alias] = previous_failure
            raise
        dispatcher.finish(assignment, settled=True)
        return {"outcome": "settled", "assignment": assignment,
                "reason": state["automatic_dispatch_failures"][alias]["reason"]}

    host.settle_automatic_failure = settle_automatic_failure

    def dispatch_pump() -> Any:
        record = dispatcher.dispatch_ready(candidates())
        if record is None or not isinstance(record.result, Mapping):
            return record
        if record.result.get("outcome") != "known-pre-effect-failure":
            return record
        # dispatch_ready marks the callback returned normally as launched. Move
        # this exact proven pre-effect refusal to a settled state after that
        # transition, and remember its task generation so the alias does not
        # spin on every capacity tick. The next admitted generation is eligible.
        failure = record.result["failure"]
        alias = record.result["alias"]
        revision = record.result["admitted_revision"]
        view = views.get(record.result["project_id"])
        if view is not None and isinstance(alias, str):
            state = view.server.state
            expected_ref = getattr(record.task, "ref", None)
            if (state.get("task_refs", {}).get(alias) != expected_ref.to_dict()
                    or state.get("project_ref", {}).get("id") != record.result["project_id"]):
                raise DispatchError("failed automatic dispatch alias changed before settlement")
            save_state = getattr(view.server, "_save_state", None)
            if not callable(save_state):
                raise DispatchError("automatic failure reason cannot be persisted by this project view")
            failures = state.setdefault("automatic_dispatch_failures", {})
            previous_failure = failures.get(alias)
            failures[alias] = {
                "admitted_revision": revision,
                "reason": str((failure.get("error") or {}).get("message")
                              or failure.get("reason") or failure.get("outcome"))[:512],
                "outcome": failure.get("outcome"),
            }
            try:
                save_state()
            except Exception:
                if previous_failure is None:
                    failures.pop(alias, None)
                else:
                    failures[alias] = previous_failure
                raise
        dispatcher.finish(record.assignment, settled=True)
        return record

    host.dispatch_pump = dispatch_pump
    return dispatcher


def _source_next_append(store: Any) -> Optional[int]:
    try:
        return store.source_next_append
    except Exception:
        return None


def _supervising_kind(record: Any, hosts: Mapping[str, Any]) -> Optional[str]:
    """The admitted host whose root assignment supervises this project (as OwnerService._attach)."""
    supervisor = ((record.payload.get('metadata') or {}).get('otto_orchestrator') or {}).get('assignment_ref') or {}
    if not supervisor.get('id'):
        return None
    return next((kind for kind, entry in hosts.items()
                 if (entry.get('root_assignment_ref') or {}).get('id') == supervisor['id']), None)


HISTORY_BATCH = 100  # the bounded batch the installed controller uses too (install/controller/operating_service.py)


def start_history_projection(store: Any) -> dict[str, Any]:
    """Attach the project-history projection and catch it up before the owner serves (D03).

    Once attached, the Store projects each commit as it lands; this first pass
    projects the history that was already there, so at rest the checkpoint equals
    the last append position. A projection error refuses startup rather than
    serving a lagged history.
    """
    projection = store.configure_history_projection(batch_size=HISTORY_BATCH)
    result = projection.maintain(raise_on_error=True)
    while result['outcome'] == 'advanced':
        result = projection.maintain(raise_on_error=True)
    return result


def compose(config: Mapping[str, Any], *, hold_dispatch: bool = False, project: Optional[str] = None,
            adapter_factory: Optional[Callable[..., Any]] = None,
            trace: Optional[dict[str, Any]] = None) -> ProductOwner:
    """Open the one Store and compose the shared owner; nothing is admitted before settlement."""
    from herzchen.kernel.store import Store
    from otto.portfolio.execution_host import ExecutionHost
    from otto.portfolio.manager_journey_service import ManagerJourneyService
    from otto.portfolio.native_caller_ingress import NativeProcessCallerIngress
    from otto.portfolio.project_services import ProjectServices
    from .cli import _resolve_project

    trace = {'phases': [], 'store': {}} if trace is None else trace
    home = Path(config['home'])
    armed = False  # a retained stop marker only counts after the store lock proves it stale

    def checkpoint(phase: str) -> None:
        trace['phases'].append({'schema': 'otto.owner-startup-phase.v1', 'phase': phase, 'pid': os.getpid(),
                                'monotonic': time.monotonic(), 'provider_called': False})
        if armed and stop_marker(home).exists():
            raise StartupStopped('explicit stop before ' + phase)

    checkpoint('composition')
    runtime_dirs(config)
    lanes.private_dir(owner_lane(home))

    checkpoint('store-open')
    target = config['store']
    path = Path(target['path'])
    # The same custody checks HostSession applies before it opens the file.
    for part in (path, *path.parents):
        if part.exists() and stat.S_ISLNK(part.lstat().st_mode):
            raise PermissionError('Store path contains a symbolic link')
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or [info.st_dev, info.st_ino] != target['device_inode']):
        raise PermissionError('Store custody or identity changed since it was attached')
    store = Store.open(path, authority=target['authority'], expected_domains=host_domains(),
                       expected_domain_digest=target['domain_descriptor_digest'], admission='clean-close')
    trace['store'] = {'phase': 'admission-complete', 'admission_report': dict(store.admission_report),
                      'store_closed': False}

    # Holding the Store's writer lock proves no other owner is live, so a
    # retained stop marker from an earlier run is stale.
    stale_stop = stop_marker(home).exists()
    stop_marker(home).unlink(missing_ok=True)
    armed = True

    sessions: list[HostSession] = []
    root: Optional[HostSession] = None
    try:
        start_history_projection(store)
        with service_store(store):
            root = HostSession(config).__enter__()
        owner = root.owner

        # Runner evidence is shared by this owner; line specific fleets are created lazily when
        # an authenticated assignment resolves its current task plan.
        from otto.portfolio.execution_operations import commit_local_checkpoint
        result_store = ResultStore(home / "runner-results")
        from herzchen.fleet.capacity import CapacityPool
        from herzchen.fleet.runner.runner import Runner
        runner_policy = capacity_policy(config)
        runner_core = Runner(CapacityPool(CapacityPolicy(heavy_headroom=runner_policy.heavy_headroom)),
                             result_store, state_dir=home / "runner-state")
        runner = _DirectRunnerClient(runner_core)
        fleet_registry = OwnerFleetRegistry(owner, config, home, result_store,
                                            checkpoint=commit_local_checkpoint,
                                            due_port=root.due_port)
        fleet_registry.bind_runner(runner)
        views: dict[str, Any] = {}
        fleet_registry.bind_views(lambda: views)

        checkpoint('owner-construction')
        policy = capacity_policy(config)
        host_dir = lanes.private_dir(home / 'shared-host')

        # Enumerate activated projects; a receipt is named by its quoted run id.
        skipped: list[dict[str, str]] = []
        resolved: list[tuple[str, Any, str]] = []
        hosts = config.get('hosts') or {}
        receipts = home / 'receipts'
        for receipt in sorted(receipts.glob('activate-*.json')):
            run_id = unquote(receipt.stem[len('activate-'):])
            with service_store(store), HostSession(config) as listing:
                try:
                    record = _resolve_project(listing, run_id)
                except LookupError:
                    skipped.append({'project': run_id, 'reason': 'not registered in this Store'})
                    continue
            kind = _supervising_kind(record, hosts)
            if kind is None:
                skipped.append({'project': run_id, 'reason': 'no admitted host supervises it'})
                continue
            resolved.append((run_id, record, kind))
        if len(resolved) > MAX_PROJECT_VIEWS:
            raise ValueError('install between zero and sixteen explicit project views')
        if project is not None and not any(project in {record.ref.id, run_id} for run_id, record, _ in resolved):
            raise LookupError('project ' + project + ' is not registered, activated and supervised by an admitted host')

        # Bind the ingress at composition time so a later activation can attach
        # its view to this same host without replacing the socket/router.
        # Reservations stay in memory, as in the live start: a Store-backed ledger would write a
        # pool event into an empty Store at first start and pin the policy across restarts.
        try:
            caller_socket = socket_path(config, 'shared-project-services')
        except ValueError:
            if resolved:
                raise
            # Long staging homes have no callers yet. Keep the legacy empty
            # owner start available; any later project view still requires a
            # valid caller socket address.
            caller_socket = None
        host = ExecutionHost(directory=host_dir, handler=lambda request: None,
                             owner_path=home / 'run' / 'shared-host-owner.json',
                             socket_path=caller_socket,
                             owner_file_compatibility=True, bounded_transports=True,
                             capacity_policy=policy)
        def owner_executor(operation: Callable[[], Any]) -> Any:
            def run_owned() -> Any:
                with host._command_lock:
                    return host._owned(operation)
            return host._owner_request(run_owned)
        fleet_registry.bind_owner_executor(owner_executor)
        if hold_dispatch:
            host.hold_admission()

        def build_view(run_id: str, record: Any, kind: str,
                       installation: Mapping[str, Any] = config) -> Any:
            project_id = record.ref.id
            installed_hosts = installation.get('hosts') or {}
            view_session = None
            with service_store(store):
                try:
                    view_session = HostSession(installation, host=installed_hosts[kind], project_ids=(project_id,)).__enter__()
                    # One Due port for the whole composition: ProjectServices requires identity, not equality.
                    view_session.due_port = root.due_port
                    view_session.owner.landed_worker_settler = fleet_registry.settle_landed_worker
                    server = HostOwnerService(view_session, record, adapter_factory=adapter_factory,
                                              execution_host=host,
                                              worker_mcp_provider=fleet_registry.grant_for_due,
                                              worker_lab_provider=fleet_registry.prepare_worker_lab,
                                              worker_context_provider=fleet_registry.worker_context_for_due)
                    server._save_state()
                    service_view = ManagerJourneyService(
                        server=server, host=host, run_path=server.render_run_view(), workspace=server.worktree(),
                        orchestrator_principal=view_session.actor.actor,
                        observe_schedules=closeout_observer(view_session.owner, project_id),
                        help_reply_authorizer=server.reply_authorizer(),
                        delegation_policy=(installation.get('policies') or {}).get('delegation'),
                        external_execution_policy=(installation.get('policies') or {}).get('external_execution'))
                except BaseException:
                    if view_session is not None:
                        view_session.__exit__(None, None, None)
                    raise
                sessions.append(view_session)
            server._execution = service_view._execution
            views[project_id] = service_view
            return service_view

        for run_id, record, kind in resolved:
            checkpoint('view-' + run_id)
            build_view(run_id, record, kind)

        bind_automatic_dispatch(host, fleet_registry, views)

        checkpoint('router-install')
        relay = SharedLaneRelay(home, host)
        router = ProjectServices(views, owner_route=relay.owner_route, host=host,
                                 due_port=root.due_port, store=store)
        ingress = NativeProcessCallerIngress(router.managed_caller_binding)
        for service_view in views.values():
            service_view.server.native_callers = ingress
        host.caller_binding_reader = ingress
        # Retained work is settled here, while the host is still closed.
        if hold_dispatch:
            reconciliation = router.install_inert(checkpoint=checkpoint)
        else:
            reconciliation = router.install()

        checkpoint('client-issuance')
        service = ProjectOwnerService({**config, 'max_active_manager_turns': min(policy.manager_units, MAX_PROJECT_VIEWS)},
                                      router=router, protected_relay=relay.protected_relay)
        def build_activated_view(project: str) -> Any:
            from .cli import _resolve_project
            installation = service.config
            live_hosts = installation.get('hosts') or {}
            with service_store(store), HostSession(installation) as listing:
                record = _resolve_project(listing, project)
            if record.ref.id in router.services:
                return router._project(record.ref.to_dict())
            kind = _supervising_kind(record, live_hosts)
            if kind is None:
                raise LookupError('activated project is not supervised by an admitted host')
            view = build_view(project, record, kind, installation)
            view.server.native_callers = ingress
            try:
                router.add_view(record.ref.id, view)
            except BaseException:
                views.pop(record.ref.id, None)
                sessions[-1].__exit__(None, None, None)
                sessions.pop()
                raise
            return view
        service._build_activated_view = build_activated_view
        relay.service = service

        if hold_dispatch:
            host.hold_admission({'pid': os.getpid(), 'dispatch': 'held',
                                 'admission_report': dict(store.admission_report),
                                 'phase_timings': list(trace['phases']),
                                 'composition_source_next_append': _source_next_append(store)})
        checkpoint('composition-complete')
        trace['store']['source_next_append'] = _source_next_append(store)
        return ProductOwner(store=store, host=host, router=router, service=service, relay=relay, root=root,
                            sessions=sessions, views=views, skipped=skipped, reconciliation=reconciliation,
                            policy=policy, hold_dispatch=hold_dispatch, stale_stop=stale_stop,
                            fleet_registry=fleet_registry, result_store=result_store, runner=runner_core)
    except BaseException:
        # A partial composition may already own a facade socket and runner. Close
        # them before releasing sessions and the unsealed Store.
        try:
            registry = locals().get("fleet_registry")
            if registry is not None:
                registry.close()
            runner_value = locals().get("runner_core")
            if runner_value is not None:
                runner_value.stop()
            for session in sessions:
                session.__exit__(None, None, None)
            if root is not None:
                root.__exit__(None, None, None)
        finally:
            close_store(store, seal=False, trace=trace)
        raise


def close_store(store: Any, *, seal: bool, trace: Optional[dict[str, Any]] = None) -> None:
    """Close the Store, sealing it only when asked; a failed close is recorded as unverified."""
    try:
        store.close(seal=seal)
    except BaseException:
        if trace is not None:
            trace.setdefault('store', {}).update(store_closed=False, seal_requested=seal, close_outcome='unverified')
        raise
    if trace is not None:
        trace.setdefault('store', {}).update(
            store_closed=True, seal_requested=seal,
            sealed=getattr(store, 'admission_report', {}).get('seal') == 'written')


@contextmanager
def _home_custody(home: Path):
    """Hold the stable home lock across composition, host ownership, and cleanup."""
    from herzchen.kernel.store import WriterBusyError

    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(home / '.owner-service.lock', flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError('owner home lock must be a regular file owned by this account')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise
            raise WriterBusyError('another owner holds the home lock') from error
        yield
    finally:
        os.close(fd)


def run_product_service(config: Mapping[str, Any], *, emit: Callable[[Mapping[str, Any]], None],
                        hold_dispatch: bool = False, project: Optional[str] = None,
                        adapter_factory: Optional[Callable[..., Any]] = None,
                        requested_manager_limit: Optional[int] = None) -> dict[str, Any]:
    """What ``ottoctl service run`` calls: hold home custody through all owner cleanup."""
    with _home_custody(Path(config['home'])):
        return _run_product_service_locked(
            config, emit=emit, hold_dispatch=hold_dispatch, project=project,
            adapter_factory=adapter_factory, requested_manager_limit=requested_manager_limit)


def _run_product_service_locked(config: Mapping[str, Any], *, emit: Callable[[Mapping[str, Any]], None],
                                hold_dispatch: bool = False, project: Optional[str] = None,
                                adapter_factory: Optional[Callable[..., Any]] = None,
                                requested_manager_limit: Optional[int] = None) -> dict[str, Any]:
    from herzchen.kernel.store import AdmissionStopped
    from .cli import _writer_busy

    home = Path(config['home'])
    trace: dict[str, Any] = {'phases': [], 'store': {}}
    try:
        if requested_manager_limit is not None and not (
                type(requested_manager_limit) is int and 1 <= requested_manager_limit <= capacity_policy(config).manager_units):
            # The pool sets the per-role limits; a flag may only ask for fewer.
            raise ValueError('requested manager limit exceeds the capacity pool')
        owner = compose(config, hold_dispatch=hold_dispatch, project=project,
                        adapter_factory=adapter_factory, trace=trace)
    except (StartupStopped, AdmissionStopped):
        emit({'outcome': 'stopped-before-serving', 'provider_called': False})
        return {'outcome': 'stopped', 'provider_called': False}
    except Exception as error:
        # A second owner that finds the writer lock busy must not write a refusal record.
        if isinstance(error, _writer_busy()):
            raise
        write_startup_refusal(home, error, trace)
        emit({'outcome': 'startup-refused', 'error': {'code': type(error).__name__, 'message': str(error)[:4096]},
              'provider_called': False})
        raise SystemExit(EXIT_STARTUP_REFUSED)

    served = normal = False
    result: Optional[dict[str, Any]] = None
    try:
        if stop_marker(home).exists():
            emit({'outcome': 'stopped-before-serving', 'provider_called': False})
            result = {'outcome': 'stopped', 'provider_called': False}
        else:
            _start_owner_host(owner)
            served = True
            owner.service.start_heartbeat()
            policy = owner.policy
            emit({'outcome': 'ready', 'pid': os.getpid(), 'generation': owner.service.generation,
                  'owner': config['owner']['actor'], 'hosts': sorted(owner.service._host_lanes()),
                  'owner_lane': str(owner_lane(home)), 'status': str(status_path(home)),
                  'stop_file': str(stop_marker(home)), 'stale_stop_marker_removed': owner.stale_stop,
                  'attached_project': owner.service._attached(), 'provider_called': False, 'dues_started': 0,
                  'attached_projects': [view.server.run_id for view in owner.views.values()],
                  'skipped_projects': owner.skipped, 'startup': owner.reconciliation,
                  'dispatch': 'held' if owner.hold_dispatch else 'open',
                  'capacity': {'manager_units': policy.manager_units, 'worker_units': policy.worker_units,
                               'heavy_headroom': policy.heavy_headroom, 'turn_units': policy.turn_units}})
            owner.host.wait_until_stopped(owner.service.stop_requested, idle_poll=owner.service.poll)
            normal = True
    finally:
        # Draining keeps the status honest while host and Store are still open.
        drain_error: Optional[str] = None
        try:
            owner.service.begin_draining()
        except Exception as error:  # the host and Store must still be released
            drain_error = type(error).__name__
            trace['drain_error'] = drain_error
        orderly = False
        try:
            owner.host.close()
            orderly = served and normal
        finally:
            try:
                owner.fleet_registry.close()
                owner.runner.stop()
            finally:
                try:
                    for session in owner.sessions:
                        session.__exit__(None, None, None)
                    owner.root.__exit__(None, None, None)
                finally:
                    close_store(owner.store, seal=orderly and owner.store.admission_report.get('mode') == 'clean-close',
                                trace=trace)
        owner.relay.release()
        # Only after the Store is released may the status say closed.
        owner.service.finalize_closed()
        closed = {'outcome': 'closed'}
        if drain_error is not None:
            closed['drain_error'] = drain_error
        emit(closed)

    if result is not None:
        return result
    return {'outcome': 'closed', 'generation': owner.service.generation, 'requests_served': owner.service.served,
            'relays_open': len(owner.service.relays), 'owner_exit_requested': stop_marker(home).exists(),
            'closure': _requested_closure(home), 'provider_called': False}

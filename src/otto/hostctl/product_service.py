"""The product start of ``ottoctl service run``: one owner over one Store.

This composes the same owner the live shared-operating wrapper composes, from
the supported owner APIs only: ONE open Store, ONE shared bounded
``ExecutionHost``, one ``ManagerJourneyService`` view per activated project
behind the ``ProjectServices`` router, the router's startup settlement BEFORE
the host starts, the dispatch hold, a startup-refusal record with exit 78, and
a close that releases the host and the Store before the status reads closed.
Nothing here calls a provider or starts a Due.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Callable, Mapping, Optional
from urllib.parse import unquote

from herzchen.fleet.capacity import CapacityPolicy

from . import lanes
from .owner import HostSession, host_domains, runtime_dirs, service_store
from .project_service import ProjectOwnerService
from .serve import HostOwnerService, request_digest, socket_path
from .service import _RELAYED, owner_lane, stop_marker, status_path

EXIT_STARTUP_REFUSED = 78
REFUSAL_SCHEMA = 'otto.owner-startup-refusal.v1'
CLOSEOUT_RECORD_LIMIT = 100
GRANT_SCHEMA = 'otto.shared-lane-grant.v1'
MAX_PROJECT_VIEWS = 16
FIELDS = {name: (name,) for name in ('schedule_id', 'project_ref', 'owner', 'interval_seconds', 'stop_state')}


class StartupStopped(RuntimeError):
    """An explicit stop was requested while the owner was still composing."""


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
        if hold_dispatch:
            host.hold_admission()

        views: dict[str, Any] = {}

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
                    server = HostOwnerService(view_session, record, adapter_factory=adapter_factory,
                                              execution_host=host)
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
                            policy=policy, hold_dispatch=hold_dispatch, stale_stop=stale_stop)
    except BaseException:
        # Nothing was started, so only the sessions and the Store are released; the
        # Store closes without a seal because this composition never completed.
        try:
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


def run_product_service(config: Mapping[str, Any], *, emit: Callable[[Mapping[str, Any]], None],
                        hold_dispatch: bool = False, project: Optional[str] = None,
                        adapter_factory: Optional[Callable[..., Any]] = None,
                        requested_manager_limit: Optional[int] = None) -> dict[str, Any]:
    """What ``ottoctl service run`` calls: compose, serve until stopped, then close in order."""
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
            owner.host.start()
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
            'relays_open': len(owner.service.relays), 'provider_called': False}

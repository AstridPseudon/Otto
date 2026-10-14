"""Host client lanes on the already composed ProjectServices owner.

This adapter owns no Store, per-project host or native semaphore. Its only
thread is the short-lived cached-status pulse started after the shared host
starts. Its
finite poll runs on the existing serialized owner; all execution remains in
the installed shared host. New projects stay pending until an ordinary closed
composition installs their view, preserving original activation and budgets.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Mapping
import os
from types import MappingProxyType
import threading
import time

from .owner import service_store, runtime_dirs
from .service import OwnerService, owner_lane, status_path, stop_marker
from . import lanes


class ProjectOwnerService(OwnerService):
    def __init__(self, config: Mapping[str, Any], *, router: Any,
                 protected_relay: Callable[..., Any] | None = None,
                 startup_report_reader: Callable[[], Mapping[str, Any]] | None = None) -> None:
        host = router.host
        if not host.bounded_transports or router.store is None:
            raise ValueError('existing bounded project owner required')
        limit = config.get('max_active_manager_turns', 3)
        if limit != host.manager_turn_limit:
            raise ValueError('installation manager limit differs from adopted shared host')
        super().__init__(config, max_active_manager_turns=limit)
        self.router, self.shared_host, self.store = router, host, router.store
        self.protected_relay = protected_relay
        # Set by the shared composition to return the owner's already-scoped
        # view of startup qualifications and held capacity effects.
        self.startup_report_reader = startup_report_reader
        self.started_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        runtime_dirs(self.config)
        self.generation = self._next_generation()
        lanes.private_dir(owner_lane(self.home))
        self._last_status = 0.0
        # The embedded owner cannot use OwnerService._heartbeat: that method
        # calls _publish() from a foreign thread, which would read the shared
        # host and enqueue on its owner queue.  Keep a private immutable
        # projection instead.  The pulse thread only touches this cache, the
        # frozen output paths, and these local lifecycle fields.
        self._heartbeat_lock = threading.RLock()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_starting = False
        self._closed = False
        self._draining = False
        self._finalized = False
        self._heartbeat_snapshot: Mapping[str, Any] | None = None
        self._heartbeat_paths: tuple[Path, ...] = ()
        self._heartbeat_interval = float(self.heartbeat_seconds)

    def run(self, **_: Any) -> Any:
        raise RuntimeError('embedded host lanes are polled by the existing owner; never open another service')

    def call(self, operation: Callable[[], Any], *, hold_during_turn: bool = False) -> Any:
        def finite():
            if hold_during_turn and (self.shared_host._executions or self.shared_host._capacity_holds):
                return {'outcome': 'held', 'reason': 'execution-changing operation requires a closed owner boundary',
                        'retry': False, 'effects_started': False, 'provider_called': False}
            with service_store(self.store):
                return operation()
        return self.shared_host._status_read({'command': 'host-client-operation'}, finite)

    def poll(self) -> None:
        def finite():
            if getattr(self.shared_host, 'dispatch_held', False):
                # Keep the authenticated local owner read lane available while
                # retaining every queued mutation and all host/relay requests.
                self._poll(owner_lane(self.home), 'owner', self._owner_command,
                           allowed_commands={'status'})
            else:
                self._poll(owner_lane(self.home), 'owner', self._owner_command)
                for kind, lane in self._host_lanes().items():
                    self._poll(lane, kind, self._host_command)
                self._poll_relays()
            if time.monotonic() - self._last_status >= self.heartbeat_seconds:
                self._publish(); self._last_status = time.monotonic()
        self.shared_host._status_read({'command': 'host-client-poll'}, finite)

    def start_heartbeat(self) -> None:
        """Project status on the owner, then start the embedded pulse.

        The wrapper calls this only after the shared host's actual ``start``.
        Initial projection and path discovery therefore run through the same
        serialized owner boundary as all other operations.  Subsequent pulses
        never call ``_status``, inspect the router/host/config, or use the
        host's owner request queue.
        """
        with self._heartbeat_lock:
            if self._closed:
                raise RuntimeError('embedded owner service is closed')
            if self._heartbeat_thread is not None or self._heartbeat_starting:
                return
            self._heartbeat_starting = True

        try:
            def initialize() -> None:
                value = self._status()
                value['projection_at'] = self._now_status_time()
                self._remember_and_publish(value, self._status_paths())

            self.shared_host._status_read({'command': 'host-client-heartbeat-start'}, initialize)
        except BaseException:
            with self._heartbeat_lock:
                self._heartbeat_starting = False
            raise

        with self._heartbeat_lock:
            self._heartbeat_starting = False
            if self._closed:
                return
            self._stopping.clear()
            thread = threading.Thread(target=self._heartbeat, name='otto-embedded-heartbeat', daemon=True)
            self._heartbeat_thread = thread
            # Start while holding the publication lock so close() cannot
            # observe an unstarted thread, publish closed, and then race with
            # this start into a live pulse.
            thread.start()

    def stop_requested(self) -> bool:
        return stop_marker(self.home).exists()

    def _owner_command(self, who: str, request: Mapping[str, Any], token: str, lane: Path) -> Any:
        # This is the existing owner-lane status operation. It remains local
        # owner-authenticated and does not borrow any manager caller identity.
        if request.get('command') == 'status' and getattr(self.shared_host, 'dispatch_held', False):
            value = self._status()
            value['dispatch'] = 'held'
            value['startup'] = self._inert_startup_report()
            return value
        return super()._owner_command(who, request, token, lane)

    def _inert_startup_report(self) -> dict[str, Any]:
        """Return public startup facts plus only the owner-scoped qualification view."""
        source = getattr(self.shared_host, '_startup_report', None)
        source = source if isinstance(source, Mapping) else {}
        report = {key: copy.deepcopy(source[key]) for key in (
            'source_commit', 'manifest_sha256', 'pid', 'dispatch',
            'admission_report', 'phase_timings', 'business_reconciliation', 'composition_source_next_append') if key in source}
        scoped = self.startup_report_reader() if callable(self.startup_report_reader) else {}
        if not isinstance(scoped, Mapping):
            raise TypeError('owner startup report reader must return a mapping')
        for key in ('current_context_qualified', 'context_qualifications',
                    'held_capacity_effects', 'qualification_scope', 'source_next_append'):
            if key in scoped:
                report[key] = copy.deepcopy(scoped[key])
        # Never expose foreign schedule identifiers just because the owner
        # status lane has broader filesystem custody than a project caller.
        report['held_capacity_count'] = len(getattr(self.shared_host, '_capacity_holds', {}))
        report['dispatch'] = 'held'
        report['provider_called'] = False
        return report

    def close(self) -> None:
        """Compatibility close for standalone/preflight service callers.

        The embedded-host wrapper uses begin_draining(), closes the host and
        Store, then calls finalize_closed(); this method preserves the older
        service-only close behavior for callers that own no such teardown.
        """
        with self._heartbeat_lock:
            thread = self._heartbeat_thread
            started = thread is not None or self._heartbeat_starting
            self._closed = True
            self._stopping.set()
        if thread is not None and thread.is_alive():
            thread.join()

        if not started:
            self._publish(state='closed')  # preflight has no heartbeat/owner queue
            with self._heartbeat_lock:
                self._finalized = True
            return

        try:
            self.shared_host._status_read(
                {'command': 'host-client-heartbeat-close'},
                lambda: self._publish(state='closed'))
            with self._heartbeat_lock:
                self._finalized = True
        except (OSError, RuntimeError):
            # If the actual shared owner is already dead, leave its last
            # serving projection for read_status() to reject by PID/freshness.
            # Do not manufacture a closed claim from a dead owner.
            return

    def begin_draining(self) -> None:
        """Publish a draining phase while keeping the cached heartbeat alive.

        This must run before the wrapper closes the shared host.  It never
        reads the owner queue: the last immutable projection remains the
        status basis while admitted work is allowed to finish.
        """
        with self._heartbeat_lock:
            if self._closed:
                raise RuntimeError('embedded owner service is closed')
            if self._draining:
                return
            cached = self._heartbeat_snapshot
            if cached is None:
                if self._heartbeat_starting or self._heartbeat_thread is not None:
                    raise RuntimeError('embedded owner has no cached serving projection to drain')
                # Preserve the preflight path: no heartbeat or owner queue was
                # ever started, so a local projection is still safe here.
                value = self._status()
                value['projection_at'] = self._now_status_time()
                self._heartbeat_paths = self._status_paths()
            else:
                value = copy.deepcopy(dict(cached))
            value['state'] = 'draining'
            value['outcome'] = 'draining'
            value['shutdown_phase'] = 'draining'
            value['draining_at'] = self._now_status_time()
            self._draining = True
            self._heartbeat_snapshot = MappingProxyType(copy.deepcopy(value))
            paths = self._heartbeat_paths or (status_path(self.home),)
            self._heartbeat_paths = tuple(paths)
            self._write_status(self._heartbeat_paths, value)

    def finalize_closed(self) -> None:
        """Publish CLOSED from the cached projection after host and Store close.

        The caller contract is the wrapper sequence: begin_draining();
        shared_host.close(); store.close(); finalize_closed().  In particular,
        this method never asks a released owner queue for a fresh projection.
        """
        with self._heartbeat_lock:
            if self._closed:
                return
            thread = self._heartbeat_thread
            self._closed = True
            self._stopping.set()
        if thread is not None and thread.is_alive():
            thread.join()
        with self._heartbeat_lock:
            if self._heartbeat_snapshot is None:
                # Standalone/preflight shutdown retains the legacy local
                # projection path; a started host must have a cached snapshot.
                if self._heartbeat_starting or thread is not None:
                    raise RuntimeError('cannot close an embedded owner without its cached projection')
                value = self._status(state='closed')
                value['projection_at'] = self._now_status_time()
                self._heartbeat_paths = (status_path(self.home),)
            else:
                value = copy.deepcopy(dict(self._heartbeat_snapshot))
            if self._draining:
                # These values describe the last owner projection.  Once the
                # queue and Store are released, retain the evidence without
                # presenting native/manager activity as freshly observed.
                last_projection = {
                    key: copy.deepcopy(value[key]) for key in (
                        'projection_at', 'manager_turns', 'manager_turn_active',
                        'native_capacity', 'in_flight', 'attached_projects', 'store_open_count')
                    if key in value
                }
                value['last_projection'] = last_projection
                for key in ('manager_turns', 'manager_turn_active', 'native_capacity', 'in_flight'):
                    value.pop(key, None)
                value['store_open_count'] = 0
                value['store_closed'] = True
                value['post_projection_liveness'] = 'unobserved_after_host_and_store_release'
            value['state'] = 'closed'
            value['outcome'] = 'closed'
            value['shutdown_phase'] = 'closed'
            value['closed_at'] = self._now_status_time()
            value['closure_provenance'] = ('host-and-store-released' if self._draining
                                           else 'standalone-service-close')
            value['heartbeat_at'] = value['closed_at']
            self._heartbeat_snapshot = MappingProxyType(copy.deepcopy(value))
            paths = self._heartbeat_paths or (status_path(self.home),)
            self._heartbeat_paths = tuple(paths)
            self._write_status(self._heartbeat_paths, value)
            self._finalized = True

    @staticmethod
    def _now_status_time() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def _status_paths(self) -> tuple[Path, ...]:
        paths = [status_path(self.home)]
        paths.extend(lane / lanes.STATUS_FILE for lane in self._host_lanes().values()
                     if lane.is_dir())
        return tuple(paths)

    @staticmethod
    def _write_status(paths: tuple[Path, ...], value: Mapping[str, Any]) -> None:
        for path in paths:
            lanes.atomic_json(path, value)

    def _remember_and_publish(self, value: Mapping[str, Any], paths: tuple[Path, ...]) -> None:
        # Copy before caching so later owner-side mutation cannot alter what a
        # pulse observes.  MappingProxyType prevents accidental top-level
        # mutation; pulse copies it back to an ordinary dict before changing
        # heartbeat_at.
        snapshot = copy.deepcopy(dict(value))
        with self._heartbeat_lock:
            if self._finalized:
                return
            if self._closed and snapshot.get('state') != 'closed':
                return
            current = self._heartbeat_snapshot
            if self._draining and current is not None:
                snapshot['state'] = 'draining'
                snapshot['outcome'] = 'draining'
                snapshot['shutdown_phase'] = 'draining'
                snapshot['draining_at'] = current.get('draining_at')
                snapshot['projection_at'] = current.get('projection_at')
            self._heartbeat_snapshot = MappingProxyType(snapshot)
            self._heartbeat_paths = tuple(paths)
            self._write_status(self._heartbeat_paths, snapshot)

    def _publish(self, state: str = 'serving') -> None:
        value = self._status(state)
        value['projection_at'] = self._now_status_time()
        with self._heartbeat_lock:
            if self._closed and state != 'closed':
                return
            heartbeat_active = self._heartbeat_starting or self._heartbeat_thread is not None
        if heartbeat_active:
            self._remember_and_publish(value, self._status_paths())
        else:
            self._write_status((status_path(self.home),), value)
            for lane in self._host_lanes().values():
                if lane.is_dir():
                    self._write_status((lane / lanes.STATUS_FILE,), value)

    def _heartbeat(self) -> None:
        while not self._stopping.wait(self._heartbeat_interval):
            with self._heartbeat_lock:
                if self._heartbeat_snapshot is None:
                    continue
                value = copy.deepcopy(dict(self._heartbeat_snapshot))
                value['heartbeat_at'] = self._now_status_time()
                paths = self._heartbeat_paths
                try:
                    self._write_status(paths, value)
                except OSError:
                    pass

    def _view_for(self, kind: str, project: str) -> Any:
        from .cli import _resolve_project
        from .owner import HostSession
        entry = self.config['hosts'][kind]
        with service_store(self.store), HostSession(self.config, host=entry) as session:
            record = _resolve_project(session, project)
            root = session.root_assignment()
        supervisor = (record.payload.get('metadata') or {}).get('otto_orchestrator') or {}
        ref = supervisor.get('assignment_ref') or {}
        if (ref.get('id') != root.ref.id or supervisor.get('generation', root.generation) != root.generation):
            raise PermissionError('project is not currently supervised by this admitted host')
        return self.router._project(record.ref.to_dict())

    def _relay_manager(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        from otto.portfolio.manager_journey_client import requires_native_caller, read_command_status
        request = dict(args.get('request') or {})
        command = request.get('command')
        if command not in {'command-status', 'read-help', 'respond-help', 'start-manager', 'manager-continue'}:
            raise PermissionError('identity-bearing manager commands require the original owner-launched native caller')
        view = self._view_for(kind, args['project'])
        if command == 'command-status':
            return read_command_status(self.shared_host.directory, request['request_id']) or {
                'outcome': 'unavailable', 'terminal': False, 'retry': False}
        if self.protected_relay is None:
            return {'outcome': 'held', 'reason': 'owner-installed exact relay grant is not composed',
                    'provider_called': False, 'effects_started': False, 'retry': False}
        # This callback authenticates the host's current root/view and issues an
        # exact owner request grant before retained publication. Never infer a
        # target from public project JSON or bypass ProjectServices routing.
        return self.protected_relay(kind=kind, view=view, request=request,
                                    token=token, lane=lane, installation=self.config)

    def _relay_reply(self, kind: str, args: Mapping[str, Any], token: str, lane: Path) -> Any:
        request = {'command': 'respond-help', **{key: args[key] for key in
            ('request_key', 'issue_id', 'authority_source', 'response', 'proposed_solution', 'next_action')}}
        return self._relay_manager(kind, {'project': args['project'], 'request': request}, token, lane)

    def _attach(self, project: str, *, host_kind: str | None) -> Any:
        if host_kind is None:
            raise PermissionError('attach cannot replace an already installed project view; recompose at closed custody')
        return self._view_for(host_kind, project)

    def _drain_project(self, project: str) -> Mapping[str, Any]:
        return {'outcome': 'held', 'reason': 'shared project drain uses the installed owner custody command',
                'provider_called': False, 'effects_started': False, 'retry': False}

    def _attached_projects(self) -> list[dict[str, Any]]:
        return [{'project_id': v.server.state['project_ref']['id'], 'run_id': v.run_path.name,
                 'manager': v.server.state['manager']} for v in self.router.services.values()]

    def _attached(self) -> None:
        return None

    def _status(self, state: str = 'serving') -> dict[str, Any]:
        value = super()._status(state)
        active = {**self.shared_host._capacity_holds, **{
            key: item['scope'] for key, item in self.shared_host._executions.items() if item['running']}}
        managers = [v for v in active.values() if v['role'] == 'manager']
        value.update(shared_project_owner=True,
            manager_turns={'active': len(managers), 'active_projects': sorted(v['project'] for v in managers),
                           'limit': self.shared_host.manager_turn_limit},
            manager_turn_active=bool(managers),
            native_capacity={'active_or_uncertain': len(active), 'total_limit': 3, 'worker_limit': 2,
                             'manager_limit': self.shared_host.manager_turn_limit,
                             'holds': sorted(self.shared_host._capacity_holds)},
            store_open_count=1, notification_mode='receipt-inspection')
        return value

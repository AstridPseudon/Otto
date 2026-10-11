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
                 protected_relay: Callable[..., Any] | None = None) -> None:
        host = router.host
        if not host.bounded_transports or router.store is None:
            raise ValueError('existing bounded project owner required')
        limit = config.get('max_active_manager_turns', 3)
        if limit != host.manager_turn_limit:
            raise ValueError('installation manager limit differs from adopted shared host')
        super().__init__(config, max_active_manager_turns=limit)
        self.router, self.shared_host, self.store = router, host, router.store
        self.protected_relay = protected_relay
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

    def close(self) -> None:
        # A pulse may already have copied a serving snapshot.  Stop and join
        # it before publishing closed, otherwise a late serving pulse could
        # overwrite the final state.  The wrapper normally calls this while
        # the shared host is still alive, so the final snapshot is serialized
        # through that host too.
        with self._heartbeat_lock:
            thread = self._heartbeat_thread
            started = thread is not None or self._heartbeat_starting
            self._closed = True
            self._stopping.set()
        if thread is not None and thread.is_alive():
            thread.join()

        if not started:
            self._publish(state='closed')  # preflight has no heartbeat/owner queue
            return

        try:
            self.shared_host._status_read(
                {'command': 'host-client-heartbeat-close'},
                lambda: self._publish(state='closed'))
        except (OSError, RuntimeError):
            # If the actual shared owner is already dead, leave its last
            # serving projection for read_status() to reject by PID/freshness.
            # Do not manufacture a closed claim from a dead owner.
            return

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
            if self._closed and snapshot.get('state') != 'closed':
                return
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

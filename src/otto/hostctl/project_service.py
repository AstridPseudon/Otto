"""Host client lanes on the already composed ProjectServices owner.

This adapter owns no Store, thread, per-project host or native semaphore. Its
finite poll runs on the existing serialized owner; all execution remains in
the installed shared host. New projects stay pending until an ordinary closed
composition installs their view, preserving original activation and budgets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
import os
import time

from .owner import service_store, runtime_dirs
from .service import OwnerService, owner_lane, stop_marker
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

    def stop_requested(self) -> bool:
        return stop_marker(self.home).exists()

    def close(self) -> None:
        self._publish(state='closed')  # borrowed Store and host remain caller-owned

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

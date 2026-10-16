"""Owner-only closed composition of an existing activated registered view.

No Store opener, process lifecycle, provider dispatch, materialization or new
assignment is present. Host-lane relays keep the inherited retained pending
mapping and pass through the original ExecutionHost admission/dispatch path.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from herzchen.contracts import ResourceRef


def identity(value):
    return tuple(value[key] for key in ('authority', 'kind', 'id'))


def activation_boundary(host):
    """Same exact ledger as ProjectOwnerService.call, including queued work."""
    queued = sorted(key for key, value in host._executions.items() if not value['running'])
    running = sorted(key for key, value in host._executions.items() if value['running'])
    holds = sorted(host._capacity_holds)
    return {'schema': 'otto.execution-changing-boundary.v1',
            'eligible': not host._executions and not host._capacity_holds,
            'queued_schedule_ids': queued, 'running_schedule_ids': running,
            'capacity_hold_schedule_ids': holds, 'provider_called': False}


def qualify_existing_view(router, service, *, expected_project_id, expected_supervisor_ref,
                          expected_supervisor_principal, expected_run_id):
    host, owner, state = router.host, service.server.owner, service.server.state
    if (host._threads or host._executions or host._capacity_holds or not host.bounded_transports
            or service.host is not host or service.server.due_port is not router.due_port
            or service.server.store is not router.store
            or owner.owner_actor != next(iter(router.services.values())).server.owner.owner_actor):
        raise PermissionError('the same closed idle owner, Store, Due port and host are required')
    if state['project_ref']['id'] != expected_project_id or state.get('run_id') != expected_run_id:
        raise PermissionError('registered project/run identity differs')
    stable = ResourceRef.from_dict({key: state['project_ref'][key] for key in ('authority', 'kind', 'id')})
    project = owner.graph.current(stable)
    relation = project.payload.get('metadata', {}).get('otto_orchestrator', {})
    supervisor = owner.assignments.get(ResourceRef.from_dict(expected_supervisor_ref))
    if (project.ref.to_dict() != state['project_ref']
            or relation.get('assignment_ref') != supervisor.ref.to_dict()
            or relation.get('generation') != supervisor.generation
            or supervisor.ref.to_dict() != dict(expected_supervisor_ref)
            or supervisor.role != 'orchestrator' or supervisor.principal != expected_supervisor_principal
            or state.get('orchestrator_assignment_ref') != supervisor.ref.to_dict()):
        raise PermissionError('current canonical project supervision differs')
    manager = owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
    if (manager.ref.to_dict() != state['assignment_ref'] or manager.generation != state['manager_generation']
            or manager.principal != state['manager'] or manager.role != 'manager'
            or identity(manager.scope.to_dict()) != identity(state['project_ref'])):
        raise PermissionError('original current project manager differs')
    schedule = state.get('schedule_id')
    due = router.due_port.read_due(schedule) if isinstance(schedule, str) else None
    if (not isinstance(due, dict) or due['assignment_ref'] != manager.ref.to_dict()
            or due['generation'] != manager.generation or due['recipient'] != manager.principal
            or due['role'] != 'manager' or identity(due['target']['project_ref']) != identity(state['project_ref'])
            or (due['requested_model'], due['requested_reasoning']) !=
               (state['requested_model'], state['requested_reasoning'])):
        raise PermissionError('original prepared or retained manager occurrence differs')
    return {'project_ref': project.ref.to_dict(), 'supervisor_ref': supervisor.ref.to_dict(),
            'supervisor_generation': supervisor.generation, 'supervisor_principal': supervisor.principal,
            'manager_ref': manager.ref.to_dict(), 'manager_generation': manager.generation,
            'schedule_id': schedule, 'run_id': expected_run_id, 'provider_called': False}


def attach_registered_view(*, router, service, native_ingress, view_key, expected_project_id,
                           expected_supervisor_ref, expected_supervisor_principal, expected_run_id):
    from otto.hostctl.lanes import read_private_json
    from otto.hostctl.serve import request_digest, GRANT_SCHEMA
    proof = qualify_existing_view(router, service, expected_project_id=expected_project_id,
        expected_supervisor_ref=expected_supervisor_ref,
        expected_supervisor_principal=expected_supervisor_principal, expected_run_id=expected_run_id)
    host = router.host
    if (host.caller_binding_reader is not native_ingress or view_key in router.services
            or len(router.services) >= 16 or getattr(service, '_fixed_project_binding', None) is not None):
        raise PermissionError('unique bounded view and the original native ingress are required')
    previous_route = router.owner_route
    def owner_route(request):
        handle = host.command_handle() or {}
        token = handle.get('request_id') if handle.get('transport') == 'file-ipc' else None
        grant = read_private_json(service.server.paths['grants'] / (token + '.json')) if token else None
        if grant is not None:
            # Grant is written only by the already-authenticated host-lane
            # callback below. A request field never selects an actor or view.
            if (grant.get('schema') != GRANT_SCHEMA or grant.get('token') != token
                    or grant.get('digest') != request_digest(request)
                    or grant.get('principal') != proof['supervisor_principal']):
                raise PermissionError('own host relay grant differs')
            qualify_existing_supervision(service, proof)
            return view_key
        if previous_route is None:
            raise PermissionError('request has no authenticated owner route')
        return previous_route(request)
    # Preserve the installed router subclass's terminal and optional-held-view
    # startup behavior. Recovery executes no provider and retains existing Dues.
    expanded = type(router)({**dict(router.services), view_key: service}, owner_route=owner_route)
    recovered = expanded.install()
    native_ingress.binding_factory = expanded.managed_caller_binding
    service.server.native_callers = native_ingress
    return expanded, {**proof, 'outcome': 'attached-existing-registered-view', 'view_key': view_key,
                      'host_recovery': recovered, 'new_host': False, 'new_store': False,
                      'new_socket': False, 'new_assignment': False}


def qualify_existing_supervision(service, proof):
    owner, state = service.server.owner, service.server.state
    project = owner.graph.current(ResourceRef.from_dict({key: proof['project_ref'][key]
                               for key in ('authority', 'kind', 'id')}))
    relation = project.payload.get('metadata', {}).get('otto_orchestrator', {})
    supervisor = owner.assignments.get(ResourceRef.from_dict(proof['supervisor_ref']))
    if (relation.get('assignment_ref') != supervisor.ref.to_dict()
            or relation.get('generation') != proof['supervisor_generation']
            or supervisor.ref.to_dict() != proof['supervisor_ref']
            or supervisor.principal != proof['supervisor_principal']
            or state['project_ref']['id'] != project.ref.id):
        raise PermissionError('original own host supervision is stale')


def protected_host_relay(host_clients, service, proof, *, previous=None):
    """Finite existing own host -> same durable owner command lane relay."""
    def relay(*, kind, view, request, token, lane, installation):
        if view is not service:
            if previous is not None:
                return previous(kind=kind, view=view, request=request, token=token,
                                lane=lane, installation=installation)
            return {'outcome': 'held', 'reason': 'no exact owner-installed relay for this view',
                    'provider_called': False, 'effects_started': False, 'retry': False}
        entry = installation.get('hosts', {}).get(kind, {})
        if (entry.get('principal') != proof['supervisor_principal']
                or Path(entry.get('lane', '')).absolute() != Path(lane).absolute()):
            raise PermissionError('relay must come from the original authenticated host lane')
        qualify_existing_supervision(service, proof)
        command = request.get('command')
        if command not in {'start-manager', 'read-help', 'respond-help'}:
            raise PermissionError('this initial registered-view relay has no such operation')
        if command == 'start-manager' and request != {'command': command, 'schedule_id': proof['schedule_id']}:
            raise PermissionError('first manager start requires the original operating-setup occurrence')
        proxy = SimpleNamespace(paths={'ipc': host_clients.shared_host.directory},
                                grant_reply=service.server.grant_reply)
        # Inherited _relay records the original host token -> manager token
        # pending receipt, recovered by _poll without resending after restart.
        return host_clients._relay(proxy, deepcopy(request), token=token, lane=Path(lane), who=kind,
                                  grant_principal=proof['supervisor_principal'])
    return relay

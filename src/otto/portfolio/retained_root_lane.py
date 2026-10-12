"""Authenticate the original issued root lane beside current private lanes."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from . import client_lanes as lanes
from .orchestrator_client import ScopedOrchestratorClient
from herzchen.contracts import ResourceRef


def _existing_private_directory(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise PermissionError('retained root lane requires an existing private directory')
    return path


def load_retained_root_lane(*, clients, controller, owner, main_state,
                            project_ids, handler, retain_stale_policy=False):
    """Load one retained locator; never issue, move or republish requests.

    The original policy is independently checked against the canonical owner.
    Two policies may use distinct lanes; one lane cannot select two clients.
    """
    controller = Path(controller).absolute()
    directory = controller / 'clients' / 'owner-root'
    path = directory / 'binding.json'
    if not path.exists() and not path.is_symlink():
        return None
    _existing_private_directory(directory)
    locator = lanes.read_private_json(path)
    lane = directory / 'lane'
    if (locator.get('schema') != 'otto.orchestrator-client-locator.v1'
            or locator.get('lane') != str(lane)):
        raise PermissionError('retained root locator selects a foreign lane')
    _existing_private_directory(lane)
    binding = locator['binding']
    expected = main_state['root_help_binding']
    actual_assignment=binding.get('assignment_ref')or{}
    expected_assignment=main_state['orchestrator_assignment_ref']
    same_assignment=all(actual_assignment.get(k)==expected_assignment.get(k) for k in ('authority','kind','id'))
    if ((actual_assignment!=expected_assignment and not (retain_stale_policy is True and same_assignment))
            or binding.get('generation') != expected['generation']
            or binding.get('conversation_ref') != expected['conversation_ref']
            or binding.get('principal') != owner.owner_actor.actor
            or binding.get('root_direction_authority') is not True
            or set(binding.get('project_ids', [])) != set(project_ids)):
        raise PermissionError('retained root binding differs from exact current responsibility')
    if any(Path(existing).resolve() == lane.resolve() for existing in clients):
        raise PermissionError('retained root lane collides with an already selected client')
    client = ScopedOrchestratorClient(owner=owner, binding=binding,
        handlers={operation: handler for operation in binding['operations']})
    if actual_assignment==expected_assignment:
        client.current()
    else:
        # A sealed Native5 packet may advance the same root revision. Retain
        # the original authenticated policy for exact request-status/error
        # publication; ScopedOrchestratorClient.call still refuses every stale
        # operation before invoking any handler. No scope or authority refresh.
        current=owner.assignments.get(ResourceRef.from_dict(expected_assignment))
        if (current.ref.to_dict()!=expected_assignment or current.generation!=binding['generation']
                or current.principal!=binding['principal'] or current.role!='orchestrator'
                or current.scope.to_dict()!=binding['portfolio_ref']
                or current.session!=binding['conversation_ref']
                or str(getattr(current.status,'value',current.status)) in {'cancelled','retired'}):
            raise PermissionError('retained stale policy has foreign current responsibility')
        expected_policy={k:v for k,v in binding.items() if k not in {'policy_ref','supervision_adopted'}}
        policy=owner.store.consumer().get_record(ResourceRef.from_dict(binding['policy_ref']))
        if policy is None or policy.payload.get('value')!=expected_policy or expected_policy.get('state')!='assigned':
            raise PermissionError('original retained policy is missing or changed')
        if any(isinstance(row.value,dict) and row.value.get('schema')=='otto.orchestrator-client-policy.v1'
               and row.value.get('state')=='revoked' and row.value.get('policy_ref')==binding['policy_ref']
               for row in owner.assignments.list_observations(current.ref,kind='report')):
            raise PermissionError('original retained root policy is revoked')
    policy = owner.store.consumer().get_record(ResourceRef.from_dict(binding['policy_ref']))
    if policy.ref.to_dict() != binding['policy_ref']:
        raise PermissionError('retained root policy revision differs from the canonical pin')
    clients[lane] = client
    return locator

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
                            project_ids, handler):
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
    if (binding.get('assignment_ref') != main_state['orchestrator_assignment_ref']
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
    client.current()
    policy = owner.store.consumer().get_record(ResourceRef.from_dict(binding['policy_ref']))
    if policy.ref.to_dict() != binding['policy_ref']:
        raise PermissionError('retained root policy revision differs from the canonical pin')
    clients[lane] = client
    return locator

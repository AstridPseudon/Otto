"""Same-root plan authoring over existing DAT/WRK atomic synchronization.

The caller is an independently issued private client policy, not owner stdin,
project authoring or a self-asserted approval. This facade creates no project,
assignment, execution task or allowance.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
from typing import Any, Mapping
from herzchen.contracts import ResourceRef, TransactionContext, canonical_json
from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from .owner_readers import json_value


def _refuse_task_authority(value: Any) -> None:
    """Direction text never authors tasks; plan tasks enter Otto only through the typed task route."""
    if isinstance(value, Mapping):
        for name, item in value.items():
            if 'task' in str(name).lower():
                raise ValueError('direction content cannot author or edit tasks; use the typed task route')
            _refuse_task_authority(item)
    elif isinstance(value, list):
        for item in value: _refuse_task_authority(item)


class RootDirectionAuthoring:
    def __init__(self, service):
        self.service, self.owner = service, service.server.owner

    def call(self, request: Mapping[str, Any], root: Any) -> Mapping[str, Any]:
        operation, key = request['operation'], request['request_key']
        payload = request.get('request') or {}
        if operation == 'direction-read':
            if payload: raise ValueError('direction-read takes no payload')
            return self.service._authenticated_owner_context(
                {'command': 'owner-context', 'operation': 'effective-context', 'request_key': key},
                self.owner.owner_actor)
        if operation == 'direction-draft':
            if set(payload) != {'content', 'expected_revision'}:
                raise ValueError('direction-draft requires content and expected_revision only')
            _refuse_task_authority(payload['content'])
            return self.service._authenticated_owner_context(
                {'command': 'owner-context', 'operation': operation, 'request_key': key, **payload},
                self.owner.owner_actor)
        if operation != 'direction-update' or set(payload) != {'content', 'expected_direction_ref', 'expected_binding_ref'}:
            raise ValueError('direction-update requires content, expected_direction_ref and expected_binding_ref only')
        # Validate the whole finite request before closing admission or mutation.
        content = payload['content']
        validate_instruction_content(content)
        _refuse_task_authority(content)
        subject = ResourceRef.from_dict(root.payload['responsibility_ref'])
        direction = self.owner.direction_surface().read(subject, assignment_ref=root.ref, generation=root.generation)
        if (direction['latest_ref'] != payload['expected_direction_ref']
                or direction['binding_ref'] != payload['expected_binding_ref']
                or direction['effective_ref'] != direction['assignment_adopted_ref']):
            raise PermissionError('current direction or scope binding changed; inspect exact readback')
        resources = deepcopy(root.payload.get('resource_adoptions', []))
        bases = [r for r in resources if r['required'] and r['resource_name'] == 'BASE']
        if len(bases) != 1: raise ValueError('exactly one current required BASE is required')
        base = bases[0]; before = json_value(self.owner.content.read(ResourceRef.from_dict(base['resource_ref'])))
        body = deepcopy(before['content']); supports = body.get('supporting_refs', [])
        if supports.count(direction['effective_ref']) != 1:
            raise PermissionError('current BASE must pin the adopted direction exactly once')
        refs = self.owner.store.consumer().find_identity_refs(kind='work.project',
            payload_matches={('metadata','otto_orchestrator','assignment_ref','id'): root.ref.id})
        projects = []
        for ref in refs:
            project = self.owner.graph.current(ref)
            relation = project.payload['metadata']['otto_orchestrator']
            if relation['assignment_ref'] != root.ref.to_dict() or relation['generation'] != root.generation:
                raise PermissionError('current project supervision join changed')
            projects.append({'project_ref': project.ref.to_dict(), 'project_version': project.version,
                             'supervision': json_value(relation)})
        if not projects: raise PermissionError('current root has no canonical supervision joins')
        defaults = {canonical_json(p['supervision']['default_ref']) for p in projects}
        if len(defaults) != 1: raise PermissionError('root project default pointers differ')
        host = self.service.host
        if host is not None:
            # Existing owner lane guarantees this is atomic with admissions.
            # Never close while a productive or uncertain native obligation exists.
            boundary = host.prepare_root_direction_adoption()
            if boundary['outcome'] != 'quiescent':
                return {**boundary, 'provider_called': False, 'canonical_effect_recorded': False}
        with self.owner.store.transaction():
            draft = self.owner.direction_surface().draft(subject, content,
                logical_request_key=key + ':draft', expected_revision=direction['latest_ref']['revision'])
            pin = draft['revision_ref']
            body['supporting_refs'] = [pin if r == direction['effective_ref'] else r for r in supports]
            old = ResourceRef.from_dict(before['identity'])
            # Deterministic exact-input revision; existing DAT replay/CAS remains authoritative.
            revision_id = 'rev-' + hashlib.sha256(canonical_json([key, body]).encode()).hexdigest()[:28]
            fresh = json_value(self.owner.content.read(ResourceRef(old.authority, old.kind, old.id)))
            if fresh.get('current_revision') != old.to_dict():
                raise PermissionError('current BASE revision changed')
            document = ContentDocument.from_dict(fresh['document'])
            revision = ContentRevision(document.ref, revision_id, body, self.owner.owner_actor,
                                       parent_revision=old.revision)
            digest = hashlib.sha256(canonical_json(body).encode()).hexdigest()
            tx = TransactionContext(self.owner.owner_actor, key + ':BASE', digest,
                expected_revision=old.revision, expected_version=fresh['version'])
            self.owner.content.execute(self.owner.content.build_append_revision(tx, document, revision))
            base.update(resource_ref=revision.ref.to_dict(), content_digest=validate_instruction_content(body))
            result = self.service._authenticated_owner_context({
                'command': 'owner-context', 'operation': 'direction-synchronize', 'request_key': key,
                'document_ref': pin, 'expected_binding_ref': direction['binding_ref'],
                'handle': {'assignment_ref': root.ref.to_dict(), 'generation': root.generation,
                           'resources': resources, 'expected_default_ref': projects[0]['supervision']['default_ref'],
                           'projects': projects}}, self.owner.owner_actor)
        return {**result, 'BASE_ref': revision.ref.to_dict(), 'draft_ref': pin,
                'project_join_count': len(projects), 'tasks_created': False,
                'allowances_changed': False, 'project_activation': False,
                'dispatch': False, 'launch': False,
                'client_binding_refresh_required': True}


def install_owner_root_client(*, service, directory, conversation_ref, request_key,
                              project_ids=(), project_handler=None):
    """Normal trusted host deployment of one same-root client lane.

    Call while composing/requalifying the owner, before native admission. The
    directory and exact chat come from operator deployment, never client JSON.
    No FIFO is relocated and no denied endpoint is forwarded. File permissions
    remain those of the normal deployment environment.
    """
    from pathlib import Path
    from . import client_lanes as lanes
    from .orchestrator_client import (OrchestratorAdmissions, ScopedOrchestratorClient,
        ROOT_DIRECTION_OPERATIONS, ROOT_PROJECT_OPERATIONS)
    if project_ids and not callable(project_handler):
        raise ValueError('finite owner-root project scope requires the existing scoped project handler')
    root = service.server.owner.assignments.get(service.server.state['orchestrator_assignment_ref'])
    admissions = OrchestratorAdmissions(service.server.owner,
        main_assignment_ref=root.ref.to_dict(), generation=root.generation)
    binding = admissions.admit_current_root(actor=service.server.owner.owner_actor,
        conversation_ref=conversation_ref,
        operations=sorted(ROOT_DIRECTION_OPERATIONS | {'whoami', 'status'} |
                          (ROOT_PROJECT_OPERATIONS if project_ids else frozenset())),
        project_ids=list(project_ids),
        request_key=request_key + ':' + root.ref.revision)
    directory = lanes.private_dir(Path(directory))
    lane = lanes.private_dir(directory / 'lane')
    locator = {'schema': 'otto.orchestrator-client-locator.v1',
               'binding': binding, 'lane': str(lane)}
    lanes.atomic_json(directory / 'binding.json', locator)
    def handle(request, current):
        if request['operation'] in {'whoami', 'status'}:
            if request.get('request') or request.get('project_id') is not None:
                raise ValueError('owner-root identity read takes no payload or project selector')
            return {'outcome': 'read', 'state': 'assigned', 'assignment_ref': current.ref.to_dict(),
                    'generation': current.generation, 'principal': current.principal,
                    'portfolio_ref': current.scope.to_dict(), 'canonical_conversation': json_value(current.session),
                    'operations': binding['operations'], 'read_only': True, 'provider_called': False}
        if request['operation'] in ROOT_PROJECT_OPERATIONS:
            return project_handler(request, current)
        return service.root_direction_client(request, current)
    return locator, ScopedOrchestratorClient(owner=service.server.owner, binding=binding,
        handlers={op: handle for op in binding['operations']})

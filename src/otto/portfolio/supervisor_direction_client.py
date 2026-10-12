"""Explicitly issued project-supervisor directions; no owner-root substitution.

The scoped client authenticates the issued policy before this host handler.
Only an already-bound manager direction can be adopted here. Worker resources,
portfolio defaults and supervision joins are never refreshed by this facade.
"""
from copy import deepcopy
import hashlib
from typing import Mapping
from herzchen.contracts import ResourceRef, TransactionContext, canonical_json
from herzchen.content import ContentDocument, ContentRevision
from herzchen.content.instructions import validate_instruction_content
from .owner_readers import json_value
from .manager_guide import resolve_required_instruction_adoption


def current_purpose_content(content, *, direction_ref, instructions, inherited_ref):
    """Render a prospective purpose while retaining immutable context history.

    Authority, workspace and selected-source fields remain unchanged. Historical
    stage prose is linked by its exact document pin, never parsed into new work.
    """
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError('current supervisor purpose requires instruction text')
    pin = ResourceRef.from_dict(direction_ref)
    prior = ResourceRef.from_dict(inherited_ref)
    if not pin.revision or not prior.revision or pin.authority != prior.authority:
        raise ValueError('current purpose requires exact owner-local context pins')
    body = deepcopy(content)
    summary = ('Current action from the exact adopted supervisor direction:\n' + instructions
        + '\nUse exact current task lifecycle and completion records to select actionable work. '
          'An inherited execution task is a transport and authority anchor; completed tasks are historical, '
          'not pending work. Preserve their accepted judgments and use ordinary final handoff when eligible. '
          'Prior stage instructions are retained non-actionable history at the linked context revision. '
          'Existing authority, workspace, model and operation limits remain in force.')
    body['current_purpose'] = {'schema': 'otto.current-supervisor-purpose.v1',
        'direction_ref': pin.to_dict(), 'instructions': instructions,
        'instructions_sha256': hashlib.sha256(instructions.encode()).hexdigest(),
        'historical_context_ref': prior.to_dict(), 'historical_context_actionable': False}
    if body.get('schema') == 'herzchen.instructions.v1':
        body['instructions'] = summary
        body['bundle_digest'] = hashlib.sha256(summary.encode()).hexdigest()
    else:
        brief = body.get('brief')
        if not isinstance(brief, Mapping):
            raise ValueError('current purpose mandate requires its existing brief')
        body['brief'] = {**brief, 'mandate': summary,
            'priorities': [{'id': 'current-supervisor-purpose', 'text': instructions, 'status': 'current'}],
            'continuation': {'source': 'exact adopted supervisor direction',
                'direction_ref': pin.to_dict(),
                'next_action': 'Read exact current task completion and lifecycle; follow this purpose only for unfinished work or final handoff.'}}
    return body


OPERATIONS = frozenset({'supervisor-direction-read', 'supervisor-direction-draft',
                        'supervisor-direction-adopt-and-continue'})


def scoped_supervisor_handler(*, services, fallback):
    """Trusted fixed-view composition; issuing the policy remains owner-only.

    Wrap the existing scoped-client handler during normal closed deployment.
    This does not admit a client, expand its policy or create another owner.
    """
    def handle(request, root):
        if request.get('operation') not in OPERATIONS:
            return fallback(request, root)
        matches = [s for s in services if s.server.state['project_ref']['id'] == request.get('project_id')]
        if len(matches) != 1: raise PermissionError('directive project has no unique installed fixed view')
        return SupervisorDirectionAuthoring(matches[0]).call(request, root)
    return handle


class SupervisorDirectionAuthoring:
    def __init__(self, service):
        self.service, self.owner = service, service.server.owner

    @staticmethod
    def _bootstrap_projection(state, manager, due, base_ref):
        # The fixed owner startup checks these exact current resource locators.
        # The historical native anchor is retained in Due/native_binding and
        # requested_continuation; it must not remain the bootstrap execution.
        state.update(assignment_ref=manager.ref.to_dict(), schedule_id=due.schedule_id,
                     guide_ref=dict(base_ref), mandate_ref=dict(due.target['mandate_ref']))

    def call(self, request, root):
        service, owner = self.service, self.owner
        state = service.server.state
        project = owner.graph.get(ResourceRef.from_dict(state['project_ref']))
        relation = project.payload.get('metadata', {}).get('otto_orchestrator', {})
        current_root = owner.assignments.get(root.ref)
        if (current_root.ref != root.ref or current_root.generation != root.generation
                or root.role != 'orchestrator' or request.get('project_id') != project.id
                or relation.get('assignment_ref') != root.ref.to_dict()
                or relation.get('generation') != root.generation):
            raise PermissionError('directive requires exact current issued project supervision')
        manager = owner.assignments.get(ResourceRef.from_dict(state['assignment_ref']))
        payload, key, operation = request.get('request') or {}, request['request_key'], request['operation']
        # Canonical commit may precede local state publication. Inspect the exact
        # application before enforcing that cached manager revision on replay.
        observation_id = 'report-' + hashlib.sha256((root.ref.id + ':' + key + ':application').encode()).hexdigest()[:28]
        retained = owner.store.consumer().get_record(ResourceRef(root.ref.authority, 'wrk.report', observation_id))
        if retained is not None:
            value = json_value(retained.payload['value'])
            digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
            if (operation != 'supervisor-direction-adopt-and-continue'
                    or value.get('request_digest') != digest
                    or value.get('supervisor_assignment_ref') != root.ref.to_dict()
                    or value.get('manager_assignment_ref') != manager.ref.to_dict()
                    or value.get('manager_generation') != manager.generation):
                raise PermissionError('directive key reused with changed input or current identity')
            app = service._execution(principal=manager.principal, model=state['requested_model'],
                reasoning=state['requested_reasoning'], evidence_id='supervisor-directive-replay')
            prepared = app.continue_manager_from_directive(manager_schedule_id=value['anchor_schedule_id'],
                report_ref=retained.ref.to_dict(), supervisor_ref=root.ref.to_dict(), execute=False)
            # Never move a newer head backward. Only restore the exact old
            # anchor -> committed callback projection after publication loss.
            if service._current_manager_schedule() == value['anchor_schedule_id']:
                from .manager_journey_service import advance_manager_head
                staged = deepcopy(state)
                due = app._read(value['continuation_schedule_id'])
                if not advance_manager_head(staged, expected=value['anchor_schedule_id'], due=due,
                        settled_anchor=value['anchor_schedule_id']):
                    raise PermissionError('manager head changed during replay projection')
                self._bootstrap_projection(staged, manager, due, value['BASE_ref'])
                state.update(staged)
                service.server._save_state()
            return {**value, 'outcome': 'replayed', 'report_ref': retained.ref.to_dict(),
                    'continuation': prepared, 'provider_called': False}
        if (manager.ref.to_dict() != state['assignment_ref'] or manager.generation != state['manager_generation']
                or manager.principal != state['manager'] or manager.role != 'manager'
                or (manager.scope.authority, manager.scope.kind, manager.scope.id) !=
                   (project.ref.authority, project.ref.kind, project.ref.id)):
            raise PermissionError('current project manager binding differs')
        subject = ResourceRef.from_dict(manager.payload['responsibility_ref'])
        surface = owner.direction_surface()
        direction = surface.read(subject, assignment_ref=manager.ref, generation=manager.generation)
        common = {'schema': 'otto.scoped-supervisor-direction.v1', 'project_ref': project.ref.to_dict(),
                  'direction_surface': 'manager-responsibility',
                  'supervisor_instruction_adoption': 'not-read-or-changed-by-this-operation',
                  'supervisor_assignment_ref': root.ref.to_dict(), 'supervisor_generation': root.generation,
                  'manager_assignment_ref': manager.ref.to_dict(), 'manager_generation': manager.generation,
                  'subject_ref': subject.to_dict(), 'provider_called': False,
                  'worker_resources_changed': False, 'budgets_changed': False,
                  'default_or_supervision_changed': False, 'consumption': 'unverified'}
        if operation == 'supervisor-direction-read':
            if payload: raise ValueError('supervisor-direction-read takes no payload')
            return {**common, 'outcome': 'read', 'direction': direction,
                    'manager_schedule_id': service._current_manager_schedule(), 'read_only': True}
        if direction.get('state') != 'effective':
            return {**common, 'outcome': 'held', 'canonical_effect_recorded': False,
                    'reason': 'first binding or incomplete manager direction requires affected-role qualification',
                    'direction': direction, 'retry': False}
        if operation == 'supervisor-direction-draft':
            if set(payload) != {'content', 'expected_revision'}:
                raise ValueError('supervisor-direction-draft needs content and expected_revision only')
            validate_instruction_content(payload['content'])
            if len(canonical_json(payload).encode()) > 65536: raise ValueError('directive payload exceeds 65536 bytes')
            return {**common, 'outcome': 'drafted', 'draft': surface.draft(subject, payload['content'],
                    expected_revision=payload['expected_revision'], logical_request_key=key),
                    'adopted': False, 'continuation': None, 'read_only': False}
        fields = {'document_ref', 'expected_binding_ref', 'expected_direction_ref',
                  'expected_manager_ref', 'expected_manager_generation', 'expected_schedule_id'}
        if operation != 'supervisor-direction-adopt-and-continue' or set(payload) != fields:
            raise ValueError('adopt-and-continue needs document_ref, expected_binding_ref, expected_direction_ref, expected_manager_ref, expected_manager_generation, expected_schedule_id')
        if len(canonical_json(payload).encode()) > 4096: raise ValueError('directive pins exceed 4096 bytes')
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        if (payload['expected_manager_ref'] != manager.ref.to_dict()
                or payload['expected_manager_generation'] != manager.generation
                or payload['expected_direction_ref'] != direction['latest_ref']
                or payload['expected_binding_ref'] != direction['binding_ref']
                or payload['expected_schedule_id'] != service._current_manager_schedule()):
            raise PermissionError('manager, direction, binding or current head changed; read exact current pins')
        app = service._execution(principal=manager.principal, model=state['requested_model'],
            reasoning=state['requested_reasoning'], evidence_id='supervisor-directive')
        prior = app._read(payload['expected_schedule_id'])
        app._manager_adoption_anchor(prior)
        _, _, hold = app._manager_anchor(prior, manager, schedule='supervisor-directive-pending', purpose='supervisor directive')
        if hold is not None: return {**common, **hold, 'canonical_effect_recorded': False}
        resources = deepcopy(manager.payload.get('resource_adoptions', []))
        try:
            base, before, _ = resolve_required_instruction_adoption(
                resources, state.get('guide_ref'), owner.content)
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            raise PermissionError('current manager guide adoption is not exact and valid') from exc
        body = deepcopy(before['content'])
        old = direction['assignment_adopted_ref']
        if body.get('supporting_refs', []).count(old) != 1:
            raise PermissionError('manager BASE must pin its controlling direction exactly once')
        pin = ResourceRef.from_dict(payload['document_ref'])
        if (pin.authority, pin.kind, pin.id) != tuple(direction['latest_ref'][k] for k in ('authority','kind','id')) or not pin.revision:
            raise PermissionError('directive draft belongs to another bound document')
        direction_content = json_value(owner.content.read(pin))['content']
        validate_instruction_content(direction_content)
        body = current_purpose_content(body, direction_ref=pin.to_dict(),
            instructions=direction_content['instructions'], inherited_ref=base['resource_ref'])
        body['supporting_refs'] = [pin.to_dict() if r == old else r for r in body['supporting_refs']]
        # All canonical effects, including Due preparation, share one owner transaction.
        staged_state = deepcopy(state)
        with owner.store.transaction():
            base_ref = ResourceRef.from_dict(base['resource_ref'])
            fresh = json_value(owner.content.read(ResourceRef(base_ref.authority, base_ref.kind, base_ref.id)))
            if fresh['current_revision'] != base_ref.to_dict(): raise PermissionError('manager BASE head changed')
            document = ContentDocument.from_dict(fresh['document'])
            revision = ContentRevision(document.ref, 'rev-' + hashlib.sha256(canonical_json([key,body]).encode()).hexdigest()[:28],
                body, owner.owner_actor, parent_revision=base_ref.revision)
            tx = TransactionContext(owner.owner_actor, key + ':BASE', hashlib.sha256(canonical_json(body).encode()).hexdigest(),
                expected_revision=base_ref.revision, expected_version=fresh['version'])
            owner.content.execute(owner.content.build_append_revision(tx, document, revision))
            base.update(resource_ref=revision.ref.to_dict(), content_digest=validate_instruction_content(body))
            adopted = surface.update(subject, pin, logical_request_key=key + ':adopt',
                expected_binding_ref=payload['expected_binding_ref'], assignment_ref=manager.ref,
                expected_generation=manager.generation, assignment_resources=resources,
                assignment_actor=owner.binding.authenticated_actor(manager.payload.get('manager') or manager.principal))
            if adopted['partial']: raise PermissionError('manager adoption is incomplete: ' + str(adopted['assignment_refresh']))
            current = owner.assignments.get(adopted['assignment_refresh']['assignment_ref'])
            value = {**common, 'schema': 'otto.supervisor-directive-application.v1', 'outcome': 'adopted',
                'request_digest': digest, 'before_manager_ref': manager.ref.to_dict(),
                'manager_assignment_ref': current.ref.to_dict(), 'direction_ref': pin.to_dict(),
                'BASE_ref': revision.ref.to_dict(), 'adoption_key': key + ':adopt:assignment',
                'anchor_schedule_id': prior.schedule_id, 'anchor_sha256': app.directive_anchor_digest(prior),
                'continuation_schedule_id': 'manager-directive-' + hashlib.sha256(canonical_json([root.ref.to_dict(),key]).encode()).hexdigest()[:28]}
            report = owner.assignments.append_report(root.ref, value, expected_generation=root.generation,
                logical_request_key=key + ':application', actor=owner.binding.authenticated_actor(root.principal))
            prepared = app.continue_manager_from_directive(manager_schedule_id=prior.schedule_id,
                report_ref=report.ref.to_dict(), supervisor_ref=root.ref.to_dict(), execute=False)
            if prepared.get('outcome') not in {'committed','prepared','replayed'}: raise PermissionError('directive continuation did not prepare')
            from .manager_journey_service import advance_manager_head
            due = app._read(prepared['schedule_id'])
            if service._current_manager_schedule() != prior.schedule_id or not advance_manager_head(staged_state, expected=prior.schedule_id, due=due, settled_anchor=prior.schedule_id):
                raise PermissionError('manager head advanced during directive adoption')
            self._bootstrap_projection(staged_state, current, due, revision.ref.to_dict())
        state.update(staged_state)
        service.server._save_state()
        return {**common, **value, 'report_ref': report.ref.to_dict(), 'continuation': prepared,
                'delivery': 'prepared-not-started', 'read_only': False}

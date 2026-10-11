"""Owner-issued external chat clients over the existing owner and assignments.

The private lane is a host intent binding, not protection against a hostile
process of the same OS account. Clients never open Store or supply an actor.
Enrollment requests grant nothing; current owner admission supplies all scope.
"""
from __future__ import annotations
import hashlib
from typing import Any, Mapping
from herzchen.contracts import ResourceRef, canonical_json
from .owner_readers import json_value
from pathlib import Path
import argparse
import json
from . import client_lanes as lanes

OPERATIONS = frozenset({'status', 'whoami', 'effective-context', 'portfolio',
    'read-manager', 'read-help', 'respond-help', 'delivery-ack',
    'project-authoring', 'manager-start'})

class ClientAccessRevoked(PermissionError):
    pass

def _key(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError('an exact stable request key is required')
    return value

class OrchestratorAdmissions:
    """Trusted current-owner facade; never exposed as a self-admission client."""
    def __init__(self, owner, *, main_assignment_ref, generation):
        self.owner, self.main, self.generation = owner, main_assignment_ref, generation

    def _owner(self, actor):
        if actor != self.owner.owner_actor:
            raise PermissionError('orchestrator admission requires current authenticated owner authority')
        main = self.owner.assignments.get(self.main)
        if main.ref.to_dict() != self.main or main.generation != self.generation or main.role != 'orchestrator':
            raise PermissionError('admitting root binding is stale')
        return main

    def request(self, *, conversation_ref, requested_project_ids, request_key):
        """A durable request only; neither conversation nor requested scope is authority."""
        _key(request_key)
        if (not isinstance(conversation_ref, Mapping) or set(conversation_ref) != {'host', 'native_id'}
                or any(not isinstance(v, str) or not v.strip() for v in conversation_ref.values())
                or not isinstance(requested_project_ids, list) or len(requested_project_ids) > 16
                or any(not isinstance(v, str) or not v.strip() for v in requested_project_ids)):
            raise ValueError('bounded conversation and requested project IDs required')
        value = {'schema': 'otto.orchestrator-enrollment-request.v1', 'state': 'requested',
                 'conversation_ref': dict(conversation_ref), 'requested_project_ids': requested_project_ids,
                 'request_key': request_key, 'authority_granted': False}
        report = self.owner.assignments.append_report(ResourceRef.from_dict(self.main), value,
            expected_generation=self.generation, logical_request_key='enrollment-request:' + request_key,
            actor=self.owner.owner_actor)
        return {'state': 'requested', 'request_ref': json_value(report.ref), 'authority_granted': False}

    def deny(self, *, actor, request_ref, reason, request_key):
        main = self._owner(actor); _key(request_key)
        record = self.owner.store.consumer().get_record(ResourceRef.from_dict(request_ref))
        if record is None or record.payload.get('assignment', {}).get('id') != main.ref.id or record.payload.get('value', {}).get('schema') != 'otto.orchestrator-enrollment-request.v1':
            raise PermissionError('denial requires the exact pending enrollment request')
        if not isinstance(reason, str) or not reason.strip(): raise ValueError('denial reason required')
        report = self.owner.assignments.append_report(main.ref, {'schema': 'otto.orchestrator-enrollment-disposition.v1', 'state': 'denied', 'request_ref': dict(request_ref), 'reason': reason, 'authority_granted': False}, expected_generation=main.generation, logical_request_key='enrollment-deny:' + request_key, actor=actor)
        return {'state': 'denied', 'disposition_ref': report.ref.to_dict(), 'authority_granted': False}

    def admit(self, *, actor, request_ref, project_ids, operations, request_key):
        main = self._owner(actor); _key(request_key)
        request = self.owner.store.consumer().get_record(ResourceRef.from_dict(request_ref))
        value = request.payload['value'] if request is not None else {}
        parent = request.payload.get('assignment', {}) if request is not None else {}
        if (value.get('schema') != 'otto.orchestrator-enrollment-request.v1' or value.get('authority_granted') is not False
                or parent.get('id') != main.ref.id or request.ref.kind != 'wrk.report'):
            raise PermissionError('admission requires the retained enrollment request')
        if (not isinstance(project_ids, list) or not project_ids or len(project_ids) > 16
                or len(set(project_ids)) != len(project_ids)
                or not set(project_ids).issubset(value['requested_project_ids'])
                or not isinstance(operations, list) or not operations or not set(operations).issubset(OPERATIONS)):
            raise PermissionError('owner must issue finite requested project and operation scope')
        if any(isinstance(r.value, Mapping) and r.value.get('schema') == 'otto.orchestrator-enrollment-disposition.v1' and r.value.get('state') == 'denied' and r.value.get('request_ref') == request_ref for r in self.owner.assignments.list_observations(main.ref, kind='report')):
            raise PermissionError('enrollment request was canonically denied')
        conversation = value['conversation_ref']
        principal = 'otto-orchestrator-' + hashlib.sha256(canonical_json(conversation).encode()).hexdigest()[:20]
        root = self.owner.assignments.assign(main.scope, role='orchestrator', principal=principal,
            session=conversation, logical_request_key='orchestrator-admit:' + principal)
        reports = self.owner.assignments.list_observations(root.ref, kind='report')
        revoked = {canonical_json(r.value['policy_ref']) for r in reports if isinstance(r.value, Mapping)
                   and r.value.get('schema') == 'otto.orchestrator-client-policy.v1'
                   and r.value.get('state') == 'revoked' and isinstance(r.value.get('policy_ref'), Mapping)}
        for prior in reports:
            p = prior.value
            if (isinstance(p, Mapping) and p.get('schema') == 'otto.orchestrator-client-policy.v1'
                    and p.get('state') == 'assigned' and canonical_json(prior.ref.to_dict()) not in revoked):
                if p['project_ids'] != project_ids or p['operations'] != sorted(set(operations)) or p['assignment_ref'] != root.ref.to_dict():
                    raise PermissionError('existing client must be explicitly revoked before scope or binding reissue')
                return {**json_value(p), 'policy_ref': prior.ref.to_dict(), 'supervision_adopted': False}
        policy = {'schema': 'otto.orchestrator-client-policy.v1', 'state': 'assigned',
                  'request_ref': dict(request_ref), 'assignment_ref': root.ref.to_dict(),
                  'generation': root.generation, 'principal': principal, 'portfolio_ref': json_value(main.scope),
                  'conversation_ref': conversation, 'project_ids': list(project_ids),
                  'operations': sorted(set(operations)), 'request_namespace': root.ref.id}
        report = self.owner.assignments.append_report(root.ref, policy, expected_generation=root.generation,
            logical_request_key='orchestrator-policy:' + request_key, actor=actor)
        return {**policy, 'policy_ref': json_value(report.ref), 'supervision_adopted': False}

    def revoke(self, *, actor, binding, request_key):
        self._owner(actor); _key(request_key)
        root = self.owner.assignments.get(ResourceRef.from_dict(binding['assignment_ref']))
        if root.ref.to_dict() != binding['assignment_ref'] or root.generation != binding['generation']:
            raise PermissionError('revocation requires the exact current client generation')
        report = self.owner.assignments.append_report(root.ref, {**binding, 'state': 'revoked'},
            expected_generation=root.generation, logical_request_key='orchestrator-revoke:' + request_key,
            actor=actor)
        return {'state': 'revoked', 'policy_ref': json_value(report.ref), 'assignment_retired': False}

class ScopedOrchestratorClient:
    """A fixed owner-issued client binding, revalidated on every serialized call."""
    def __init__(self, *, owner, binding, handlers):
        self.owner, self.binding, self.handlers = owner, dict(binding), dict(handlers)

    def current(self):
        binding = self.binding
        root = self.owner.assignments.get(ResourceRef.from_dict(binding['assignment_ref']))
        if (root.ref.to_dict() != binding['assignment_ref'] or root.generation != binding['generation']
                or root.principal != binding['principal'] or root.role != 'orchestrator'
                or json_value(root.scope) != binding['portfolio_ref']
                or json_value(root.session) != binding['conversation_ref']
                or str(getattr(root.status, 'value', root.status)) in {'cancelled', 'retired'}):
            raise PermissionError('issued orchestrator responsibility is stale or foreign')
        policy = self.owner.store.consumer().get_record(ResourceRef.from_dict(binding['policy_ref']))
        expected = {k:v for k,v in binding.items() if k not in {'policy_ref', 'supervision_adopted'}}
        revoked = any(isinstance(x.value, Mapping) and x.value.get('schema') == 'otto.orchestrator-client-policy.v1'
                      and x.value.get('state') == 'revoked' and x.value.get('policy_ref') == binding['policy_ref']
                      for x in self.owner.assignments.list_observations(root.ref, kind='report'))
        if revoked:
            raise ClientAccessRevoked('orchestrator client access is canonically revoked')
        if policy is None or policy.payload.get('value') != expected or expected.get('state') != 'assigned':
            raise PermissionError('orchestrator client access is revoked or its issued policy changed')
        return root

    def call(self, request):
        if not isinstance(request, Mapping) or set(request) - {'operation', 'project_id', 'request_key', 'request'}:
            raise PermissionError('client cannot select principal, generation or privilege')
        operation = request.get('operation')
        try:
            root = self.current()
        except ClientAccessRevoked:
            if operation == 'status':
                return {'state': 'revoked', 'supervision_adopted': False, 'authority_granted': False}
            raise
        if operation not in self.binding['operations'] or operation not in self.handlers:
            raise PermissionError('operation is outside the issued client scope')
        project_id = request.get('project_id')
        if project_id is not None and project_id not in self.binding['project_ids']:
            raise PermissionError('project is outside the issued orchestrator scope')
        if operation not in {'status', 'whoami', 'portfolio'}:
            if project_id not in self.binding['project_ids']:
                raise PermissionError('project is outside the issued orchestrator scope')
            record = self.owner.graph.get(ResourceRef(root.ref.authority, 'work.project', project_id))
            relation = record.payload.get('metadata', {}).get('otto_orchestrator', {})
            if relation.get('assignment_ref') != root.ref.to_dict() or relation.get('generation') != root.generation:
                raise PermissionError('project supervision is not adopted for this client')
        key = _key(request.get('request_key'))
        scoped = {**request, 'request_key': self.binding['request_namespace'] + ':' + key}
        # Handler and actor come only from the owner composition, never JSON.
        return self.handlers[operation](scoped, root)

def submit_exact(lane, request, *, namespace, request_key):
    """Stable per-principal handle; changed input cannot reuse the same key."""
    token = hashlib.sha256(canonical_json([namespace, _key(request_key)]).encode()).hexdigest()[:32]
    path = Path(lane) / ('request-' + token + '.json')
    prior = lanes.read_private_json(path)
    if prior is None:
        lanes.submit(Path(lane), request, token=token)
    elif prior != request:
        raise PermissionError('client request key was reused with changed input')
    return token

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', default=str(Path.home()/'.otto/orchestrator-connection.json'))
    parser.add_argument('--binding')
    parser.add_argument('--timeout-seconds', type=float, default=2)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('discover')
    enroll = sub.add_parser('request-enrollment')
    enroll.add_argument('--owner-inbox'); enroll.add_argument('--request-key', required=True)
    enroll.add_argument('--conversation-ref', required=True)
    enroll.add_argument('--project-id', action='append', required=True)
    for operation in sorted(OPERATIONS):
        command = sub.add_parser(operation)
        command.add_argument('--request-key', required=operation in {'respond-help', 'delivery-ack', 'project-authoring', 'manager-start'})
        command.add_argument('--project-id')
        if operation in {'respond-help', 'delivery-ack', 'project-authoring', 'manager-start'}:
            command.add_argument('--request', required=True)
    command = sub.add_parser('request-status'); command.add_argument('--request-id', required=True)
    args = parser.parse_args(argv)
    connection = lanes.read_private_json(Path(args.connection))
    if connection is None:
        raise FileNotFoundError('No installed Otto connection locator; request installation from the accountable owner')
    if args.operation == 'discover':
        result = {**connection, 'state': 'unregistered' if not args.binding else 'binding-issued-not-yet-verified'}
    elif args.operation == 'status' and not args.binding:
        result = {'state': 'unregistered', 'supervision_adopted': False, 'connection': connection, 'authority_granted': False}
    else:
        if args.operation == 'request-status' and not args.binding:
            lane = connection['owner_inbox']
            token = args.request_id
            if not lanes.valid_token(token): raise ValueError('exact retained request ID required')
        elif args.operation == 'request-enrollment':
            lane = args.owner_inbox or connection['owner_inbox']
            request = {'operation': args.operation, 'conversation_ref': json.loads(args.conversation_ref),
                       'requested_project_ids': args.project_id, 'request_key': args.request_key}
            token = submit_exact(lane, request, namespace='enrollment-request', request_key=args.request_key)
        else:
            if not args.binding:
                raise PermissionError('Use request-enrollment; no orchestrator binding has been issued')
            locator = lanes.read_private_json(Path(args.binding))
            if locator is None: raise FileNotFoundError('Issued binding locator is missing')
            lane = locator['lane']
            if args.operation == 'request-status':
                token = args.request_id
                if not lanes.valid_token(token): raise ValueError('exact retained request ID required')
            else:
                request_key = args.request_key or ('read-' + lanes.new_token())
                request = {'operation': args.operation, 'request_key': request_key}
                if args.project_id is not None: request['project_id'] = args.project_id
                if hasattr(args, 'request'): request['request'] = json.loads(args.request)
                token = submit_exact(lane, request, namespace=locator['binding']['request_namespace'], request_key=request_key)
        result = lanes.wait(Path(lane), token, timeout_seconds=min(max(args.timeout_seconds,0),60))
    print(json.dumps(result, sort_keys=True, default=str))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

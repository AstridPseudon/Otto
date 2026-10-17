"""Root-owned installed composition for same-assignment native replacement.

Session acquisition and context delivery are trusted host callbacks, never
request JSON. Existing owner reports retain acquisition custody; the existing
assignment CAS and role runtime own binding, generation, readiness and work.
"""
from __future__ import annotations
import hashlib
import json
import secrets
from typing import Any, Callable, Mapping
from herzchen.contracts import ResourceRef
from .manager_continuity import ManagerContinuity
from .owner_readers import json_value


_NEXT_ACTION = (
    'Ask the owner to inspect the original retained intent and reconcile prior manager/native custody; '
    'only submit a new accepted schedule after resolution. '
    'Do not retry acquisition for this assignment generation and native session.'
)


def _held(reason: str, **fields: Any) -> dict[str, Any]:
    return {'outcome': 'held', 'reason': reason, 'retry': False,
            'next_action': _NEXT_ACTION, **fields}


class OwnerManagerReplacement:
    def __init__(self, *, application: Any, report_reader: Callable[..., Any], acquire_session: Callable[..., Mapping[str, Any]],
                 context_builder: Callable[..., Mapping[str, Any]],
                 readiness: Callable[..., Mapping[str, Any]],
                 operational_help: Callable[..., Mapping[str, Any]] | None = None,
                 restart: Callable[..., Mapping[str, Any]] | None = None) -> None:
        self.app, self.report_reader = application, report_reader
        self.acquire_session, self.context_builder = acquire_session, context_builder
        self.readiness, self.operational_help, self.restart = readiness, operational_help, restart
        if not all(callable(cb) for cb in (report_reader, acquire_session, context_builder, readiness)):
            raise TypeError('replacement requires trusted acquisition/context/readiness ports')

    def _report(self, assignment: Any, key: str, value: Mapping[str, Any]) -> Any:
        return self.app.assignments.append_report(assignment.ref, dict(value),
            expected_generation=assignment.generation, logical_request_key=key,
            actor=self.app.binding.authenticated_actor(self.app.manager_actor))

    def replace(self, *, schedule_id: str, request_key: str) -> Mapping[str, Any]:
        """One root intent; a failed acquisition is held, never automatically retried."""
        if not isinstance(request_key, str) or not request_key.strip():
            raise ValueError('replacement request key is required')
        prior = self.app._read(schedule_id)
        assignment = self.app.assignments.get(ResourceRef.from_dict(prior.assignment_ref))
        target = prior.target
        native = target.get('native_id') or (prior.last_result or {}).get('physical_session_id')
        if (prior.role != 'manager' or assignment.role != 'manager'
                or assignment.principal != self.app.manager_actor):
            raise PermissionError('replacement requires the exact accountable manager')
        records = {}
        # The first admitted acquisition owns this assignment generation and
        # native session. Other completed DueRecords and request keys cannot
        # bypass an unresolved acquisition by choosing another schedule.
        intent_key = 'manager-native-replacement:' + hashlib.sha256(json.dumps(
            [prior.generation, native], separators=(',', ':'), sort_keys=True).encode()).hexdigest()
        for stage, suffix in (("intent", "intent"), ("acquired", "acquired"),
                              ("acquisition-unknown", "acquisition-unknown")):
            report_key = intent_key if stage == 'intent' else request_key + ':' + suffix
            identifier = "report-" + hashlib.sha256((assignment.id+":"+report_key).encode()).hexdigest()[:28]
            record = self.report_reader(
                ResourceRef(assignment.ref.authority, "wrk.report", identifier))
            if record is None:
                continue
            payload = record.payload
            value = payload.get("value")
            if (payload.get("assignment") != prior.assignment_ref or payload.get("generation") != prior.generation
                    or not isinstance(value, Mapping) or value.get("schema") != "otto.manager-native-replacement.v1"
                    or (stage != 'intent' and value.get("request_key") != request_key)
                    or value.get("stage") != stage):
                raise PermissionError("retained native replacement report attribution differs")
            records[stage] = value
        original = records.get('intent')
        pin = {'schedule_id': schedule_id, 'assignment_ref': prior.assignment_ref,
               'generation': prior.generation, 'native_id': native,
               'project_ref': target['project_ref'], 'task_ref': target['task_ref']}
        if original is not None and original.get('pin') != pin:
            raise PermissionError('retained replacement intent differs')
        if original is not None and original.get('request_key') != request_key:
            return _held('prior replacement intent owns this native acquisition', provider_called=False)
        retained = records.get('acquired')
        if assignment.generation == prior.generation:
            if assignment.ref.to_dict() != prior.assignment_ref:
                raise PermissionError('replacement assignment revision changed')
            self.app._verify_native_binding(assignment, native, schedule_id)
            if (prior.stop_state != 'completed' or prior.completion_state != 'succeeded'
                    or prior.in_flight_request is not None
                    or ((prior.host_evidence or {}).get('gateway_attempt') or {}).get('result', {}).get('outcome') != 'succeeded'):
                return _held('prior manager custody is not terminal succeeded', provider_called=False)
            if original is not None and retained is None:
                return _held('session acquisition was admitted but has no verified retained result',
                             provider_called=False)
            if original is None:
                claim = secrets.token_hex(16)
                self._report(assignment, intent_key, {'schema':'otto.manager-native-replacement.v1',
                    'request_key':request_key,'stage':'intent','pin':pin,'claim':claim})
                intent_id = "report-" + hashlib.sha256((assignment.id+":"+intent_key).encode()).hexdigest()[:28]
                admitted = self.report_reader(ResourceRef(assignment.ref.authority, "wrk.report", intent_id))
                if admitted is None:
                    return _held('retained native acquisition intent is unavailable', provider_called=False)
                admitted_value = admitted.payload.get('value')
                if (not isinstance(admitted_value, Mapping)
                        or admitted.payload.get('assignment') != prior.assignment_ref
                        or admitted.payload.get('generation') != prior.generation
                        or admitted_value.get('schema') != 'otto.manager-native-replacement.v1'
                        or admitted_value.get('stage') != 'intent'
                        or admitted_value.get('pin') != pin):
                    raise PermissionError('retained replacement intent cannot be verified')
                if admitted_value.get('request_key') != request_key:
                    return _held('prior replacement intent owns this native acquisition', provider_called=False)
                if admitted_value.get('claim') != claim:
                    return _held('another caller admitted this native acquisition', provider_called=False)
                result = dict(self.acquire_session(prior.to_dict()))
                # The trusted host verifies the actual inert native receipt;
                # the JSON caller cannot supply a session or verification bit.
                if (result.get('outcome') != 'succeeded' or result.get('terminal_verified') is not True
                        or not isinstance(result.get('physical_session_id'), str)
                        or not result['physical_session_id'].strip() or result['physical_session_id'] == native):
                    self._report(assignment, request_key+':acquisition-unknown', {
                        'schema':'otto.manager-native-replacement.v1','request_key':request_key,
                        'stage':'acquisition-unknown','pin':pin,'result':result})
                    return _held('new native acquisition is unresolved')
                retained = {'schema':'otto.manager-native-replacement.v1','request_key':request_key,
                    'stage':'acquired','pin':pin,'result':json_value(result)}
                self._report(assignment,request_key+':acquired',retained)
        else:
            # A late context/readiness failure resumes the retained acquisition
            # and current same assignment; it never initializes another native.
            if (retained is None or assignment.generation != prior.generation+1
                    or assignment.session != retained['result']['physical_session_id']):
                raise PermissionError('replacement generation or acquired native changed')
        continuity = ManagerContinuity(
            assignment_reader=lambda ref: self.app.portfolio.operations._assignment_dict(
                self.app.assignments.get(ResourceRef.from_dict(ref))),
            assignments_port=self.app.assignments)
        result = continuity.replace_session(target['project_ref'], principal=self.app.manager_actor,
            request_key=request_key+':bind', assignment_ref=assignment.ref.to_dict(),
            expected_generation=assignment.generation,
            native_identity=retained['result']['physical_session_id'],
            old_session=assignment.session, actor=self.app.binding.authenticated_actor(self.app.manager_actor),
            custody={'state':'reconciled','schedule_id':schedule_id,'preserved_prior_native':native},
            context_builder=self.context_builder, readiness=self.readiness,
            operational_help=self.operational_help, restart=self.restart)
        return {**result,'acquisition':retained,'prior_schedule_id':schedule_id,
                'parent_acceptance_unchanged':True}

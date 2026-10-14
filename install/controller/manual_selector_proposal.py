"""Read-only exact reconciled predecessor -> existing new selector proposal."""
from copy import deepcopy
from herzchen.contracts import ResourceRef
from otto.portfolio.owner_readers import json_value
from otto.portfolio.operating_setup import read_setup,setup_reference,validate_execution_contract
from prompt_bound_manager_custody import retained,settled_anchor,digest

def require(value,message):
 if not value:raise PermissionError(message)
def proposal(app,*,schedule_id):
 due=app._read(schedule_id);current=app._current(due.assignment_ref,due.generation)
 setup=read_setup(app.portfolio.operations,due.target['project_ref'])
 require(setup is not None and setup['mode']=='manual','exact existing manual setup required')
 prior=app._read(setup['roles']['manager'])
 require(prior.schedule_id!=due.schedule_id and due.role==prior.role=='manager'
  and due.recipient==prior.recipient and due.generation==prior.generation
  and all(due.assignment_ref[k]==prior.assignment_ref[k]for k in('authority','kind','id'))
  and all(due.target['project_ref'][k]==prior.target['project_ref'][k]for k in('authority','kind','id')),
  'existing manual predecessor/current manager scope differs')
 body=retained(app,prior);anchor=settled_anchor(app,prior)
 require(due.stop_state=='active'and due.completion_state=='none'
  and due.delivery_state=='ready'and due.last_result is None
  and not due.accepted_checkins and not(due.host_evidence or{}).get('gateway_attempt')
  and due.in_flight_request in(None,due.invocation_identity)
  and due.target.get('native_binding')=={'schedule_id':anchor.schedule_id,'due_sha256':digest(anchor.to_dict())}
  and due.target.get('native_id')==body['scope']['prior_native_session'],
  'new occurrence must be unattempted and bind the exact independently settled native anchor')
 pin=(due.host_evidence or{}).get('supervisor_directive_ref')
 require(pin,'existing new occurrence lacks its authentic own-supervisor application')
 reader=app.portfolio.operations._owner_reader;report=reader.get_record(ResourceRef.from_dict(pin));value=report.payload.get('value')if report else None
 require(report is not None and report.ref.to_dict()==pin
  and isinstance(value,dict) and value.get('schema')=='otto.supervisor-directive-application.v1'
  and value.get('manager_assignment_ref')==due.assignment_ref and value.get('manager_generation')==due.generation
  and value.get('anchor_schedule_id')==prior.schedule_id and value.get('anchor_sha256')==digest(prior.to_dict())
  and value.get('continuation_schedule_id')==due.schedule_id,'new same-manager directive receipt differs')
 receipt=reader.get_receipt(value['adoption_key'])
 require(receipt is not None and receipt.operation=='work.assignment.adopt-resources'
  and receipt.result_ref==current.ref,'exact current resource adoption receipt unavailable')
 app._verify_native_binding(current,due.target['native_id'],anchor.schedule_id)
 observed=json_value(app.portfolio.operations.content_port.read(setup_reference(due.target['project_ref'])))
 document=observed.get('document')or{}
 require(document.get('maintainer')==app.actor and document.get('writable')is True
  and document.get('role')=='operating_setup','exact authentic service-owner writable setup required')
 readiness=app.runtime.prepare_execution_readiness(due=due)
 validate_execution_contract(readiness,due.profile,execution_manager=True)
 updated=deepcopy(setup);updated['roles']['manager']=schedule_id
 return {'schema':'otto.original-prompt-exact-manual-selector-proposal.v1',
  'document_ref':observed['identity'],'current_revision':observed['current_revision'],
  'before_setup':setup,'after_setup':updated,'before_setup_sha256':digest(setup),'after_setup_sha256':digest(updated),
  'original_disposition_ref':prior.host_evidence['manager_prompt_bound_custody_release']['disposition_ref'],
  'original_due_sha256':digest(prior.to_dict()),'new_due_sha256':digest(due.to_dict()),
  'existing_new_schedule_id':schedule_id,'same_native_session':due.target['native_id'],
  'native_anchor':due.target['native_binding'],'new_supervisor_application_ref':pin,
  'current_assignment_ref':current.ref.to_dict(),'generation':due.generation,
  'readiness_qualified':True,'provider_called':False,'records_modified':False}

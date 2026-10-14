"""Finite read of completion metadata; no replay, journal or judgment writes."""
from herzchen.contracts import ResourceRef

def read(service):
 state,owner=service.server.state,service.server.owner
 selected=state.get('task_refs')or{}
 if not isinstance(selected,dict)or len(selected)>32:
  return {'state':'unavailable','reason':'Finite selected task roster unavailable'}
 rows={}
 for alias,pin in selected.items():
  try:
   named=ResourceRef.from_dict(pin)
   if named.authority!=owner.store.authority or named.kind!='work.task':raise PermissionError('selected task is foreign')
   observed=owner.graph.reader.get_identity_bounded(ResourceRef(named.authority,named.kind,named.id),max_record_bytes=32768)
   record=observed.get('record')
   if record is None:raise PermissionError('bounded selected task unavailable')
   project=record.payload.get('project_ref')or{}
   if any(project.get(k)!=state['project_ref'].get(k)for k in('authority','kind','id')):raise PermissionError('task project differs')
   value={'state':'known','task_ref':record.ref.to_dict(),'projection_task_ref':pin,'lifecycle':record.payload.get('lifecycle')}
   completion=record.payload.get('completion')
   if isinstance(completion,dict):
    assignment=completion.get('assignment_ref')or{}
    if any(assignment.get(k)!=state['assignment_ref'].get(k)for k in('authority','kind','id'))or completion.get('generation')!=state['manager_generation']:
     raise PermissionError('completion manager identity or generation differs')
    key=completion.get('logical_request_key')
    if not isinstance(key,str)or not 1<=len(key)<=512:raise PermissionError('completion receipt key unavailable')
    receipt=owner.graph.reader.get_receipt(key)
    receipt_value=None if receipt is None else {'status':receipt.status.value,'operation':receipt.operation,
     'target':None if receipt.target is None else receipt.target.to_dict(),
     'result_ref':None if receipt.result_ref is None else receipt.result_ref.to_dict()}
    value.update(completion=completion,receipt=receipt_value,predicates={
     'task_lifecycle_completed':record.payload.get('lifecycle')=='completed',
     'completion_manager_current':completion.get('manager')==state['manager'],
     'completion_generation_current':completion.get('generation')==state['manager_generation'],
     'receipt_committed':receipt is not None and receipt.status.value=='committed',
     'receipt_operation_work_revise':receipt is not None and receipt.operation=='work.revise',
     'receipt_target_equals_completion_task_ref':receipt is not None and receipt.target is not None and receipt.target.to_dict()==completion.get('task_ref'),
     'receipt_result_equals_current_task_ref':receipt is not None and receipt.result_ref==record.ref},
     review_journal_predicates='not read by this finite completion metadata projection')
   rows[alias]=value
  except Exception as error:
   rows[alias]={'state':'unavailable','error':type(error).__name__,'reason':str(error)[:256]}
 return {'tasks':rows,'read_only':True,'effects_started':False,'provider_called':False,'replay_attempted':False}

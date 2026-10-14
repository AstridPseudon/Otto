"""Read only pools named by the selected manager's adopted configuration."""
from herzchen.contracts import ResourceRef
from herzchen.kernel.limits import LimitService

def read(service):
 owner,state=service.server.owner,service.server.state
 local=service._budget()
 result={'local_assessment':local,'manager':{'state':'unavailable','reason':'No exact adopted manager allowance is configured'},'provider_called':False,'effects_started':False}
 from completion_receipt_snapshot import read as read_completion_receipts
 result['completion_receipts']=read_completion_receipts(service)
 ref=state.get('role_configuration_ref')
 if ref is None:return result
 try:
  configuration=owner.content.read(ResourceRef.from_dict(ref))['content']
  pool_ref=(configuration.get('new_finite_allocations')or{}).get('manager')
  if pool_ref is None:return result
  named=ResourceRef.from_dict(pool_ref)
  due=service.server.due_port.read_due(service._current_manager_schedule())
  if(named.authority!=owner.store.authority or named.kind!='limit' or due is None
   or due['assignment_ref']!=state['assignment_ref']or due['generation']!=state['manager_generation']
   or due['role']!='manager' or due['recipient']!=state['manager']or due.get('allowance_ref')!=pool_ref):
   raise PermissionError('selected manager Due and adopted allowance differ')
  pool=LimitService(owner.store).get_pool(ResourceRef(named.authority,named.kind,named.id))
  if pool is None:raise PermissionError('exact named manager pool unavailable')
  result['manager']={'state':'known','pool_identity':named.to_dict(),
   'pool_ref':{**named.to_dict(),'revision':pool.current_revision},'version':pool.version,
   **{key:getattr(pool,key)for key in('capacity_units','cumulative_allowance_units','held_units','cumulative_used_units','available_capacity_units','remaining_allowance_units')},
   'configuration_ref':ref,'schedule_id':due['schedule_id'],'source':'owner.limit.reader; exact selected Due and adopted role configuration'}
 except Exception as error:
  result['manager']={'state':'unavailable','reason':'Exact owner manager allowance read could not be qualified','error':type(error).__name__,'message':str(error)[:256]}
 return result

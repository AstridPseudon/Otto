"""Optional canonical owner transfer after exact retired initializer + owner input.

The stable work descriptors and old manager history remain unchanged. This
late-registered mutation changes only current assignment owner, not identity,
principal, generation, resources, session, budgets, or execution.
"""
from hashlib import sha256
from herzchen.command_ports import command_facade
from herzchen.contracts import AuthenticatedActor,CommandEnvelope,DomainContribution,ResourceRef,TransactionContext,canonical_json

DOMAIN='otto.work.assignment-owner-migration'
OP='work.assignment.transfer-owner'
SCHEMA='otto.assignment-owner-migration.v1'
AUTHORIZATION='otto.service-owner.authorized-role-migration.v1'

def contribution():
 return DomainContribution(DOMAIN,'1.0','wrk',(),(),('work.assignment-owner-migration',),(OP,),
   ('work.assignment.owner-transferred',),SCHEMA,
   ('fnd-03.identities','fnd-03.record_references','fnd-03.transaction','handler-required',
    'mutation-resource:wrk.assignment','mutation-port:'+SCHEMA+'|'+OP+'|wrk.assignment|work.assignment.owner-transferred'))

def register(store):
 descriptor=contribution();found={d.domain_id:d for d in store.registered_domains()}
 if found.get(DOMAIN)==descriptor:return store.domain_handler((descriptor,))
 return store.register_domain_handler((descriptor,))

def require(value,message):
 if not value:raise PermissionError(message)

def _dict(value):return value.to_dict()if hasattr(value,'to_dict')else value

class _OwnerMigration:
 def __init__(self,writer):
  self.writer=writer.domain_handler((contribution(),));self.reader=self.writer.consumer()
 def transfer(self,target,*,from_owner,to_owner,expected_generation,disposition_ref,authorization_ref,due_ref,actor,request_key):
  require(isinstance(actor,AuthenticatedActor) and actor.actor==to_owner and actor.authority==self.writer.authority,
    'owner transfer requires authentic receiving service-owner actor')
  require(from_owner!=to_owner and request_key and request_key.strip()==request_key,'exact distinct old/new owner and request key required')
  target=ResourceRef.from_dict(_dict(target));disposition_ref=ResourceRef.from_dict(_dict(disposition_ref))
  authorization_ref=ResourceRef.from_dict(_dict(authorization_ref));due_ref=ResourceRef.from_dict(_dict(due_ref))
  require(target.kind=='wrk.assignment' and target.revision and type(expected_generation)is int and expected_generation>0,
    'exact current assignment revision/generation required')
  require(all(r.authority==actor.authority and r.revision for r in(target,disposition_ref,authorization_ref,due_ref)),
    'migration references must be exact local canonical revisions')
  body={'from_owner':from_owner,'to_owner':to_owner,'expected_generation':expected_generation,
    'disposition_ref':disposition_ref.to_dict(),'authorization_ref':authorization_ref.to_dict(),'due_ref':due_ref.to_dict()}
  fingerprint=sha256(canonical_json({'target':target.to_dict(),'body':body}).encode()).hexdigest()
  envelope=CommandEnvelope(OP,SCHEMA,target,TransactionContext(actor,request_key,fingerprint,
    expected_revision=target.revision,expected_version=int(target.revision.removeprefix('rev-'))),body)
  with self.writer.transaction()as tx:
   prior=self.writer.get_receipt(request_key)
   if prior is not None:
    self.writer.mutate(envelope,event_type='work.assignment.owner-transferred',result_ref=prior.result_ref,
      stream='assignment:'+target.id,transaction=tx)
    event=next(e for e in self.reader.list_events(stream='assignment:'+target.id)if e.event_id in prior.event_ids)
    return {'outcome':'replayed','assignment_ref':prior.result_ref.to_dict(),'payload':event.effects['result_payload']}
   current=self.reader.get_record(target)
   require(current is not None and current.ref==target and current.payload.get('generation')==expected_generation,
     'assignment owner migration is stale')
   payload=dict(current.payload)
   require((payload.get('manager')or payload.get('principal'))==from_owner and payload.get('role')=='manager'
     and payload.get('status')in('queued','reassigned') and payload.get('session')is None,
     'only exact current sessionless manager owner can transfer')
   disposition=self.reader.get_record(disposition_ref);authorization=self.reader.get_record(authorization_ref)
   due=self.reader.get_record(due_ref)
   for record,ref in((disposition,disposition_ref),(authorization,authorization_ref),(due,due_ref)):
    require(record is not None and record.ref==ref,'canonical migration prerequisite changed')
   for record in(disposition,authorization):
    require(record.payload.get('record_type')=='work.observation' and record.payload.get('observation_kind')=='report'
      and record.payload.get('assignment')==target.to_dict() and record.payload.get('generation')==expected_generation,
      'migration requires current same-assignment owner reports')
    require(any(e.operation=='work.report.append' and e.actor==actor
      for e in self.reader.list_events(subjects=(record.ref,))),'migration report lacks authenticated receiving owner event')
   scope=disposition.payload['value'].get('scope')or{};permission=authorization.payload['value'];state=due.payload
   require(disposition.payload['value'].get('schema')=='otto.claude-invalid-initializer-custody-disposition.v1'
     and disposition.payload['value'].get('provider_retry_allowed')is False
     and scope.get('assignment_ref')==target.to_dict() and scope.get('generation')==expected_generation,
     'exact prior invalid initializer disposition required')
   require(permission.get('schema')==AUTHORIZATION and permission.get('assignment_ref')==target.to_dict()
     and permission.get('generation')==expected_generation and permission.get('from_owner')==from_owner
     and permission.get('to_owner')==to_owner and permission.get('same_project')is True
     and permission.get('preserve_effects_and_debits')is True and permission.get('disposition_ref')==disposition_ref.to_dict(),
     'human-authorized service-owner migration input differs')
   marker=(state.get('host_evidence')or{}).get('claude_invalid_initializer_custody_release')or{}
   require(state.get('assignment_ref')==target.to_dict() and state.get('generation')==expected_generation
     and state.get('stop_state')=='stopped' and state.get('in_flight_request')is None
     and state.get('lifecycle_owner')==state.get('owner')==actor.actor
     and marker.get('disposition_ref')==disposition_ref.to_dict()
     and state.get('project_ref')==scope.get('project_ref',{}).get('id')==payload.get('scope',{}).get('id'),
     'retired original occurrence/project ownership does not match transfer')
   history=list(payload.get('history',()))
   history.append({'generation':expected_generation,'principal':payload.get('principal'),
     'reason':'authenticated-owner-transfer','from_manager':from_owner,'to_manager':to_owner,
     'disposition_ref':disposition_ref.to_dict(),'authorization_ref':authorization_ref.to_dict()})
   payload.update(manager=to_owner,history=history,owner_transfer_base_ref=target.to_dict(),
     owner_transfer_disposition_ref=disposition_ref.to_dict(),owner_transfer_authorization_ref=authorization_ref.to_dict())
   receipt=self.writer.mutate(envelope,identity_payload=payload,event_type='work.assignment.owner-transferred',
     effects={'result_payload':payload,'former_owner':from_owner,'receiving_owner':to_owner},
     stream='assignment:'+target.id,transaction=tx)
   return {'outcome':'transferred','assignment_ref':receipt.result_ref.to_dict(),'payload':payload}

AssignmentOwnerMigration=command_facade(_OwnerMigration,DOMAIN)

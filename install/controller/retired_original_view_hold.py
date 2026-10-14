"""Truthful service availability for two exact reconciled, unlaunchable originals."""
from otto.attention import DueRecord

def qualify(app,raw):
 due=raw if isinstance(raw,DueRecord)else DueRecord.from_dict(raw)
 evidence=due.host_evidence or{}
 if evidence.get('claude_invalid_initializer_custody_release'):
  from claude_invalid_initializer_custody import retained
  body=retained(app,due);reason='original invalid Claude initializer custody reconciled; same-project Codex migration remains pending'
 elif evidence.get('manager_prompt_bound_custody_release'):
  from prompt_bound_manager_custody import retained
  body=retained(app,due);reason='original prompt refused before spawn; own supervisor must adopt compact exact current direction'
 else:return None
 return {'outcome':'held','schedule_id':due.schedule_id,'generation':due.generation,
  'execution_held':True,'current_context_qualified':False,'original_unknown_retained':True,
  'custody_disposition_ref':evidence.get('claude_invalid_initializer_custody_release',evidence.get('manager_prompt_bound_custody_release'))['disposition_ref'],
  'reason':reason,'provider_called':False,'effects_started':False,'retry':False,
  'original_due_sha256':body['scope']['due_sha256']}

def fence(service,hold):
 original=service._execution
 def execution(*args,**kwargs):
  app=original(*args,**kwargs);start=app.start
  def held_start(*args,**kwargs):
   schedule=kwargs.get('schedule_id')or(args[0]if args else None)
   return dict(hold)if schedule==hold['schedule_id']else start(*args,**kwargs)
  app.start=held_start;return app
 service._execution=execution;service.server._execution=execution
 service.server.state['execution_hold']=dict(hold)

"""Exact assignment-event metadata selects finish intents before bounded bodies."""
import hashlib
from collections.abc import Mapping
from herzchen.contracts import ResourceRef
FIELDS={'record_type':('record_type',),'observation_kind':('observation_kind',),
 'assignment':('assignment',),'generation':('generation',),'schema':('value','schema'),
 'logical_key':('value','logical_request_key'),'task':('value','content','task'),
 'review_key':('value','content','review_key')}
def _identity(ref):return (ref.authority,ref.kind,ref.id)
def journal_header_stage(commands,schema,logical):
 """A typed journey journal cannot silently become an unidentified stage."""
 if schema!='otto.manager-journey.v1':return None
 if not isinstance(logical,str)or not logical.startswith('journey:'):
  raise PermissionError('ambiguous manager journey journal header')
 for stage in ('finish-intent','intent','review','planning-input','planning-authored','project-intent','finish-project-pin'):
  suffix=':'+stage
  if logical.endswith(suffix):
   commands._key({'request_key':logical[len('journey:'):-len(suffix)]});return stage
 marker=':finish-project-pin-refresh:'
 if marker in logical:
  key,revision=logical[len('journey:'):].rsplit(marker,1)
  commands._key({'request_key':key})
  if revision and revision==revision.strip()and len(revision)<=128:return 'finish-project-pin-refresh'
 raise PermissionError('ambiguous manager journey journal header')

def selected_reports(commands,*,aliases,review_key=None):
 state=commands.state;reader=commands.owner.graph.reader;actor=commands._authorize()
 if not isinstance(aliases,tuple)or not aliases or len(aliases)>4 or len(set(aliases))!=len(aliases)or not set(aliases).issubset(state['task_refs']):raise PermissionError('finite selected completion aliases required')
 if review_key is not None:commands._key({'request_key':review_key})
 assignment=ResourceRef.from_dict(state['assignment_ref']);ancestors=[r.to_dict()for r in commands._adopted_assignment_refs(assignment)]
 events=[e for e in reader.list_events(stream='report:'+assignment.id)if e.operation=='work.report.append']
 if len(events)>512:raise PermissionError('completion assignment append stream exceeds finite bound')
 records=[];ignored=[]
 for offset in range(0,len(events),32):
  batch=events[offset:offset+32]
  refs=[e.subject for e in batch]
  if any(r.authority!=assignment.authority or r.kind!='wrk.report'for r in refs):raise PermissionError('foreign report in selected assignment stream')
  rows=commands.owner.store.consumer().project_identity_fields_for_refs(refs,fields=FIELDS,max_refs=32,max_projection_bytes=65536)
  if len(rows)!=len(batch):raise PermissionError('completion report metadata inventory differs')
  for event,meta in zip(batch,rows):
   if meta.get('state')!='available':raise PermissionError('completion report metadata '+str(meta.get('state'))+'; no intent disposition inferred: '+event.subject.id)
   fields=meta['fields'];logical=fields.get('logical_key');schema=fields.get('schema')
   journal_header_stage(commands,schema,logical)
   finish=isinstance(logical,str)and logical.startswith('journey:')and logical.endswith(':finish-intent')
   if not finish:
    ignored.append({'report_ref':meta['ref'],'reason':'metadata is not a finish-intent journal','body_read':False});continue
   if schema!='otto.manager-journey.v1':raise PermissionError('finish-intent journal schema is missing or differs')
   task=fields.get('task');review=fields.get('review_key')
   if not isinstance(task,str)or task not in state['task_refs']or not isinstance(review,str):raise PermissionError('finish-intent metadata task/review scope unavailable')
   if review_key is not None and review!=review_key:
    ignored.append({'report_ref':meta['ref'],'reason':'different exact review key','body_read':False});continue
   if task not in aliases:
    if review_key is not None:raise PermissionError('same review finish intent belongs to another task')
    ignored.append({'report_ref':meta['ref'],'reason':'different selected task','body_read':False});continue
   key=logical[len('journey:'):-len(':finish-intent')];commands._key({'request_key':key});commands._key({'request_key':review})
   expected_id='report-'+hashlib.sha256((assignment.id+':'+logical).encode()).hexdigest()[:28]
   current=ResourceRef.from_dict(meta['ref']);receipt=reader.get_receipt(logical)
   if (event.actor!=actor or event.effects.get('generation')!=state['manager_generation']
       or event.effects.get('assignment')not in ancestors or fields.get('assignment')not in ancestors
       or fields.get('generation')!=state['manager_generation']or fields.get('record_type')!='work.observation'
       or fields.get('observation_kind')!='report' or event.subject.id!=expected_id
       or receipt is None or receipt.status.value!='committed'or receipt.operation!='work.report.append'
       or _identity(receipt.target)!=_identity(current)or receipt.result_ref!=current
       or event.event_id not in receipt.event_ids):raise PermissionError('selected finish-intent event/receipt provenance differs')
   bounded=reader.get_identity_bounded(current,max_record_bytes=65536);record=bounded.get('record')
   if record is None:raise PermissionError('selected finish-intent body '+str(bounded.get('state'))+'; no disposition inferred: '+current.id)
   value=record.payload.get('value');request=value.get('content')if isinstance(value,Mapping)else None
   if (record.ref!=current or record.payload.get('assignment')!=fields['assignment']
       or record.payload.get('generation')!=fields['generation']or not isinstance(value,Mapping)
       or value.get('schema')!=schema or value.get('logical_request_key')!=logical
       or not isinstance(request,Mapping)or request.get('task')!=task
       or request.get('review_key')!=review or request.get('request_key')!=key):raise PermissionError('selected finish-intent body differs from authenticated metadata')
   records.append(record)
 return tuple(records),{'schema':'otto.completion-intent-selection.v1','metadata_reports':len(events),
  'selected_body_reads':len(records),'ignored':ignored,'read_only':True,'unknown_relevant_reports_skipped':False}

def read_journal(commands,key,stage,*,adopted_history):
 """Only exact read-only completion stages; never enumerate observation bodies."""
 if stage not in {'intent','review','finish-intent'}:raise PermissionError('finite completion journal stage required')
 commands._key({'request_key':key});actor=commands._authorize();state=commands.state;reader=commands.owner.graph.reader
 assignment=ResourceRef.from_dict(state['assignment_ref']);logical='journey:'+key+':'+stage
 ref=ResourceRef(assignment.authority,'wrk.report','report-'+hashlib.sha256((assignment.id+':'+logical).encode()).hexdigest()[:28])
 receipt=reader.get_receipt(logical);bounded=reader.get_identity_bounded(ref,max_record_bytes=65536);record=bounded.get('record')
 if record is None:
  if bounded.get('state')=='missing'and receipt is None:return None
  raise PermissionError('exact completion journal '+str(bounded.get('state'))+'; no replay/disposition inferred')
 ancestors=[r.to_dict()for r in commands._adopted_assignment_refs(assignment)]if adopted_history else [assignment.to_dict()]
 value=record.payload.get('value')
 record_assignment=record.payload.get('assignment')
 record_generation=record.payload.get('generation')
 if (adopted_history and type(record_generation) is int
     and type(state.get('manager_generation')) is int
     and record_generation < state['manager_generation']
     and isinstance(record_assignment, Mapping)
     and _identity(ResourceRef.from_dict(record_assignment)) == _identity(assignment)):
  # A reassignment ends the old manager's journal authority. Preserve the
  # historical record, but it is not a current continuation under the newer
  # generation and therefore has no current read result.
  return None
 if (receipt is None or receipt.status.value!='committed'or receipt.operation!='work.report.append'
     or _identity(receipt.target)!=_identity(ref)or receipt.result_ref!=record.ref
     or record.payload.get('record_type')!='work.observation'or record.payload.get('observation_kind')!='report'
     or record.payload.get('assignment')not in ancestors or record.payload.get('generation')!=state['manager_generation']
     or not isinstance(value,Mapping)or value.get('schema')!='otto.manager-journey.v1'
     or value.get('logical_request_key')!=logical):raise PermissionError('exact completion journal receipt/scope differs')
 events=reader.list_events(stream='report:'+assignment.id)
 if len(events)>512:raise PermissionError('exact completion journal event stream exceeds finite bound')
 matching=[e for e in events if e.event_id in receipt.event_ids]
 if (len(matching)!=1 or matching[0].operation!='work.report.append'or matching[0].actor!=actor
     or _identity(matching[0].subject)!=_identity(ref)
     or matching[0].effects.get('assignment')!=record.payload['assignment']
     or matching[0].effects.get('generation')!=state['manager_generation']):raise PermissionError('exact completion journal authenticated event differs')
 return value['content']

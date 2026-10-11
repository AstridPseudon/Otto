import json, os, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
import herzchen.adapters.host as host
from herzchen.contracts import HostRequest, HostOperation, HostIdentity, ResourceRef

class NativeResumeTraceTests(unittest.TestCase):
 def fixture(self, path):
  header=(json.dumps({'type':'session_meta','payload':{'id':'issued-session'}})+'\n').encode()
  path.write_bytes(header+b'{"type":"old-context"}\n')
  b=host.CodexCliBinding(worktree=str(path.parent),launcher='/fixture/codex',model='fixture',reasoning='high',prompt='Exact current intent',trusted_thread_reader=Mock(return_value={'thread':{'id':'issued-session','path':str(path)}}))
  return b,header
 def test_same_invocation_reuses_trusted_locator_without_second_metadata_rpc(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'native.jsonl';b,_=self.fixture(path)
   b.trusted_thread_reader.side_effect=[{'thread':{'id':'issued-session','path':str(path)}},TimeoutError('second read must not occur')]
   def finish(process,prompt,**kwargs):
    events=[{'type':'event_msg','payload':{'type':'task_started','turn_id':'turn1','started_at':int(time.time())}},{'type':'turn_context','payload':{'turn_id':'turn1','model':'fixture','collaboration_mode':{'settings':{'reasoning_effort':'high'}},'sandbox_policy':{'type':'read-only'},'approval_policy':'never'}},{'type':'event_msg','payload':{'type':'item_completed','turn_id':'turn1','thread_id':'issued-session','item':{'type':'UserMessage','content':[{'type':'Text','text':prompt}]}}},{'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn1','completed_at':int(time.time())}}]
    with path.open('ab')as f:f.write(('\n'.join(json.dumps(e)for e in events)+'\n').encode())
    return json.dumps({'type':'thread.started','thread_id':'issued-session'})+'\n'+json.dumps({'type':'turn.completed','turn_id':'turn1'}),'',0,None
   with patch.object(host.subprocess,'Popen',return_value=Mock(pid=1234)),patch.object(host,'_communicate_after_native_start',side_effect=finish):
    receipt,envelope=b.execute(HostRequest(HostOperation.RESUME,HostIdentity('fixture-worker','issued-session'),ResourceRef('fixture','work.task','task','rev-1'),'read-only'))
   self.assertEqual(receipt.outcome.value,'succeeded')
   self.assertTrue(envelope['host_evidence']['invocation_turn_verified'])
   self.assertEqual(b.trusted_thread_reader.call_count,1)
 def test_delayed_exact_message_uses_existing_finite_admission_budget(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'native.jsonl';b,_=self.fixture(path)
   clock=[0.0]; sleeps=[]; prompt_value=[]
   b.monotonic_clock=lambda:clock[0]
   b._native_start_callback=Mock()
   def append(event):
    with path.open('ab') as stream:stream.write((json.dumps(event)+'\n').encode())
   def advance(_):
    clock[0]+=6; sleeps.append(clock[0])
    if len(sleeps)==2:
     append({'type':'event_msg','payload':{'type':'item_completed','turn_id':'turn1','thread_id':'issued-session','item':{'type':'UserMessage','content':[{'type':'Text','text':prompt_value[0]}]}}})
   def finish(process,prompt,**kwargs):
    prompt_value.append(prompt)
    append({'type':'event_msg','payload':{'type':'task_started','turn_id':'turn1','started_at':int(time.time())}})
    append({'type':'turn_context','payload':{'turn_id':'turn1','model':'fixture','collaboration_mode':{'settings':{'reasoning_effort':'high'}},'sandbox_policy':{'type':'read-only'},'approval_policy':'never'}})
    kwargs['native_start_callback'](None,'current-start')
    append({'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn1','completed_at':int(time.time())}})
    return json.dumps({'type':'thread.started','thread_id':'issued-session'})+'\n'+json.dumps({'type':'turn.completed','turn_id':'turn1'}),'',0,None
   with patch.object(host.subprocess,'Popen',return_value=Mock(pid=1234)),patch.object(host,'_communicate_after_native_start',side_effect=finish),patch.object(host.time,'sleep',side_effect=advance):
    receipt,envelope=b.execute(HostRequest(HostOperation.RESUME,HostIdentity('fixture-worker','issued-session'),ResourceRef('fixture','work.task','task','rev-1'),'read-only'))
   self.assertEqual(receipt.outcome.value,'succeeded',(receipt,envelope))
   self.assertEqual(sleeps,[6,12])
   self.assertEqual(b._native_start_callback.call_count,1)
   self.assertEqual(b._native_start_callback.call_args.args[0],'turn1')
   self.assertTrue(envelope['host_evidence']['invocation_turn_verified'])
 def test_file_replacement_header_boundary_and_symlink_fail_closed(self):
  for mode in ['replacement','header','truncate','boundary','symlink']:
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'native.jsonl';b,_=self.fixture(path)
    location,boundary,header,snapshot=b._resume_trace_boundary('issued-session')
    if mode=='replacement':
     replacement=Path(directory)/'replacement';replacement.write_bytes(path.read_bytes());replacement.replace(path)
    elif mode=='header':
     with path.open('r+b')as f:f.write(b'x')
    elif mode=='truncate':path.write_bytes(header)
    elif mode=='boundary':
     with path.open('r+b')as f:f.seek(boundary-3);f.write(b'x')
    else:
     moved=Path(directory)/'moved';path.replace(moved);path.symlink_to(moved)
    with self.assertRaises((ValueError,OSError)):b._resume_trace_tail(location,boundary,header,snapshot)
 def test_large_history_reads_only_header_boundary_and_append_tail(self):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'native.jsonl';b,header=self.fixture(path)
   with path.open('r+b')as f:f.seek(38*1024*1024);f.write(b'\n')
   location,boundary,observed,snapshot=b._resume_trace_boundary('issued-session')
   with path.open('ab')as f:f.write(b'{"type":"new-context"}\n')
   tail=b._resume_trace_tail(location,boundary,observed,snapshot)
   self.assertEqual(tail,header+b'{"type":"new-context"}\n')
   self.assertLess(len(snapshot[2]),4097)

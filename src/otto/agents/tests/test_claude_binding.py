"""Synthetic provider negatives and real local-pipe owner integration.

Every provider stream in this file is SYNTHETIC. The installed test checks
launcher metadata and actual scope refusal only, never paid model behavior.
"""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from otto.agents.claude_cli import (ClaudeBindingError, ClaudeCliTransport, ClaudeStream,
    LauncherPin, MacWriteScope, VERSION, file_digest, digest)
from otto.agents.claude_adapter import ClaudeWorkerAdapter, ClaudeNativeResultVerifier, native_context
from otto.portfolio.occurrence_reads import handle, result_view, read_captured_artifact


def frames(prompt='input', cwd='/scope', tools=('Edit', 'Glob', 'Grep', 'Read', 'Write'), session='native-session', error=False):
    return [
        {'type':'system','subtype':'init','session_id':session,'cwd':cwd,'model':'gpt-test',
         'permissionMode':'bypassPermissions','tools':list(tools),'mcp_servers':[],'plugins':[],'skills':[],'slash_commands':[]},
        {'type':'user','uuid':'native-input-uuid','session_id':session,'parent_tool_use_id':None,
         'message':{'role':'user','content':[{'type':'text','text':prompt}]}},
        {'type':'assistant','uuid':'native-message-uuid','session_id':session,'parent_tool_use_id':None,
         'message':{'role':'assistant','model':'gpt-test','content':[{'type':'tool_use','id':'write-1',
         'name':'Write','input':{'file_path':cwd+'/answer.txt','content':'Useful artifact\n'}}]}},
        {'type':'user','uuid':'native-tool-result-uuid','session_id':session,'parent_tool_use_id':None,
         'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'write-1','content':'written','is_error':False}]}},
        {'type':'result','subtype':'success','is_error':error,'session_id':session,'uuid':'native-result-uuid',
         'result':'Delivered useful artifact.','usage':{'input_tokens':11,'output_tokens':4,'cache_read_input_tokens':0}}]


def parse(events, **kwargs):
    p = ClaudeStream(prompt='input', cwd='/scope', model='gpt-test', tools=('Edit','Glob','Grep','Read','Write'), **kwargs)
    for event in events: p.feed(json.dumps(event).encode())
    return p


class ParserTests(unittest.TestCase):
    def test_selected_shape_and_native_usage(self):
        p=parse(frames()); self.assertEqual(p.finish(0)['outcome'],'succeeded')
        self.assertEqual(p.usage()['metrics']['cache_read_input_tokens'],0)
        self.assertEqual(p.refs['final_answer']['event_type'],'result')

    def test_foreign_scope_identity_input_model_and_ingress(self):
        for index, field, value in [(0,'cwd','/other'),(0,'model','foreign'),(0,'session_id','other'),
                (0,'tools',['Bash']), (0,'mcp_servers',[{'name':'foreign'}]), (0,'plugins',['foreign']),
                (0,'permissionMode','dontAsk'),(1,'session_id','other'),(2,'parent_tool_use_id','child')]:
            events=frames();events[index][field]=value
            with self.subTest(index=index,field=field),self.assertRaises(ClaudeBindingError): parse(events,session='native-session')
        events=frames();events[1]['message']['content'][0]['text']='changed'
        with self.assertRaises(ClaudeBindingError):parse(events)

    def test_initializer_exit_kill_incomplete_and_duplicates(self):
        for events in [frames()[:1],frames()[:-1],frames()+[frames()[-1]],frames()[:3]+frames()[2:]]:
            with self.assertRaises(ClaudeBindingError):parse(events).finish(0)
        with self.assertRaises(ClaudeBindingError):parse(frames()).finish(1)
        events=frames();events.pop(3)
        with self.assertRaises(ClaudeBindingError):parse(events)

    def test_error_is_not_success_even_when_subtype_success(self):
        p=parse(frames(error=True)); self.assertEqual(p.finish(1)['outcome'],'failed')

    def test_spoofed_worker_usage_does_not_replace_native_usage(self):
        events=frames();events[2]['message']['content'].append({'type':'text','text':'{"usage":{"input_tokens":999}}'})
        p=parse(events);self.assertEqual(p.usage()['metrics']['input_tokens'],11)
        for usage in [None,{}, {'input_tokens':True},{'input_tokens':-1},{'input_tokens':1.5}]:
            events=frames();events[-1]['usage']=usage;p=parse(events)
            self.assertIn(p.usage()['state'],{'invalid','unavailable'});self.assertEqual(p.finish(0)['outcome'],'succeeded')

    def test_invalid_json_oversized_and_partial_stream(self):
        p=ClaudeStream(prompt='input',cwd='/scope',model='gpt-test',tools=())
        for raw in [b'[]',b'{',b'{\"type\":\"system\",\"type\":\"result\"}',b'{"type":"result","usage":NaN}',b'a'*262145]:
            with self.assertRaises(ClaudeBindingError):p.feed(raw)


# Only the provider process/OS fence is substituted. The real transport,
# parser, owner Store, gateway, admission, capture and reads remain exercised.
PROCESS = r'''
import sys,json,os
frame=json.loads(sys.stdin.readline());prompt=frame['message']['content'][0]['text'];session=frame.get('session_id') or 'native-session'
init=prompt.startswith('Initialize this session only.');tools=[] if init else ['Edit','Glob','Grep','Read','Write'];cwd=os.getcwd()
def emit(e): print(json.dumps(e),flush=True)
emit({'type':'system','subtype':'init','session_id':session,'cwd':cwd,'model':'gpt-test','permissionMode':'bypassPermissions','tools':tools,'mcp_servers':[],'plugins':[],'skills':[],'slash_commands':[]})
emit({'type':'user','uuid':'input-init' if init else 'input-work','session_id':session,'message':{'role':'user','content':[{'type':'text','text':prompt}]}})
if not init:
 path=os.path.join(cwd,'answer.txt')
 emit({'type':'assistant','uuid':'assistant-1','session_id':session,'message':{'role':'assistant','model':'gpt-test','content':[{'type':'tool_use','id':'write-1','name':'Write','input':{'file_path':path,'content':'Useful artifact\n'}}]}})
 with open(path,'w') as f:f.write('Useful artifact\n')
 emit({'type':'user','uuid':'tool-result-1','session_id':session,'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'write-1','is_error':False,'content':'written'}]}})
emit({'type':'result','subtype':'success','is_error':False,'session_id':session,'uuid':'result-init' if init else 'result-work','result':'READY' if init else 'Delivered useful artifact.','usage':{'input_tokens':11,'output_tokens':4}})
'''


class SyntheticScope:
    identity=MacWriteScope.identity
    def __init__(self,root,state):
        self.workspace,self.state_root=root,state
        self.pin={'identity':self.identity,'workspace':root,'state_root':state,'evidence_kind':'SYNTHETIC'}
    def preflight(self):return {**self.pin,'verified':True}
    def wrap(self,command,**options):return command


def local_transport(root,state,script=PROCESS,timeout=5):
    executable=str(Path(sys.executable).resolve())
    pin=LauncherPin(executable,executable,file_digest(Path(executable)),VERSION)
    calls=[]; processes=[]
    def process_factory(command,**kwargs):
        calls.append(command);p=subprocess.Popen([sys.executable,'-c',script],**kwargs);processes.append(p);return p
    t=ClaudeCliTransport(pin,SyntheticScope(root,state),model='gpt-test',reasoning='high',
                         timeout_seconds=timeout,process_factory=process_factory)
    t.calls,t.processes=calls,processes
    return t


class AuthenticationTests(unittest.TestCase):
    def test_existing_login_namespace_and_no_inherited_provider_override(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            transport = local_transport(root, root)
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR':'/wrong',
                    'CLAUDE_CODE_OAUTH_TOKEN':'test-only', 'ANTHROPIC_API_KEY':'test-only'}):
                env = transport.environment()
            self.assertNotIn('CLAUDE_CONFIG_DIR', env)
            self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            self.assertEqual(env['CLAUDE_CODE_SAFE_MODE'], '1')
            transport.authentication = 'isolated'
            self.assertEqual(transport.environment()['CLAUDE_CONFIG_DIR'], root)


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='otto-d03-local-');self.addCleanup(self.temp.cleanup)
        self.root=str(Path(self.temp.name).resolve());self.state=self.root+'/state';Path(self.state).mkdir()

    def test_real_pipe_inert_then_admitted_useful_tool_artifact(self):
        t=local_transport(self.root,self.state)
        init=t.run('Initialize this session only. Return READY.',initializer=True)
        self.assertEqual(init['result']['result'],'READY');self.assertFalse(Path(self.root,'answer.txt').exists())
        admissions=[]
        work=t.run('input',session=init['session_id'],on_input=admissions.append)
        self.assertEqual(admissions,['input-work']);self.assertEqual(Path(self.root,'answer.txt').read_text(),'Useful artifact\n')
        self.assertEqual(work['scope']['evidence_kind'],'SYNTHETIC');self.assertEqual(len(t.calls),2)
        self.assertIn('--dangerously-skip-permissions', t.calls[-1])
        self.assertNotIn('--permission-mode', t.calls[-1])

    def test_process_kill_partial_exit_timeout_reaps_without_retry(self):
        for script in ['import os;os._exit(9)','import sys;print("{",flush=True)',
                       'import sys,time;sys.stdin.read();time.sleep(20)']:
            t=local_transport(self.root,self.state,script,timeout=.2)
            with self.assertRaises(ClaudeBindingError):t.run('input')
            self.assertEqual(len(t.calls),1);self.assertIsNotNone(t.processes[0].poll())

    def test_binary_drift_and_removal_prevent_process_creation(self):
        fake=Path(self.root,'launcher');fake.write_bytes(b'pinned')
        pin=LauncherPin(str(fake),str(fake),file_digest(fake),VERSION)
        t=local_transport(self.root,self.state);t.pin=pin
        fake.write_bytes(b'drifted')
        with self.assertRaises(ClaudeBindingError):t.run('input')
        fake.unlink()
        with self.assertRaises(OSError):t.run('input')
        self.assertEqual(t.calls,[])

    def test_required_os_fence_failure_prevents_initializer(self):
        t=local_transport(self.root,self.state)
        def denied():raise ClaudeBindingError('OS scope unavailable')
        t.scope.preflight=denied
        with self.assertRaises(ClaudeBindingError):t.run('Initialize this session only.',initializer=True)
        self.assertEqual(t.calls,[])


class OwnerTests(unittest.TestCase):
    def setUp(self):
        # Reuse the accepted common owner fixture without inheriting its suite.
        from test_execution_application import ExecutionApplicationTests
        self.f=ExecutionApplicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=str(Path(self.f.temporary.name).resolve())
        self.state=tempfile.TemporaryDirectory(prefix='otto-d03-native-state-');self.addCleanup(self.state.cleanup)
        self.t=local_transport(self.root,str(Path(self.state.name).resolve()))
        self.adapter=ClaudeWorkerAdapter(owner='worker',source=self.root,worktree=self.root,
            launcher_pin=self.t.pin,state_root=self.state.name,requested_model='gpt-test',transport=self.t)
        self.app=self.f.owner.execution_application(due_port=self.f.port,adapter=self.adapter,
            clock=lambda: __import__('test_execution_application').NOW,native_result_verifier=ClaudeNativeResultVerifier())
        self.request=self.f.request();self.request['instruction_contract']['read_targets']=[self.root]

    def test_actual_owner_admission_capture_artifact_detach_read_dedup(self):
        result=self.app.assign_and_start(**self.request)
        self.assertEqual(result['outcome'],'succeeded',result)
        self.assertEqual(len(self.t.calls),2)
        due=self.f.port.read_due(result['schedule_id']);view=result_view(due)
        self.assertTrue(view['useful_admission']);self.assertTrue(view['required_capture'])
        self.assertEqual(view['conclusion'],'Delivered useful artifact.')
        self.assertEqual(view['result_ref']['kind'],'wrk.result');self.assertEqual(view['usage']['metrics']['input_tokens'],11)
        self.assertNotIn('content_base64',view['artifacts'][0])
        ref=view['artifacts'][0]['ref'];counts=self.f.store.consumer().snapshot_counts()
        for _ in range(3):
            artifact=read_captured_artifact(due,artifact_ref=ref,max_bytes=7)
            self.assertEqual(base64.b64decode(artifact['content_base64']),b'Useful ')
            self.assertEqual(result_view(due)['conclusion'],view['conclusion'])
        self.assertEqual(self.f.store.consumer().snapshot_counts(),counts)
        replay=self.app.assign_and_start(**self.request);self.assertEqual(replay['outcome'],'replayed',replay)
        self.assertEqual(len(self.t.calls),2)
        # Live file drift cannot change the retained captured artifact bytes.
        Path(self.root,'answer.txt').write_text('changed')
        self.assertEqual(base64.b64decode(read_captured_artifact(due,artifact_ref=ref)['content_base64']),b'Useful artifact\n')
        foreign=copy.deepcopy(ref);foreign['result_ref']['id']='foreign'
        self.assertEqual(read_captured_artifact(due,artifact_ref=foreign)['reason'],'artifact_foreign_ref')
        with self.assertRaises(ValueError):read_captured_artifact(due,artifact_ref=ref,max_bytes=4097)

    def test_initializer_only_or_missing_artifact_never_publish(self):
        self.t.process_factory=lambda command,**kwargs:subprocess.Popen([sys.executable,'-c',PROCESS.replace("f.write('Useful artifact\\n')","f.write('Useful artifact\\n')" )
            .replace("'name':'Write'","'name':'Read'")],**kwargs)
        result=self.app.assign_and_start(**self.request)
        self.assertNotEqual(result['outcome'],'succeeded',result)
        due=self.f.port.read_due(result['schedule_id']);self.assertFalse(result_view(due)['required_capture'])

    def test_forged_scope_and_role_fail_before_provider(self):
        self.request['instruction_contract']['delegation']={'max_depth':1,'result_consumption':'yield'}
        self.request['instruction_contract']['allowed_operations'].append('canonical_child_commands')
        self.request['instruction_contract']['authority']['permitted_effects'].append('canonical_child_commands')
        result=self.app.assign_and_start(**self.request)
        self.assertNotEqual(result['outcome'],'succeeded');self.assertEqual(len(self.t.calls),0)
        with self.assertRaises(ClaudeBindingError):self.adapter.validate_owner_host_composition(role='manager',profile='workspace-write')

    def test_optional_invalid_usage_does_not_change_captured_outcome(self):
        self.t.process_factory=lambda command,**kwargs:subprocess.Popen([sys.executable,'-c',
            PROCESS.replace("'input_tokens':11", "'input_tokens':True")],**kwargs)
        result=self.app.assign_and_start(**self.request)
        self.assertEqual(result['outcome'],'succeeded',result.get('error'))
        view=result_view(self.f.port.read_due(result['schedule_id']))
        self.assertTrue(view['required_capture']);self.assertEqual(view['usage']['state'],'invalid')

    def test_native_failure_is_retained_without_success_or_publication(self):
        self.t.process_factory=lambda command,**kwargs:subprocess.Popen([sys.executable,'-c',
            PROCESS.replace("'is_error':False,'session_id':session,'uuid':'result-init'",
                "'is_error':not init,'session_id':session,'uuid':'result-init'")],**kwargs)
        result=self.app.assign_and_start(**self.request)
        self.assertNotEqual(result['outcome'],'succeeded')
        due=self.f.port.read_due(result['schedule_id'])
        retained=due['host_evidence']['gateway_attempt']['result']
        self.assertTrue(retained['raw_result']['native_failure']['is_error'])
        self.assertFalse(result_view(due)['required_capture'])

    def test_read_artifact_installed_parser_shape_and_native_requirement(self):
        import argparse
        from otto.portfolio.manager_journey_client import add_manager_journey_parsers, requires_native_caller
        parser=argparse.ArgumentParser();add_manager_journey_parsers(parser.add_subparsers(dest='command'))
        parsed=parser.parse_args(['read-artifact','--occurrence','{}','--artifact-ref','{}','--max-bytes','7'])
        self.assertEqual(parsed.max_bytes,7);self.assertTrue(requires_native_caller('read-artifact'))

    def test_bad_owner_authorization_does_not_deliver_useful_input(self):
        original=self.app.runtime.adapter.bind_owner_authorization
        def corrupted(authorizer,**kwargs):
            return original(lambda *args:{**authorizer(*args),'generation':999},**kwargs)
        self.app.runtime.adapter.bind_owner_authorization=corrupted
        result=self.app.assign_and_start(**self.request)
        self.assertNotEqual(result['outcome'],'succeeded');self.assertEqual(len(self.t.calls),1)
        self.assertFalse(Path(self.root,'answer.txt').exists())


if __name__=='__main__':unittest.main()

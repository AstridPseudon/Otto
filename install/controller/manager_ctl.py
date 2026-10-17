"""Installed ordinary client: only commands provided by this host and maintained service."""
from pathlib import Path
import argparse,json,os,sys,time,uuid
HERE=Path(os.path.abspath(__file__)).parent # preserve invoked fixed-view identity through shared client symlinks
if HERE.name=='prepared':HERE=HERE.parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'runtime-source'))
from native_caller_address import native_caller_socket_path
IPC=HERE/'manager-ipc'
def call(payload):
 from otto.portfolio.manager_journey_client import read_command_response,read_command_status
 token=uuid.uuid4().hex;request=IPC/('request-'+token+'.json')
 temporary=IPC/('.request-'+token+'.tmp')
 fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  with os.fdopen(fd,'w') as stream:json.dump(payload,stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
  os.replace(temporary,request)
 finally:
  temporary.unlink(missing_ok=True)
 from otto.portfolio.manager_journey_client import wait_command_response
 return wait_command_response(IPC,token,timeout_seconds=2.0)

def main():
 from otto.portfolio.manager_journey_client import add_manager_journey_parsers,read_command_status
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True);sub.add_parser('status');sub.add_parser('whoami',help='read current caller through version-qualified native socket custody');sub.add_parser('effective-context',help='read caller direction/context through actual native socket custody')
 report=sub.add_parser('report');report.add_argument('--task',required=True);report.add_argument('--request-key',required=True);report.add_argument('--summary',required=True);report.add_argument('--next-action',required=True);report.add_argument('--continue-project',action='store_true')
 worker=sub.add_parser('run-worker',help='Prepare a finite child using current task alias, route, principal, stable request-key and focus; return retained handle. Owner executes its start after authorization/capacity. review-input follows the retained candidate, not before the first worker.');worker.add_argument('--task',required=True);worker.add_argument('--route',required=True,choices=['normal','xhard']);worker.add_argument('--principal',required=True);worker.add_argument('--request-key',required=True);worker.add_argument('--focus',required=True,help='1..4000 characters. Pin an exact owned scope-manifest path and SHA for long file lists; preserve rejected intent and use a distinct corrected key.')
 continuation=sub.add_parser('manager-continue');continuation.add_argument('--report-key',required=True);continuation.add_argument('--operation',default='prepare');continuation.add_argument('--new-report-key')
 lifecycle=sub.add_parser('project-lifecycle-read');lifecycle.add_argument('--task',default=next(iter(json.loads((HERE/'canonical-state.json').read_text())['task_refs'])))
 commit=sub.add_parser('commit');commit.add_argument('--message',required=True);commit.add_argument('--path',action='append',dest='paths',required=True)
 add_manager_journey_parsers(sub);args=vars(p.parse_args())
 from otto.portfolio.manager_journey_client import requires_native_caller
 if requires_native_caller(args['command']):
  from otto.portfolio.caller_client import call as caller_call
  result=caller_call(str(native_caller_socket_path()),args)
 elif args['command']=='command-status':
  state=json.loads((HERE/'canonical-state.json').read_text());scope={'principal':state['manager'],'generation':state['manager_generation'],'assignment_identity':{k:state['assignment_ref'][k]for k in('authority','kind','id')},'project_identity':{k:state['project_ref'][k]for k in('authority','kind','id')}}
  shared=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller/manager-ipc');token=args['request_id']
  if(shared/('socket-intent-'+token+'.json')).exists():result=read_command_status(shared,token,expected_socket_scope=scope)
  else:result=read_command_status(IPC,token) or {'outcome':'unavailable','terminal':False,'request_id':args['request_id'],'retry':False,'next_action':'No exact request or response is visible. This does not establish owner death; inspect retained owner receipts before any replay.'}
 else:result=call(args)
 print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__':main()

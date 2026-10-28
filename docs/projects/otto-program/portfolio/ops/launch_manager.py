import subprocess, json, os, time, sys
_rec = os.path.expanduser('~/Developer/otto-program/ops/manager-session.json')
try:
    _old = json.load(open(_rec)).get('pid')
except (OSError, ValueError):
    _old = None
if _old and subprocess.run(['ps', '-p', str(_old)], capture_output=True).returncode == 0:
    sys.exit(f"the recorded manager (pid {_old}) is alive; stop it first or resume it; nothing launched")
root=os.path.expanduser('~/Developer/otto-program'); import uuid; sid=str(uuid.uuid4())  # a fresh manager session each launch; resume_manager.py continues one
goal=("/goal First read ops/manager-handoff.md and every '## Orchestrator' section of ops/requests.md written after it. Then work strictly by ops/manager-bootstrap-brief.md (read it first, then PLAN.md, RUNBOOK.md and projects/program/tasklist.md). "
 "The goal is met when (a) every wave 0 and wave 1 task in projects/program/tasklist.md (SKEL0 included) has landed on canon/main as a 'Land <TASK>' merge, is in ops/LANDED-PRIOR.txt or is marked skipped, "
 "and you have requested CUTOVER in ops/requests.md (your scope ends there; stage runs, reviews and CUTOVER are the orchestrator's); "
 "OR (b) no worker is running and none can be launched, and you are waiting only on open requests in ops/requests.md (a stage review, an answer, CUTOVER); "
 "OR (c) your context is long and you have written ops/manager-handoff.md.")
argv=['claude','-p','--model','claude-haiku-5-5','--effort','high','--session-id',sid,'--max-budget-usd','25',
 '--permission-mode','acceptEdits','--allowedTools','Bash Read Edit Write Glob Grep','--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
 '--add-dir',os.path.expanduser('~/Developer/otto-claude-host'),'--add-dir',os.path.expanduser('~/Developer/astrid-video/astrid-local'),
 '--output-format','stream-json','--verbose',goal]
log=open(os.path.join(root,'ops/manager.log'),'ab')
p=subprocess.Popen(argv,cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
json.dump({'session_id':sid,'pid':p.pid,'started':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'model':'claude-haiku-5-5','effort':'high','budget_usd':25,'goal':goal},open(os.path.join(root,'ops/manager-session.json'),'w'),indent=1)
print(p.pid, sid)

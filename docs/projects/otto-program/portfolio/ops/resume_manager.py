# Resume the manager's SAME session, detached, with a fresh /goal whose first step is
# to re-read the brief and the orchestrator's sections in ops/requests.md.
#   python3 ops/resume_manager.py
# Run only when the manager process has exited (or after stopping it between turns).
import subprocess, json, os, time
root = os.path.expanduser('~/Developer/otto-program')
state = json.load(open(os.path.join(root, 'ops/manager-session.json')))
sid = state['session_id']
base = state['goal'].removeprefix('/goal ').removeprefix('Work strictly by')
goal = ("/goal First re-read ops/manager-bootstrap-brief.md (its loop now has a step 0) and every '## Orchestrator' "
        "section of ops/requests.md, and apply them; then check on the running workers (ops/workers.json). "
        "Work strictly by" + base)
argv = ['claude', '-p', '--resume', sid, '--model', 'claude-haiku-5-5', '--effort', 'high',
        '--max-budget-usd', '25', '--permission-mode', 'acceptEdits', '--allowedTools', 'Bash Read Edit Write Glob Grep',
        '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
        '--add-dir', os.path.expanduser('~/Developer/otto-claude-host'),
        '--add-dir', os.path.expanduser('~/Developer/astrid-video/astrid-local'),
        '--output-format', 'stream-json', '--verbose', goal]
log = open(os.path.join(root, 'ops/manager.log'), 'ab')
p = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
state.update(pid=p.pid, resumed=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), goal=goal)
json.dump(state, open(os.path.join(root, 'ops/manager-session.json'), 'w'), indent=1)
print(p.pid, sid)

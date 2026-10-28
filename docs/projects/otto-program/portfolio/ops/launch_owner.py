"""Start the shared owner exactly as ExecutionHost.supervise_owner_service's spawn does (execution_host.py:1711-1725),
after the 14 Oct incident left its supervision policy exhausted. Records the launch the way the waiter's on_spawn does."""
import json, os, stat, subprocess, time, sys
from datetime import datetime, timezone
from pathlib import Path
# Guard (ASTRA0, 15 Oct): there is no --preflight; any argument used to be ignored and the owner launched.
if sys.argv[1:]:
    sys.exit("launch_owner.py takes no arguments (there is no --preflight); nothing launched")
_status = Path(os.path.expanduser('~/.otto-clients/claude-code/lanes/claude-code/status.json'))
try:
    _s = json.loads(_status.read_text())
    _age = (datetime.now(timezone.utc) - datetime.fromisoformat(_s['heartbeat_at'])).total_seconds()
    _pid = int((_s.get('holder') or {}).get('pid') or 0)
    _alive = _pid > 0 and subprocess.run(['ps', '-p', str(_pid)], capture_output=True).returncode == 0
except Exception as e:
    sys.exit(f"cannot read the owner's status ({e}); nothing launched")
if _alive or _age < 120:
    sys.exit(f"an owner is alive (holder pid {_pid}, heartbeat {_age:.0f} s ago); nothing launched")
I=Path(os.path.expanduser('~/.codex/owner-services/otto-onboarding-20261010/shared-launch-intent-task-enable-adf995-20261014-maintenance-3505e8c81e462f0a-successor-4f725829de68-1.json'))
intent=json.loads(I.read_text())
fifo, log = Path(intent['fifo']), Path(intent['log'])
m=fifo.lstat()
assert stat.S_ISFIFO(m.st_mode) and m.st_uid==os.getuid() and stat.S_IMODE(m.st_mode)==0o600, 'fifo'
fd=os.open(fifo, os.O_RDWR|os.O_NOFOLLOW); held=os.fstat(fd); assert (held.st_dev,held.st_ino)==(m.st_dev,m.st_ino)
out=os.open(log, os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW, 0o600)
info=os.fstat(out); assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600, 'log'
p=subprocess.Popen(intent['argv'], cwd=intent['cwd'], stdin=fd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
os.close(fd); os.close(out)
record={**intent['metadata'],'pid':p.pid,'monitor_pid':None,'session_id':os.getsid(p.pid),'process_group_id':os.getpgid(p.pid),'detached':True,
 'stdin_transport':'private root-owned FIFO passed as actual stdin','supervision_path':intent['supervision_path'],'log':intent['log'],
 'launched_by':'claude-code manual restart, 15 Oct 2026, after the 14 Oct --help incident (supervision policy exhausted; no supervisor)','launched_at':time.time()}
rp=Path(intent['record'])
if rp.exists(): os.replace(rp, rp.with_name('supervised-prior-owner-'+str(time.time_ns())+'.json'))
tmp=rp.with_name('.'+rp.name+'.write'); fdw=os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
with os.fdopen(fdw,'w') as s: json.dump(record,s,sort_keys=True); s.write('\n'); s.flush(); os.fsync(s.fileno())
os.replace(tmp, rp)
print(json.dumps({'pid':p.pid,'record':str(rp)}))

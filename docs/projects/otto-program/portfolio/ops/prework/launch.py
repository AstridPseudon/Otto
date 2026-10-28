#!/usr/bin/env python3
"""Run the audit/plan jobs through codex exec, at most MAX at once, only while memory allows.
Outputs: <NAME>.md (the answer), <NAME>.log (codex stderr/stdout); one line per start/finish in launcher.log."""
import json, os, subprocess, sys, time, re, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 6
MIN_FREE = 25  # percent free memory required to start another job
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def log(msg):
    with open(os.path.join(HERE, 'launcher.log'), 'a') as f: f.write(f'{now()} {msg}\n')
def free_pct():
    try:
        out = subprocess.run(['memory_pressure'], capture_output=True, text=True, timeout=60).stdout
        return int(re.search(r'free percentage: (\d+)%', out).group(1))
    except Exception:
        return 100
jobs = json.load(open(os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2 else 'jobs.json')))
pre = {k: open(os.path.join(HERE, f'preamble-{k}.md')).read() for k in ('audit', 'plan')}
pending = [j for j in jobs if not os.path.exists(os.path.join(HERE, j['name'] + '.md'))]
running = {}
while pending or running:
    for name, p in list(running.items()):
        rc = p.poll()
        if rc is not None:
            del running[name]
            out = os.path.join(HERE, name + '.md')
            size = os.path.getsize(out) if os.path.exists(out) else 0
            log(f'done {name} rc={rc} answer_bytes={size}')
    while pending and len(running) < MAX:
        free = free_pct()
        if free < MIN_FREE:
            log(f'waiting: memory free {free}% < {MIN_FREE}%')
            break
        j = pending.pop(0)
        brief = (pre['audit'] if j['kind'] in ('audit', 'diag') else pre['plan']) + '\n' + j['q'] + '\n'
        open(os.path.join(HERE, j['name'] + '.brief.md'), 'w').write(brief)
        cmd = ['codex', 'exec', '-m', 'gpt-6-sol', '-c', 'model_reasoning_effort="xhigh"',
               '--skip-git-repo-check', '-C', '${TRANSFER_ROOT}/source/otto', '-s', 'read-only',
               '-o', os.path.join(HERE, j['name'] + '.md'), brief]
        lf = open(os.path.join(HERE, j['name'] + '.log'), 'w')
        running[j['name']] = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT)
        log(f'start {j["name"]} pid={running[j["name"]].pid} (memory free {free}%)')
    time.sleep(20)
log('all jobs finished')

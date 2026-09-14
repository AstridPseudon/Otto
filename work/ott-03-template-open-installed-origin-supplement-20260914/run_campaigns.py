from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

repo = Path(sys.argv[1]).resolve()
out = Path(__file__).resolve().parent
venv = Path('/tmp/ott03-template-open.o3HzxD/venv/bin/python')
workdir = Path('/tmp/ott03-template-open.o3HzxD/installed-origin-campaign')
workdir.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env.pop('PYTHONPATH', None)
env.pop('PYTHONHOME', None)
env['PYTHONDONTWRITEBYTECODE'] = '1'
cmds = [
    ('installed-full-47-same-process', [str(venv), str(out/'run_pytest_same_process.py'), 'full', str(repo)]),
    ('installed-focused-18-same-process', [str(venv), str(out/'run_pytest_same_process.py'), 'focused', str(repo)]),
    ('installed-selected-observation-same-process', [str(venv), str(out/'run_observation_same_process.py'), str(repo/'work/ott-03-template-open-receipt-20260914-v3/selected_create_open_observation.py')]),
]
receipts = []
for label, command in cmds:
    start = datetime.now(timezone.utc)
    proc = subprocess.run(command, cwd=workdir, env=env, text=True, capture_output=True)
    end = datetime.now(timezone.utc)
    output_path = out / f'{label}.txt'
    output_path.write_text(proc.stdout + (('\n[stderr]\n' + proc.stderr) if proc.stderr else ''))
    receipts.append({
        'label': label,
        'command': command,
        'cwd': str(workdir),
        'environment': {'PYTHONPATH': 'unset', 'PYTHONHOME': 'unset', 'PYTHONDONTWRITEBYTECODE': '1'},
        'pid': proc.pid if hasattr(proc, 'pid') else None,
        'return_code': proc.returncode,
        'start': start.isoformat(),
        'end': end.isoformat(),
        'output': str(output_path.relative_to(repo)),
        'stdout_tail': proc.stdout[-1000:],
        'stderr_tail': proc.stderr[-1000:],
    })
(out/'same-process-receipts.json').write_text(json.dumps(receipts, indent=2, sort_keys=True) + '\n')
print(json.dumps(receipts, indent=2, sort_keys=True))
if any(item['return_code'] != 0 for item in receipts):
    raise SystemExit(1)

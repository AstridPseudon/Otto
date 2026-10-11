"""Supervise the installed shared-owner wrapper; never compose a second Store."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
from typing import Any, Mapping


def installed_argv(config: Mapping[str, Any], *, requested_limit: int) -> list[str]:
    selected = config.get('owner_composition') or {}
    if (selected.get('kind') != 'shared-project-services' or requested_limit != config.get('max_active_manager_turns')
            or requested_limit != 3):
        raise PermissionError('installed shared-owner composition and exact adopted limit required')
    argv = selected.get('argv')
    pins = selected.get('file_sha256')
    if (not isinstance(argv, list) or len(argv) < 2 or any(not isinstance(x, str) or not x for x in argv)
            or not isinstance(pins, Mapping) or not pins):
        raise ValueError('exact installed wrapper argv and immutable file pins required')
    for name, digest in pins.items():
        path = Path(name)
        if not path.is_absolute() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise PermissionError('installed supervisor input changed: ' + name)
    if not Path(argv[0]).is_absolute() or not Path(argv[1]).is_absolute():
        raise PermissionError('installed supervisor interpreter and wrapper must be absolute')
    return list(argv)


def run_installed_supervisor(config: Mapping[str, Any], *, requested_limit: int) -> dict[str, Any]:
    argv = installed_argv(config, requested_limit=requested_limit)
    # The existing wrapper validates owner PID/start, original intent/source,
    # exact custody and stop markers; its retained finite restart count remains
    # authoritative. The CLI never opens Store or starts another owner itself.
    completed = subprocess.run(argv, cwd=config['owner_composition']['cwd'], check=False)
    return {'outcome': 'closed' if completed.returncode == 0 else 'supervisor-failed',
            'supervisor_exit_code': completed.returncode, 'shared_project_owner': True,
            'store_opened_by_cli': False, 'provider_called_by_cli': False}


def launchd_definition(config: Mapping[str, Any], *, label: str) -> bytes:
    if not isinstance(label, str) or not label.startswith('org.otto.') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in label):
        raise ValueError('exact Otto launchd label required')
    argv = installed_argv(config, requested_limit=config.get('max_active_manager_turns'))
    selected = config['owner_composition']
    # Retry only an unsuccessful supervisor exit. Its retained intent/exit
    # ledger owns the finite child restarts; explicit pause, stop and exhausted
    # policies exit successfully and cannot reset that count.
    return plistlib.dumps({'Label': label, 'ProgramArguments': argv,
        'WorkingDirectory': selected['cwd'], 'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
        'StandardOutPath': selected['stdout'], 'StandardErrorPath': selected['stderr'],
        'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1'}}, sort_keys=True)


def write_launchd_definition(config: Mapping[str, Any], *, label: str, path: Path) -> Path:
    data = launchd_definition(config, label=label)
    path = Path(path)
    if path.is_symlink():
        raise PermissionError('launchd definition cannot replace a symbolic link')
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    return path

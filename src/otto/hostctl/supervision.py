"""Supervise the installed shared-owner wrapper; never compose a second Store."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
from typing import Any, Mapping


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def _private_create(path: Path, value: Mapping[str, Any]) -> None:
    """Publish an immutable prepared receipt, never a replaceable policy."""
    data = (json.dumps(value, sort_keys=True) + '\n').encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        if path.is_symlink() or json.loads(path.read_text()) != value:
            raise PermissionError('maintenance receipt already has different input')
        return
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def prepare_planned_maintenance(*, old_path: Path, expected_policy_sha256: str,
        expected_exits: Mapping[str, str], new_path: Path, source_identity: Mapping[str, Any],
        request_key: str, custody: Mapping[str, Any]) -> Mapping[str, Any]:
    """One owner-authorized source cutover after an exact ordinary closure.

    No process or Store is opened here. The installer supplies fresh, verified
    closed custody; filesystem permissions are not a substitute for that proof.
    Old policy/exits remain immutable. The prepared successor is seeded with
    the remaining crash allowance, so its initial planned launch is distinct
    from automatic crash retries. Ordinary supervise(resume=True) stays strict.
    """
    old_path, new_path = Path(old_path), Path(new_path)
    if (old_path == new_path or old_path.parent != new_path.parent or old_path.is_symlink()
            or new_path.is_symlink() or not request_key or len(request_key) > 200):
        raise PermissionError('exact same-home maintenance lineage/key required')
    if (custody.get('ordinary_exit_status') != 0 or custody.get('store_closed') is not True
            or custody.get('owner_alive') is not False or custody.get('supervisor_alive') is not False
            or custody.get('native_active_or_uncertain') != 0 or custody.get('holds') != []
            or custody.get('in_flight') != []):
        raise PermissionError('planned maintenance requires verified closed, effect-free custody')
    raw = old_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_policy_sha256:
        raise PermissionError('prior supervision policy CAS differs')
    old = json.loads(raw)
    keys = ('argv', 'source_identity', 'max_restarts', 'restart_delay', 'max_restart_delay')
    policy = {k: old[k] for k in keys}
    if old.get('schema') != 'otto.owner-host-supervision.v2' or old.get('policy_sha256') != _digest(policy):
        raise PermissionError('prior supervision policy is not exact v2')
    paths = sorted(old_path.parent.glob(old_path.name + '.exit-*.json'))
    measured = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if measured != dict(expected_exits) or not paths:
        raise PermissionError('exact completed supervision exit tail required')
    exits = [json.loads(p.read_text()) for p in paths]
    exits.sort(key=lambda x: x.get('index', -1))
    if any(e.get('schema') != 'otto.owner-host-exit.v2' or e.get('policy_sha256') != old['policy_sha256']
           or e.get('source_identity') != old['source_identity'] or e.get('index') != i
           or type(e.get('exit_status')) is not int for i, e in enumerate(exits)):
        raise PermissionError('uncertain, foreign or noncontiguous prior exit tail')
    if exits[-1]['exit_status'] != 0:
        raise PermissionError('maintenance cannot reinterpret a failed/UNKNOWN exit as an ordinary stop')
    consumed = max(0, len(exits) - 1)
    if consumed > old['max_restarts']:
        raise PermissionError('prior automatic restart allowance exhausted')
    if not isinstance(source_identity, Mapping) or not source_identity:
        raise ValueError('new exact compatible source identity required')
    successor = {**policy, 'source_identity': dict(source_identity),
                 'max_restarts': old['max_restarts'] - consumed}
    transition = {'schema': 'otto.owner-planned-maintenance.v1', 'request_key': request_key,
        'prior_policy': str(old_path), 'prior_policy_sha256': expected_policy_sha256,
        'prior_exits': measured, 'successor_policy': str(new_path),
        'successor_policy_sha256': _digest(successor), 'source_identity': dict(source_identity),
        'automatic_restart_budget': {'original_max': old.get('planned_maintenance', {}).get(
            'automatic_restart_budget', {}).get('original_max', old['max_restarts']),
            'previously_consumed': old.get('planned_maintenance', {}).get(
                'automatic_restart_budget', {}).get('previously_consumed', 0) + consumed,
            'remaining': successor['max_restarts']}, 'custody': dict(custody),
        'provider_called': False, 'store_opened': False}
    # One successor per prior ledger; replay of the exact preparation is safe
    # even if the process stopped between publishing this record and its seed.
    _private_create(old_path.with_name(old_path.name + '.maintenance.json'), transition)
    _private_create(new_path, {'schema': 'otto.owner-host-supervision.v2', **successor,
        'policy_sha256': _digest(successor), 'planned_maintenance': transition})
    return transition


def maintenance_restart_limit(intent: Mapping[str, Any]) -> int:
    """Read a prepared successor; never issue a new budget from an intent."""
    path = Path(intent['supervision_path'])
    require_unsuperseded_preparation(path)
    if not path.exists():
        if intent.get('metadata', {}).get('planned_maintenance'):
            raise PermissionError('planned maintenance policy was not prepared')
        return 2  # Existing installed wrapper's declared original policy.
    policy = json.loads(path.read_text())
    transition = policy.get('planned_maintenance')
    if not transition:
        return 2
    keys = ('argv', 'source_identity', 'max_restarts', 'restart_delay', 'max_restart_delay')
    if (policy['argv'] != intent['argv'] or policy['source_identity'] != intent['metadata']
            or policy['policy_sha256'] != _digest({k: policy[k] for k in keys})
            or transition['successor_policy'] != str(path)
            or transition['successor_policy_sha256'] != policy['policy_sha256']
            or transition['automatic_restart_budget']['remaining'] != policy['max_restarts']):
        raise PermissionError('prepared maintenance policy differs from installed intent')
    validate_unused_supersession(transition)
    return policy['max_restarts']


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

# BEGIN maintained unused preparation supersession
# Closed unused-preparation supersession. Uses the same retained supervision
# ledger; no new budget, process, Store or dispatcher is created.
def _preparation_lock(path):
    import contextlib, fcntl
    @contextlib.contextmanager
    def held():
        gate=Path(str(path)+'.preparation-lock')
        fd=os.open(gate,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX);yield
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
    return held()

def _superseded_marker(path):return Path(str(path)+'.supersession.json')
def _launch_claim_path(path,index):return Path(str(path)+'.launch-'+str(index)+'.json')

def require_unsuperseded_preparation(path):
    if _superseded_marker(Path(path)).exists():raise PermissionError('unused supervision preparation was superseded; original policy is retained, not executable')

def claim_supervision_launch(path,*,index,policy_sha256):
    path=Path(path)
    with _preparation_lock(path):
        require_unsuperseded_preparation(path)
        claim=_launch_claim_path(path,index)
        if claim.exists():return False
        _private_create(claim,{'schema':'otto.owner-supervision-launch-claim.v1','index':index,'policy_sha256':policy_sha256})
        return True

def _original_maintenance_valid(transition):
    prior=Path(transition['prior_policy'])
    if (hashlib.sha256(prior.read_bytes()).hexdigest()!=transition['prior_policy_sha256']
        or json.loads(Path(str(prior)+'.maintenance.json').read_text())!=transition
        or {p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in prior.parent.glob(prior.name+'.exit-*.json')}!=transition['prior_exits']):
        raise PermissionError('original maintenance ancestry changed')

def validate_unused_supersession(transition,*,depth=0):
    if depth>8:raise PermissionError('unused supersession ancestry exceeds finite bound')
    source=transition.get('supersession')
    if source is None:return _original_maintenance_valid(transition)
    old_path=Path(source['policy_path']);old_raw=old_path.read_bytes();old=json.loads(old_raw)
    marker=json.loads(_superseded_marker(old_path).read_text())
    if (hashlib.sha256(old_raw).hexdigest()!=source['policy_sha256']or marker.get('transition')!=transition
        or list(old_path.parent.glob(old_path.name+'.exit-*.json'))or list(old_path.parent.glob(old_path.name+'.launch-*.json'))
        or transition['automatic_restart_budget']!=old['planned_maintenance']['automatic_restart_budget']):
        raise PermissionError('unused supersession ancestry/launch proof changed')
    return validate_unused_supersession(old['planned_maintenance'],depth=depth+1)

def supersede_unlaunched_preparation(*,old_path,expected_policy_sha256,new_path,source_identity,request_key,custody,unused_evidence):
    old_path,new_path=Path(old_path),Path(new_path)
    if old_path==new_path or old_path.parent!=new_path.parent or old_path.is_symlink()or new_path.is_symlink()or not request_key or len(request_key)>200:
        raise PermissionError('exact same-home unused preparation/key required')
    if (custody.get('ordinary_exit_status')!=0 or custody.get('store_closed')is not True or custody.get('owner_alive')is not False
        or custody.get('supervisor_alive')is not False or custody.get('native_active_or_uncertain')!=0 or custody.get('holds')!=[]or custody.get('in_flight')!=[]):
        raise PermissionError('unused supersession requires actual closed, effect-free custody')
    raw=old_path.read_bytes();old=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=expected_policy_sha256:raise PermissionError('unused preparation CAS differs')
    keys=('argv','source_identity','max_restarts','restart_delay','max_restart_delay');policy={k:old[k]for k in keys}
    original=old.get('planned_maintenance')
    if old.get('schema')!='otto.owner-host-supervision.v2' or old.get('policy_sha256')!=_digest(policy)or not isinstance(original,dict):
        raise PermissionError('only an exact planned unused seed may be superseded')
    validate_unused_supersession(original)
    # Absence of exit receipts alone is not no-launch proof. Require the exact
    # independently retained last owner launch to still be the exited parent.
    launch_path=Path(unused_evidence['owner_launch_path']);launch_raw=launch_path.read_bytes();launch=json.loads(launch_raw)
    prior=json.loads(Path(original['prior_policy']).read_text())
    if (hashlib.sha256(launch_raw).hexdigest()!=unused_evidence['owner_launch_sha256']
        or launch.get('supervision_path')!=original['prior_policy']
        or launch.get('source_commit')!=prior['source_identity'].get('source_commit')
        or launch.get('pid')!=custody.get('owner_pid')or launch.get('monitor_pid')!=custody.get('supervisor_pid')
        or unused_evidence.get('exclusive_closed_operator')is not True):
        raise PermissionError('no-launch custody attestation is missing, stale or uncertain')
    proof_path=Path(unused_evidence['root_custody_path']);proof_raw=proof_path.read_bytes();proof=json.loads(proof_raw)
    if (hashlib.sha256(proof_raw).hexdigest()!=unused_evidence['root_custody_sha256']
        or proof.get('schema')!='otto.root-never-launched-preparation-custody.v1'
        or proof.get('original_482_policy_path')!=str(old_path)
        or proof.get('original_482_policy_sha256')!=expected_policy_sha256
        or proof.get('original_e921_owner_pid')!=custody['owner_pid']
        or proof.get('original_e921_supervisor_pid')!=custody['supervisor_pid']
        or proof.get('original_e921_processes_dead')is not True
        or proof.get('launchd_label_absent')is not True
        or proof.get('matching_live_owner_or_supervisor_processes')!=[]
        or proof.get('unused_482_exit_files')!=[]
        or proof.get('root_exclusive_custody')is not True
        or proof.get('current_config_still_selects_original_482_intent')is not True
        or not proof.get('root_operator_attestation')
        or proof.get('store_closed')is not True or proof.get('native_active_or_uncertain')!=0 or proof.get('holds')!=[]):
        raise PermissionError('exact retained root no-launch proof differs')
    successor={**policy,'source_identity':dict(source_identity)}
    transition={**original,'request_key':request_key,'successor_policy':str(new_path),'successor_policy_sha256':_digest(successor),
        'source_identity':dict(source_identity),'custody':dict(custody),
        'supersession':{'policy_path':str(old_path),'policy_sha256':expected_policy_sha256,'unused_evidence':dict(unused_evidence)}}
    marker={'schema':'otto.owner-unused-maintenance-supersession.v1','transition':transition}
    with _preparation_lock(old_path):
        if list(old_path.parent.glob(old_path.name+'.exit-*.json'))or list(old_path.parent.glob(old_path.name+'.launch-*.json')):
            raise PermissionError('started or UNKNOWN preparation cannot be superseded')
        # Durable disable precedes seed publication. Exact replay after a lost
        # response can publish the same new seed; no fork can replace this edge.
        _private_create(_superseded_marker(old_path),marker)
        _private_create(new_path,{'schema':'otto.owner-host-supervision.v2',**successor,'policy_sha256':_digest(successor),'planned_maintenance':transition})
    return transition

# END maintained unused preparation supersession

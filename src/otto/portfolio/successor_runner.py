"""Frozen receiving CLI for the existing, owner-admitted one-use successor.

Authority/configuration is data, never executable callbacks. The successor API
alone owns its deterministic intent and result records; this wrapper never resets
or replaces them. Construction of the existing reader/adapter is inert.
"""
from __future__ import annotations
import argparse
import importlib
import json
from pathlib import Path
import sys
import sysconfig

from .attention_binding import _digest, _need
from .operator import ProjectOperator, load_config
from .successor_entry import _pinned, _proof, _exclusive, preflight_successor, invoke_successor_once

SCHEMA = 'otto.same-occurrence-successor-runner.v1'
FILES = {'admission', 'source_admission', 'manager_disposition', 'd95_report',
         'd95_receipt', 'd96_receipt', 'd97_receipt', 'd97_integration_receipt'}
MODULES = {'otto.portfolio.successor_runner', 'otto.portfolio.successor_entry',
           'otto.agents.codex_host_reader', 'otto.agents.herzchen_adapter',
           'otto.agents.source_verification'}


def _named_hash(values, pin):
    return values.get(Path(pin['path']).name) == pin['sha256']


def load_envelope(path, expected_sha256):
    """Validate frozen files and installed origins, without opening any Store."""
    envelope = json.loads(_pinned({'path':str(path), 'sha256':expected_sha256}))
    _need(envelope.get('schema') == SCHEMA and set(envelope) == {
        'schema', 'files', 'module_origins', 'admission_sha256'}, 'runner envelope schema mismatch')
    pins = envelope['files']
    _need(set(pins) == FILES, 'complete runner authority files required')
    raw = {key:_pinned(pin) for key,pin in pins.items()}
    data = {key:json.loads(value) for key,value in raw.items() if key != 'd95_report'}
    origins = envelope['module_origins']
    _need(set(origins) == MODULES, 'complete runner installed origins required')
    site = Path(sysconfig.get_paths()['purelib']).resolve()
    for name,pin in origins.items():
        actual = Path(importlib.import_module(name).__file__).resolve()
        expected = site.joinpath(*name.split('.')).with_suffix('.py')
        _need(actual == expected and str(actual) == pin['path'], 'runner source fallback/origin mismatch: '+name)
        _pinned(pin)
    admission = data['admission']
    _need(_digest(admission) == envelope['admission_sha256'], 'original admission digest mismatch')
    original,target = _proof(admission, envelope['admission_sha256'])
    binding = admission['current_binding']; scope = binding['scope']; packet = original['packet']
    _need(str(Path(sys.executable).absolute()) == binding['python'], 'runner interpreter differs from admitted interpreter')
    _need(_digest(data['source_admission']) == packet['source_manifest_sha256'] == binding['source_manifest_sha256'], 'runner source admission changed')
    manager = data['manager_disposition']
    _need(manager.get('schema') == 'otto.o16.same-occurrence-manager-disposition.v1' and manager.get('decision') == 'one_same_occurrence_successor_conditionally_authorized', 'manager has not admitted this successor')
    selected = manager['scope']
    for field in ('project_ref','task_ref','assignment_ref','mandate_ref'):
        ref = scope[field]
        _need(selected.get(field) == ref['id']+'@'+ref['revision'], 'manager scope differs: '+field)
    brief = binding['published_brief_ref']
    _need(selected.get('brief_ref') == brief['id']+'@'+brief['revision'], 'manager brief differs')
    for field in ('generation','schedule_id','logical_request_key'):
        _need(selected.get(field) == scope[field], 'manager occurrence differs: '+field)
    _need(selected.get('due_record_version') == 1 and selected.get('due_record_sha256') == admission['due_sha256'], 'manager DueRecord differs')
    predecessor = manager['predecessor']; old = admission['predecessor']
    for field,key in [('packet_sha256','packet'),('runner_sha256','runner'),('intent_sha256','intent'),('uncertain_sha256','uncertain'),('reconciliation_report_sha256','reconciliation_report'),('reconciliation_receipt_sha256','reconciliation'),('reconciliation_observation_sha256','observation')]:
        _need(predecessor.get(field) == old[key]['sha256'], 'manager predecessor differs: '+field)
    _need(predecessor.get('packet_digest') == packet['invocation']['packet_digest'] and predecessor.get('no_reset_or_mutation') is True, 'manager predecessor custody differs')
    observed = predecessor['observed']
    _need(observed.get('provider_invoked') is False and all(observed.get(k) is None for k in ('claim','gateway_attempt','native_session_id')) and observed.get('due_state') == 'ready' and observed.get('due_version') == 1, 'manager observation includes prior effect')
    repair = manager['repair_and_successor_admission']
    for field,key in [('d96_receipt_sha256','d96_receipt'),('d97_candidate_receipt_sha256','d97_receipt'),('d97_integration_receipt_sha256','d97_integration_receipt')]:
        _need(repair.get(field) == pins[key]['sha256'], 'manager repair receipt differs: '+field)
    _need(repair.get('successor_admission_sha256') == envelope['admission_sha256'] and repair.get('current_binding_sha256') == _digest(binding) and repair.get('preflight_status') == 'PASS_NON_DISPATCH' and repair.get('successor_intent_created') is False, 'manager receiving preflight differs')
    named_target = Path(repair['successor_intent_path'])
    _need((named_target == target) if named_target.is_absolute() else tuple(target.parts[-len(named_target.parts):]) == named_target.parts, 'manager successor path differs')
    limits = manager['execution_limits']
    _need(limits.get('successor_invocations_max') == 1 and all(limits.get(k) is False for k in ('new_task_or_assignment','new_schedule_or_occurrence','automatic_retry')), 'manager one-use limits differ')
    d95 = data['d95_receipt']
    _need(d95.get('schema') == 'otto.advice.D95.pre-dispatch-queue-update.v1' and d95.get('report',{}).get('sha256') == pins['d95_report']['sha256'], 'D95 advice receipt mismatch')
    for table,keys in [('protected_unchanged_sha256',('binding','custody','packet','intent','uncertain')),('inputs_sha256',('reconciliation','reconciliation_report','observation'))]:
        hashes = {Path(k).name:v for k,v in d95.get(table,{}).items()}
        _need(all(_named_hash(hashes,old[key]) for key in keys), 'D95 predecessor reconciliation chain mismatch')
    _need(data['d96_receipt'].get('status') == 'PASS_ISOLATED_REPAIR' and data['d97_receipt'].get('status') == 'PASS_DISPOSABLE_INSTALLED', 'repair receipt not passing')
    integrated = data['d97_integration_receipt']
    _need(integrated.get('status') == 'PASS_NON_DISPATCH' and integrated.get('admission_sha256') == envelope['admission_sha256'] and integrated.get('current_binding_sha256') == _digest(binding) and integrated.get('due_sha256') == admission['due_sha256'] and integrated.get('due_version') == 1 and integrated.get('due_state') == 'ready' and integrated.get('provider_invoked') is False and integrated.get('successor_intent_created') is False and all(integrated.get(k) is None for k in ('claim','native_id','result')), 'integration preflight receipt mismatch/effect')
    _need(_named_hash(integrated['artifacts_sha256'], pins['admission']), 'integration did not admit this exact file')
    _need(integrated['d97_candidate']['receipt_sha256'] == pins['d97_receipt']['sha256'], 'integration candidate differs')
    # Extra immutable receiving evidence changes only the API admission digest,
    # which is persisted in its one-use intent. Original admission bytes survive.
    bound = {**admission, 'runner_authority': {'envelope_path':str(path), 'envelope_sha256':expected_sha256,
                                            'original_admission_sha256':envelope['admission_sha256']}}
    return bound, data, target


def run(path, expected_sha256, *, invoke=False):
    admission,data,target = load_envelope(path, expected_sha256)
    binding = admission['current_binding']
    config = load_config(Path(binding['owner_config_path']), binding['owner_config_sha256'])
    returned = False
    try:
        with ProjectOperator(config, binding['owner_config_sha256']) as operator:
            if not invoke:
                return preflight_successor(operator, admission, expected_sha256=_digest(admission))
            from ..agents.codex_host_reader import CodexAppServerThreadReader
            from ..agents.herzchen_adapter import HerzchenCodexAdapter
            from ..agents.source_verification import SourceVerifierFactory
            packet = json.loads(_pinned(admission['predecessor']['packet'])); scope = binding['scope']
            reader = CodexAppServerThreadReader(launcher=packet['launcher'])
            adapter = HerzchenCodexAdapter(owner='worker',source=packet['source_run'],worktree=packet['worktree'],
                launcher=packet['launcher'],requested_model=scope['requested_model'],requested_reasoning=scope['requested_reasoning'],
                host_context_path=packet['host_context_path'],trusted_thread_reader=reader,require_host_context=True,
                source_verifier_factory=SourceVerifierFactory(data['source_admission']))
            # Revalidate authority files at the receiving boundary. The API
            # separately revalidates current Store scope and guarded CAS state.
            load_envelope(path, expected_sha256)
            _need(not target.exists() and not target.is_symlink(), 'successor intent already consumed')
            result = invoke_successor_once(operator, admission, expected_sha256=_digest(admission), adapter=adapter)
            returned = True
        return result  # Successful output is emitted only after owner close.
    except BaseException as exc:
        uncertain = target.with_suffix('.uncertain.json')
        if returned and target.exists() and not uncertain.exists() and not uncertain.is_symlink():
            _exclusive(uncertain, {'envelope_sha256':expected_sha256,'admission_sha256':_digest(admission),
                                  'exception_type':type(exc).__name__,'message':str(exc),'relaunch':False})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('check','invoke'))
    parser.add_argument('--envelope', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args(argv)
    result = run(args.envelope, args.sha256, invoke=args.operation == 'invoke')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

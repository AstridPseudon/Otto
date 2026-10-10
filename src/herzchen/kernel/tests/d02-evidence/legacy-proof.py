import datetime,hashlib,json,os,subprocess,tempfile,time
from pathlib import Path
from herzchen.contracts import ResourceRef,DomainContribution
from herzchen.kernel import Store,MigrationRequiredError
from herzchen.kernel.recovery import closed_owner_custody,restore_snapshot
from herzchen.kernel.migration import EventsMigration
from herzchen.kernel.schema import LEGACY_COMPOSITION,LEGACY_SCHEMA_FINGERPRINT,SCHEMA_REVISION,SCHEMA_FINGERPRINT
baseline=Path('/tmp/d02-baseline-u4mg1ujx');output=Path('/tmp/d02-final-verification')
started=datetime.datetime.now(datetime.timezone.utc).isoformat();tick=time.monotonic()
with tempfile.TemporaryDirectory(prefix='d02-real-legacy-') as temporary:
 root=Path(temporary)
 create="""
import json,sys
from pathlib import Path
from herzchen.contracts import ResourceRef,AuthenticatedActor
from herzchen.kernel import Store
from herzchen.kernel.recovery import create_snapshot
from herzchen.domains.work import WorkGraph,contributions
root=Path(sys.argv[1])
with Store.create(root/'owner.sqlite',authority='owner') as store:
 store.register_domain_handler(contributions(include_assignment_resources=True))
 graph=WorkGraph(store,actor=AuthenticatedActor('owner','host','credential'))
 project=graph.create_project(title='Real legacy',logical_request_key='project')
 task=graph.create_task(project,title='Retained',logical_request_key='task')
 snapshot=create_snapshot(store,root/'snapshot',source_identity=ResourceRef('owner','source','source','rev-1'),realm_identity=ResourceRef('owner','realm','realm','rev-1'))
 (root/'fixture.json').write_text(json.dumps({'domains':[d.to_dict() for d in store.registered_domains()],'receipt':store.get_receipt('task').to_dict(),'task':task.ref.to_dict()}))
print('baseline legacy writable admission and snapshot: PASS')
"""
 command=['/usr/bin/python3','-c',create,str(root)]
 first=subprocess.run(command,cwd=baseline,env={**os.environ,'PYTHONPATH':'src:tests'},text=True,capture_output=True)
 assert first.returncode==0,first.stderr
 fixture=json.loads((root/'fixture.json').read_text());domains=tuple(DomainContribution.from_dict(d) for d in fixture['domains'])
 with Store.open_readonly(root/'owner.sqlite',authority='owner',expected_domains=domains) as reader:
  assert reader.get_receipt('task').to_dict()==fixture['receipt']
 try:
  Store.open(root/'owner.sqlite',authority='owner',expected_domains=domains)
 except MigrationRequiredError:
  pass
 else:
  raise AssertionError('legacy writable open must require migration')
 manifest=json.loads((root/'snapshot'/'manifest.json').read_text())
 restored=restore_snapshot(root/'snapshot',root/'restored-legacy',expected_authority='owner',
  expected_source_identity=ResourceRef('owner','source','source','rev-1'),expected_realm_identity=ResourceRef('owner','realm','realm','rev-1'),
  expected_composition=LEGACY_COMPOSITION,expected_composition_digest=manifest['composition_digest'],expected_schema_fingerprint=LEGACY_SCHEMA_FINGERPRINT)
 with Store.open_readonly(root/'restored-legacy'/'database.sqlite3',authority='owner',expected_domains=domains) as reader:
  assert reader.get_receipt('task').to_dict()==fixture['receipt']
 with closed_owner_custody(root/'owner.sqlite',authority='owner',expected_domains=domains) as custody:
  with EventsMigration.begin(custody,candidate_path=root/'candidate.sqlite',backup_path=root/'backup.sqlite',journal_path=root/'migration.json',migration_id='real-legacy') as migration:
   while migration.step(limit=1)['phase']!='verified':
    pass
   receipt=migration.switch()
 with Store.open(root/'owner.sqlite',authority='owner',expected_domains=domains) as owner:
  assert owner.get_receipt('task').to_dict()==fixture['receipt']
 reject="""
import json,sys
from pathlib import Path
from herzchen.contracts import DomainContribution
from herzchen.kernel import Store,CompositionMismatchError
root=Path(sys.argv[1]);fixture=json.loads((root/'fixture.json').read_text())
try:
 Store.open(root/'owner.sqlite',authority='owner',expected_domains=tuple(DomainContribution.from_dict(d) for d in fixture['domains']))
except CompositionMismatchError:
 print('actual unchanged baseline binary rejects successor: PASS')
else:
 raise AssertionError('old binary admitted successor')
"""
 second=subprocess.run(['/usr/bin/python3','-c',reject,str(root)],cwd=baseline,env={**os.environ,'PYTHONPATH':'src:tests'},text=True,capture_output=True)
 assert second.returncode==0,second.stderr
 result={'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'duration_seconds':time.monotonic()-tick,'exit_status':0,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
  'baseline_source_commit':'f7bbb885e0dd093b83c83e9cf684f91d5d4e95e3',
  'baseline_path':str(baseline),'baseline_create_exit_status':first.returncode,'baseline_rejection_exit_status':second.returncode,
  'successor_schema':SCHEMA_REVISION,'successor_fingerprint':SCHEMA_FINGERPRINT,
  'checks':['actual old writable admission','actual old Recovery snapshot creation','new read-only legacy admission',
  'new legacy writable refusal','new Recovery restore of actual old snapshot','resumable successor migration',
  'exact task receipt equality','actual old binary successor rejection'], 'migration_switch_receipt':receipt,
  'stdout':first.stdout+second.stdout,'provider_calls':0,'domain_replays':0}
 (output/'legacy-proof.json').write_text(json.dumps(result,indent=2)+'\n')
 print(result['stdout']);print('Actual old/new composition and Recovery proof: PASS')

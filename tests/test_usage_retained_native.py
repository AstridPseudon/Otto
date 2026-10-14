"""Real DAT/Evidence, kernel lineage and Due producer amplification fixture."""
import json
import unittest
from unittest.mock import patch

from tests import test_evidence_projection as evidence_fixture
from tests.test_usage_capture import owner_capture
from otto.agents.retained_native import RetainedNativeBodies, SCHEMA
from otto.attention import due_record_contribution, issue_store_due_record_port, InputChangedError
from herzchen.contracts import ResourceRef
from herzchen.command_ports import close_consumer_facade


class RetainedNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = evidence_fixture.EvidenceProjectionTests()
        self.fixture.setUp()
        self.bodies = RetainedNativeBodies(self.fixture.handler, self.fixture.actor)

    def tearDown(self): self.fixture.tearDown()

    def test_source_pins_are_immutable_reused_and_resolve_exact_body(self):
        body = {'native': 'large-native-' * 1000, 'initializer': 'init', 'work': 'work'}
        scope = {'project_ref': self.fixture.project.to_dict()}
        a = self.bodies.retain(body, **scope); b = self.bodies.retain(body, **scope)
        self.assertEqual(a, b)
        self.assertEqual(a['schema'], SCHEMA)
        self.assertEqual(self.bodies.resolve(a), body)
        bad = dict(a, sha256='0' * 64)
        with self.assertRaises(ValueError): self.bodies.resolve(bad)

    def test_preexisting_inline_due_receipt_replays_exact_digest_without_retention(self):
        store = self.fixture.store
        store.register_domain_handler([due_record_contribution()])
        writer = store.domain_handler([due_record_contribution()])
        legacy = issue_store_due_record_port(writer, self.fixture.actor)
        modern = issue_store_due_record_port(writer, self.fixture.actor, native_bodies=self.bodies)
        _, memory = owner_capture()
        value = memory.read_due('schedule')
        value['assignment_ref'] = None
        value['project_ref'] = self.fixture.project.id
        value['host_evidence'] = {'raw_result': {'stdout': 'legacy' * 2000}}
        try:
            saved = legacy.save_due('schedule', value, request_id='old-inline', expected_version=0)
            digest = store.get_receipt('old-inline').request_digest
            with patch.object(self.bodies, 'retain', side_effect=AssertionError('legacy replay rewrote evidence')):
                replayed = modern.save_due('schedule', value, request_id='old-inline', expected_version=0)
            self.assertEqual(replayed['mutation_receipt']['replayed'], True)
            self.assertEqual(replayed['host_evidence'], saved['host_evidence'])
            self.assertEqual(store.get_receipt('old-inline').request_digest, digest)
            changed = dict(value, host_evidence={'raw_result': {'stdout': 'changed'}})
            with self.assertRaises(InputChangedError): modern.save_due('schedule', changed, request_id='old-inline', expected_version=0)
        finally:
            close_consumer_facade(legacy.transport)
            close_consumer_facade(modern.transport)

    def test_structured_native_bodies_are_pinned_and_legacy_shape_roundtrips(self):
        record = {'project_ref': self.fixture.project.to_dict(),
            'raw_result': {'events': [{'id': str(i), 'text': 'small-native-field'} for i in range(1000)]}}
        packed = self.bodies.pack_due(record)
        self.assertLess(len(json.dumps(packed)), 4096)
        self.assertEqual(self.bodies.unpack_due(packed), record)
        self.assertEqual(self.bodies.pack_due(packed), packed)

    def test_usage_source_is_retained_before_return_and_metadata_is_reference_only(self):
        from herzchen.usage.capture import UsageStream
        from tests.test_usage_capture import native
        capture, port = owner_capture()
        capture.native_bodies = self.bodies
        # Use an admitted project from this isolated Evidence owner fixture.
        capture.project_ref = self.fixture.project.to_dict()
        capture.task_ref = None
        self.fixture.store.put_identity(ResourceRef.from_dict(capture.assignment_ref), {'generation': 2}, version=1)
        value = port.read_due('schedule')
        value['project_ref'] = self.fixture.project.id
        value['target']['project_ref'] = self.fixture.project.to_dict()
        capture.expected_target = value['target']
        port.save_due('schedule', value, request_id='test-scope', expected_version=value['version'])
        stream = UsageStream('codex-host', phase='initializer',
            on_usage=lambda observation: capture.record_usage_observation('key', observation))
        events = native('codex-host', {'input_tokens': 0}, turn='init')
        for event in events: stream.feed(json.dumps(event))
        retained = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations'][0]
        pin = retained['provenance']['retained_source']
        self.assertEqual(json.loads(self.bodies.resolve(pin)), events[-1])
        self.assertEqual(retained['usage']['state'], 'zero')
        self.assertNotIn('native_source', retained)
        self.assertNotIn('inline_replacement', pin)
        self.assertEqual(stream.snapshot()['coverage']['callback_pending'], 0)
        self.assertEqual(stream.snapshot()['coverage']['raw_payload'], 'retained')
        self.assertEqual(stream.observations[0]['provenance']['retained_source'], pin)

    def test_large_body_transitions_duplicates_unknown_and_inventory_do_not_amplify(self):
        fixture = self.fixture
        store = fixture.store
        store.register_domain_handler([due_record_contribution()])
        writer = store.domain_handler([due_record_contribution()])
        port = issue_store_due_record_port(writer, fixture.actor, native_bodies=self.bodies)
        _, memory = owner_capture()
        value = memory.read_due('schedule')
        # Pure fixture Due has no operational assignment adoption/grants.
        value['assignment_ref'] = None
        value['host_evidence']['gateway_attempt'] = {
            'state': 'result', 'logical_request_key': 'key', 'request_fingerprint': 'fingerprint',
            'physical_session_id': 'session', 'result': {'outcome': 'unknown',
                'physical_session_id': 'session', 'observed_turn_id': 'work',
                'raw_result': {'initialization_envelope': {'stdout': 'initializer'},
                    'work_envelope': {'stdout': 'x' * 37_700_000},
                    'worker_content': ['x' * 37_700_000]}}}
        value['project_ref'] = fixture.project.id
        # Evidence owner namespace comes from project ref for this fixture.
        value['assignment_ref'] = {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'unadopted', 'revision': 'rev-1'}
        store.put_identity(ResourceRef.from_dict(value['assignment_ref']), {'generation': 2}, version=1)
        store.put_identity(ResourceRef.from_dict(value['target']['task_ref']), {'project_ref': fixture.project.to_dict()}, version=1)
        initial_pages = store.connection.execute('PRAGMA page_count').fetchone()[0]
        body_bytes = 37_700_000
        transitions = 5
        try:
            for i in range(transitions):
                value['version'] = i
                value['host_evidence']['phase'] = i
                if i == 0:
                    # Lose the reply after the provider body and canonical Due
                    # mutation commit. Inspect its exact receipt before replay.
                    def lose_reply():
                        # The public owner operation has fully committed before
                        # this outer transport loses its response.
                        port.save_due('schedule', value, request_id='transition-0', expected_version=0)
                        raise OSError('interrupted post-provider capture transport')
                    with self.assertRaises(OSError): lose_reply()
                    self.assertIsNotNone(store.get_receipt('transition-0'))
                else:
                    port.save_due('schedule', value, request_id='transition-' + str(i), expected_version=i)
                if i == 0:
                    duplicate = port.save_due('schedule', value, request_id='transition-0', expected_version=0)
                    self.assertEqual(duplicate['mutation_receipt']['replayed'], True)
                # Exact legacy-shape read hydrates only this selected occurrence.
                current = port.read_due('schedule')
                self.assertEqual(current['host_evidence']['gateway_attempt']['result']['outcome'], 'unknown')
                self.assertEqual(current['host_evidence']['gateway_attempt']['result']['raw_result']['work_envelope']['stdout'], 'x' * body_bytes)
            calls = []
            original = self.bodies.resolve
            self.bodies.resolve = lambda *args: calls.append(args) or (_ for _ in ()).throw(AssertionError('inventory hydrated raw native body'))
            rows = port.list_due({'project_ref': fixture.project.id})
            self.assertEqual(len(rows), 1)
            self.assertEqual(calls, [])
            self.bodies.resolve = original
            lineage_bytes = 0
            for i in range(transitions):
                receipt = store.get_receipt('transition-' + str(i))
                events = store.list_events(subjects=(receipt.result_ref,))
                self.assertTrue(set(receipt.event_ids).issubset({e.event_id for e in events}))
                lineage_bytes += sum(len(e.to_json().encode()) for e in events)
            self.assertLess(lineage_bytes, body_bytes // 10)
            pages = store.connection.execute('PRAGMA page_count').fetchone()[0] - initial_pages
            sqlite_bytes = pages * store.connection.execute('PRAGMA page_size').fetchone()[0]
            managed_bytes = sum(path.stat().st_size for path in fixture.handler.payload_root.rglob('*') if path.is_file())
            self.assertLess(managed_bytes, body_bytes + 65536)
            self.assertLess(sqlite_bytes + managed_bytes, body_bytes * 2)
            self.measurement = {'body_bytes': body_bytes, 'transitions': transitions,
                'body_times_transitions': body_bytes * transitions, 'managed_bytes': managed_bytes,
                'sqlite_page_growth_bytes': sqlite_bytes, 'kernel_lineage_bytes': lineage_bytes,
                'finish_inventory_body_reads': len(calls), 'original_outcome': 'unknown',
                'interrupted_post_provider_reply_reconciled': True}
            print('D02 persisted-byte measurement ' + json.dumps(self.measurement, sort_keys=True))
        finally: close_consumer_facade(port.transport)


class WrkRetainedBodyTests(unittest.TestCase):
    def test_real_wrk_append_keeps_identity_and_reads_new_refs_and_old_inline(self):
        from tests import test_execution_application as application_fixture
        from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
        from herzchen.evidence.model import load_evidence_pack
        from herzchen.packs.authoring import read_managed_pack
        from tests.test_evidence_projection import _v11_pack_hooks
        from otto.agents.gateway import HerzchenAttemptCapture
        f = application_fixture.ExecutionApplicationTests(); f.setUp()
        try:
            a, _, _ = f.role_handles('worker', 'worker-body', 'worker-session')
            register_evidence(f.store)
            root, discover, loader = _v11_pack_hooks()
            selected = load_evidence_pack(managed_pack=read_managed_pack('evidence',
                project_root=root.parents[3], discoverer=discover, loader=loader))
            handler = EvidenceCommandHandler(f.store, f.path.parent / 'native-evidence', pack=selected,
                adopted_pins=[item.to_dict() for item in selected.resources])
            bodies = RetainedNativeBodies(handler, f.actor)
            capture = HerzchenAttemptCapture(f.owner.assignments.command_port, f.store.consumer(), actor=f.actor, native_bodies=bodies)
            value = {'logical_request_key': 'new-ref-result', 'request_fingerprint': 'fingerprint',
                'project_ref': f.project.ref.to_dict(), 'task_ref': f.task.ref.to_dict(),
                'assignment_ref': a.ref.to_dict(), 'generation': 1, 'outcome': 'unknown',
                'physical_session_id': 'worker-session', 'raw_result': {'work_envelope': {'stdout': 'x' * 100000}}}
            self.assertEqual(capture.record(value), value)
            self.assertEqual(capture.record(value), value)
            stored = f.owner.assignments.command_port.list_observations(a.ref, kind='result')
            self.assertEqual(len(stored), 1)
            pin = stored[0].value['raw_result']['work_envelope']['stdout']
            self.assertEqual(pin['schema'], SCHEMA)
            self.assertEqual(capture.read('new-ref-result'), value)
            self.assertEqual(capture.read_assignment(a.ref.to_dict(), 1), value)
            # Old inline bodies retain their exact interpretation.
            old = {**value, 'logical_request_key': 'old-inline-result', 'raw_result': {'stdout': 'old'}}
            legacy = HerzchenAttemptCapture(f.owner.assignments.command_port, f.store.consumer(), actor=f.actor)
            legacy.record(old)
            self.assertEqual(capture.read('old-inline-result'), old)
            changed = dict(value, raw_result={'stdout': 'changed'})
            with self.assertRaises(ValueError): capture.record(changed)
            foreign = dict(pin, origin={**pin['origin'], 'project_ref': {'authority':'execution-owner','kind':'work.project','id':'other','revision':None}})
            with self.assertRaises(ValueError): bodies.resolve(foreign)
        finally: f.doCleanups()

    def test_review_input_resolves_real_wrk_refs_without_rewriting_and_rejects_missing_reader(self):
        from types import SimpleNamespace
        from tests import test_execution_application as application_fixture
        from tests.test_evidence_projection import _v11_pack_hooks
        from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
        from herzchen.evidence.model import load_evidence_pack
        from herzchen.packs.authoring import read_managed_pack
        from otto.agents.gateway import HerzchenAttemptCapture
        from otto.portfolio.manager_journey_command import ManagerJourneyCommands, _digest
        f=application_fixture.ExecutionApplicationTests();f.setUp()
        try:
            manager,_,_=f.role_handles('manager','manager','manager-session')
            worker,_,_=f.role_handles('worker','review-worker','worker-session')
            register_evidence(f.store)
            root,discover,loader=_v11_pack_hooks()
            pack=load_evidence_pack(managed_pack=read_managed_pack('evidence',project_root=root.parents[3],discoverer=discover,loader=loader))
            handler=EvidenceCommandHandler(f.store,f.path.parent/'review-bodies',pack=pack,adopted_pins=[x.to_dict()for x in pack.resources])
            bodies=RetainedNativeBodies(handler,f.actor)
            capture=HerzchenAttemptCapture(f.owner.assignments.command_port,f.store.consumer(),actor=f.actor,native_bodies=bodies)
            result={'logical_request_key':'review-body-result','request_fingerprint':'review-body-fingerprint','project_ref':f.project.ref.to_dict(),'task_ref':f.task.ref.to_dict(),'assignment_ref':worker.ref.to_dict(),'generation':1,'outcome':'succeeded','context_digest_verified':True,'raw_result':{'stdout':'x'*100000}}
            capture.record(result)
            records=f.owner.assignments.command_port.list_observations(worker.ref,kind='result');before=_digest(records[0].value)
            f.owner.assignments.command_port.append_result(worker.ref,'legacy opaque noncandidate',expected_generation=1,logical_request_key='opaque-legacy-result',actor=f.actor)
            state={'project_ref':f.project.ref.to_dict(),'assignment_ref':manager.ref.to_dict(),'manager':'manager','manager_generation':1,'task_refs':{'J01':f.task.ref.to_dict()},'workers':{'J01':{'schedule_id':'review-worker-occurrence','assignment_ref':worker.ref.to_dict(),'principal':'review-worker','generation':1}}}
            due={'assignment_ref':worker.ref.to_dict(),'generation':1,'stop_state':'completed','completion_state':'succeeded','in_flight_request':None,'host_evidence':{'gateway_attempt':{'result':result}}}
            port=SimpleNamespace(read_due=lambda schedule:due)
            missing=ManagerJourneyCommands(owner=f.owner,portfolio=f.app.portfolio,state=state,due_port=port)
            with self.assertRaisesRegex(ValueError,'one exact canonical observation'):missing.review_input('J01')
            commands=ManagerJourneyCommands(owner=f.owner,portfolio=f.app.portfolio,state=state,due_port=port,native_bodies=bodies)
            view=commands.review_input('J01');self.assertEqual(view['candidate_ref'],records[0].ref.to_dict());self.assertEqual(view['worker_result_sha256'],_digest(result))
            again=f.owner.assignments.command_port.list_observations(worker.ref,kind='result');self.assertEqual(len(again),2);retained=next(x for x in again if x.ref==records[0].ref);self.assertEqual(_digest(retained.value),before)
            self.assertEqual(retained.value['raw_result']['stdout']['schema'],SCHEMA)
            due['host_evidence']['gateway_attempt']['result']={**result,'raw_result':{'stdout':'different'}}
            with self.assertRaisesRegex(ValueError,'one exact canonical observation'):commands.review_input('J01')
            due['generation']=2
            with self.assertRaisesRegex(PermissionError,'binding differs'):commands.review_input('J01')
            due['generation']=1;due['host_evidence']['gateway_attempt']['result']=result
            f.owner.assignments.command_port.append_result(worker.ref,result,expected_generation=1,logical_request_key='duplicate-semantic-result',actor=f.actor)
            with self.assertRaisesRegex(ValueError,'one exact canonical observation'):commands.review_input('J01')
        finally:f.doCleanups()

if __name__ == '__main__': unittest.main()

"""SL9: a host turn's transcript is stored once, by digest; records carry a reference.

Real Store, real Due port (no mocks of the store), a realistic completed-turn
record. Bodies live in the private content-addressed ``FileBodyStore``; no
schema change, no Evidence pack.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from herzchen.command_ports import close_consumer_facade
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel.store import Store
from otto.agents.retained_native import (SCHEMA, BodyPurged, FileBodyStore, RetainedNativeBodies)
from otto.attention import due_record_contribution, issue_store_due_record_port

from tests.test_usage_capture import owner_capture

PROJECT = ResourceRef('owner', 'work.project', 'project')
SESSION = 'native-session-1'


def noise(label, size):
    """Incompressible-ish deterministic text (hex digests), like real transcripts."""
    out, n = [], 0
    while n < size:
        chunk = hashlib.sha256((label + str(len(out))).encode()).hexdigest() * 2
        out.append(chunk)
        n += len(chunk)
    return ''.join(out)[:size]


def evidence(scale=1):
    return {'session_id': SESSION, 'turn_id': 'turn-1', 'evidence_digest': 'e' * 64,
            'transcript': noise('tbe', 300_000 * scale), 'owner_delivery_authorization': {'assignment': 'a', 'brief_sha256': 'b' * 64}}


def turn_result(scale=1):
    """A completed host turn as the gateway records it (task_bound_evidence is nested twice)."""
    tbe = evidence(scale)
    return {
        'outcome': 'succeeded', 'context_digest_verified': True, 'physical_session_id': SESSION,
        'observed_turn_id': 'turn-1', 'requested_model': 'claude-sonnet-5-5', 'observed_model': 'claude-sonnet-5-5',
        'requested_tier': 'high', 'observed_tier': 'high', 'native_session_id': SESSION,
        'raw_result': {'exit_status': 0, 'stdout': noise('stdout', 1_500_000 * scale),
                       'work_envelope': {'task_bound_evidence': tbe, 'events': [noise('ev' + str(i), 2000) for i in range(40)]}},
        'task_bound_evidence': tbe,
        'resource_evidence': {'schema': 'otto.orchestrator.resource_evidence.v1', 'brief': {'text': noise('brief', 150_000 * scale)},
                              'resources': [{'name': 'guide', 'content': noise('guide', 20_000)}]},
        'worker_content': ['done: ' + noise('answer', 900)],
    }


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='sl9-')).resolve()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.actor = AuthenticatedActor('owner', 'submitter', 'credential')
        self.stores = []

    def open_store(self, name='owner.sqlite'):
        store = Store.create(self.dir / name, authority='owner')
        self.stores.append(store)
        self.addCleanup(store.close)
        store.register_domain_handler([due_record_contribution()])
        return store

    def port(self, store, bodies=None):
        port = issue_store_due_record_port(store.domain_handler([due_record_contribution()]), self.actor, native_bodies=bodies)
        self.addCleanup(close_consumer_facade, port.transport)
        return port

    def bodies(self, name='bodies'):
        return RetainedNativeBodies.on_files(self.dir / name, self.actor)

    def base_record(self):
        _, memory = owner_capture()
        value = memory.read_due('schedule')
        value['project_ref'] = PROJECT.id
        value['assignment_ref'] = {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'attempt-1', 'revision': 'rev-1'}
        value['target']['project_ref'] = PROJECT.to_dict()
        value['target']['native_adapter'] = 'claude-code'
        return value

    def seed(self, store):
        store.put_identity(ResourceRef.from_dict(self.base_record()['assignment_ref']), {'generation': 2}, version=1)

    def phases(self, scale=1):
        """The ~10 saves a callback record goes through, ending with the completed turn."""
        value = self.base_record()
        result = turn_result(scale)
        steps = []
        for i in range(10):
            record = json.loads(json.dumps(value))
            record['host_evidence'] = {'phase': i}
            if i >= 2:
                record['host_evidence']['gateway_attempt'] = {
                    'state': 'claimed', 'logical_request_key': 'key', 'request_fingerprint': 'f' * 64,
                    'physical_session_id': SESSION,
                    'delivery_authorization': {'physical_session_id': SESSION, 'assignment_ref': value['assignment_ref']}}
            if i >= 6:
                record['host_evidence']['gateway_attempt']['state'] = 'result'
                record['host_evidence']['gateway_attempt']['result'] = result
                record['host_evidence']['captured_artifacts'] = [{'path': 'out/%d.txt' % n, 'content': noise('art%d' % n, 40_000 * scale)} for n in range(3)]
            steps.append(record)
        return steps

    def save_all(self, port, steps):
        saved = None
        for i, record in enumerate(steps):
            record = dict(record, version=i)
            saved = port.save_due('schedule', record, request_id='save-%d' % i, expected_version=i)
        return saved

    def store_bytes(self, store):
        c = store.connection
        return c.execute('PRAGMA page_count').fetchone()[0] * c.execute('PRAGMA page_size').fetchone()[0]

    @staticmethod
    def body_files(root):
        return [p for p in Path(root).rglob('*') if p.is_file() and p.parent.name != 'purged' and not p.name.startswith('.tmp-')]

    def events(self, store):
        return [e for e in store.list_events(stream='otto.due-record:schedule')]


class TranscriptStoredOnceTests(Fixture):
    def test_transcript_stored_once_per_turn(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        steps = self.phases()
        self.save_all(port, steps)
        files = self.body_files(bodies.files.root)
        shas = {p.name for p in files}
        self.assertEqual(len(shas), len(files), 'a body is addressed once')
        result = steps[-1]['host_evidence']['gateway_attempt']['result']
        def digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        stdout, transcript = result['raw_result']['stdout'], result['task_bound_evidence']['transcript']
        # ten saves carry the same turn many times; each distinct body is one file, and the
        # transcript nested inside raw_result.work_envelope is the same file as the top-level copy.
        self.assertEqual(sum(1 for p in files if p.name == digest(stdout)), 1)
        self.assertEqual(sum(1 for p in files if p.name == digest(transcript)), 1)
        self.assertEqual(sum(1 for p in files if p.name == digest(result['resource_evidence']['brief']['text'])), 1)
        self.assertLess(len(files), 12)
        # readers resolve it: the current record reads back byte-for-byte as it was saved
        current = port.read_due('schedule')
        got = current['host_evidence']['gateway_attempt']['result']
        self.assertEqual(got['raw_result'], result['raw_result'])
        self.assertEqual(got['task_bound_evidence'], result['task_bound_evidence'])
        self.assertEqual(current['host_evidence']['captured_artifacts'], steps[-1]['host_evidence']['captured_artifacts'])
        # saving the same turn again (a later status update) writes no new body
        before = {p.name for p in self.body_files(bodies.files.root)}
        later = dict(steps[-1], version=10)
        later['host_evidence'] = dict(later['host_evidence'], phase=99)
        port.save_due('schedule', later, request_id='save-10', expected_version=10)
        self.assertEqual({p.name for p in self.body_files(bodies.files.root)}, before)

    def test_small_fields_stay_inline_for_sql_and_index_readers(self):
        store = self.open_store(); self.seed(store)
        port = self.port(store, self.bodies())
        self.save_all(port, self.phases())
        last = self.events(store)[-1]
        row = store.connection.execute(
            "SELECT json_extract(effects_json,'$.record.host_evidence.gateway_attempt.result.context_digest_verified'),"
            "json_type(effects_json,'$.record.host_evidence.gateway_attempt.result.context_digest_verified'),"
            "json_extract(effects_json,'$.record.host_evidence.gateway_attempt.result.requested_model'),"
            "json_extract(effects_json,'$.record.host_evidence.gateway_attempt.delivery_authorization.physical_session_id') "
            "FROM events WHERE event_id=?", (last.event_id,)).fetchone()
        self.assertEqual(tuple(row), (1, 'true', 'claude-sonnet-5-5', SESSION))
        # attention.py / the due-native lookup index select by physical session without any body
        with mock.patch.object(RetainedNativeBodies, 'resolve', side_effect=AssertionError('lookup read a body')):
            found = port.list_due({'native_adapter': 'claude-code', 'native_session_id': SESSION})
        self.assertEqual([r['schedule_id'] for r in found], ['schedule'])
        store.prepare_identity_lookup_indexes()
        plan = ' '.join(r[3] for r in store.connection.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM identities WHERE authority='owner' AND kind='otto.due-record' "
            "AND json_extract(payload_json,'$.target.native_adapter')='claude-code' "
            "AND json_extract(payload_json,'$.host_evidence.gateway_attempt.delivery_authorization.physical_session_id')=?", (SESSION,)))
        self.assertIn('identities_due_native_lookup', plan)


class EventsCarryReferencesTests(Fixture):
    def test_due_record_event_carries_reference_not_body(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        steps = self.phases()
        self.save_all(port, steps)
        result = steps[-1]['host_evidence']['gateway_attempt']['result']
        for event in self.events(store):
            text = event.to_json()
            self.assertLess(len(text), 60_000, 'event snapshot stays small')
            self.assertNotIn(result['raw_result']['stdout'][:200], text)
            self.assertNotIn(result['task_bound_evidence']['transcript'][:200], text)
        raw_ref = self.events(store)[-1].effects['record']['host_evidence']['gateway_attempt']['result']['raw_result']['stdout']
        self.assertEqual(raw_ref['schema'], SCHEMA)
        self.assertEqual(raw_ref['store'], 'file')
        self.assertEqual(raw_ref['media_type'], 'application/json')
        self.assertEqual(len(raw_ref['sha256']), 64)
        self.assertGreater(raw_ref['utf8_bytes'], 1_500_000)
        self.assertTrue(raw_ref['inline_replacement'])
        identity = port.transport and store.get_identity(ResourceRef('owner', 'otto.due-record', 'schedule'))
        self.assertLess(len(json.dumps(identity.payload)), 60_000)
        # every digest the log mentions is durable on disk
        for carrier in self.carriers(self.events(store)[-1].effects):
            self.assertTrue(bodies.files.exists(carrier['origin']['project_ref'], carrier['sha256']))

    @staticmethod
    def carriers(value):
        if isinstance(value, dict):
            if value.get('schema') == SCHEMA:
                yield value
            else:
                for item in value.values():
                    yield from EventsCarryReferencesTests.carriers(item)
        elif isinstance(value, list):
            for item in value:
                yield from EventsCarryReferencesTests.carriers(item)


class LegacyInlineTests(Fixture):
    def test_inline_legacy_records_still_read(self):
        store = self.open_store(); self.seed(store)
        legacy = self.port(store)                       # no body capability: bodies stay inline
        steps = self.phases(scale=1)
        saved = legacy.save_due('schedule', dict(steps[-1], version=0), request_id='legacy-0', expected_version=0)
        self.assertGreater(len(self.events(store)[-1].to_json()), 1_500_000)
        modern = self.port(store, self.bodies())
        read = modern.read_due('schedule')
        want = steps[-1]['host_evidence']['gateway_attempt']['result']
        self.assertEqual(read['host_evidence']['gateway_attempt']['result']['raw_result'], want['raw_result'])
        self.assertEqual(modern.read_due('schedule', hydrate_native=False)['host_evidence'], saved['host_evidence'])
        # an exact replay of the old receipt must not repin or rewrite it
        replay = modern.save_due('schedule', dict(steps[-1], version=0), request_id='legacy-0', expected_version=0)
        self.assertTrue(replay['mutation_receipt']['replayed'])
        self.assertEqual(self.body_files(self.dir / 'bodies'), [])
        # the next save under the new port externalizes it and still reads identically
        nxt = dict(steps[-1], version=1)
        nxt['host_evidence'] = dict(nxt['host_evidence'], phase=2)
        modern.save_due('schedule', nxt, request_id='modern-1', expected_version=1)
        self.assertEqual(modern.read_due('schedule')['host_evidence']['gateway_attempt']['result']['raw_result'], want['raw_result'])
        # and a legacy-composed reader of a modern record sees references, never a half body
        modern_read_raw = legacy.read_due('schedule')['host_evidence']['gateway_attempt']['result']['raw_result']['stdout']
        self.assertEqual(modern_read_raw['schema'], SCHEMA)


class CrashOrderTests(Fixture):
    def test_crash_after_body_before_record_leaves_no_dangling_ref(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        steps = self.phases()
        self.save_all(port, steps[:6])
        events_before = len(self.events(store))
        identity_before = store.get_identity(ResourceRef('owner', 'otto.due-record', 'schedule'))
        record = dict(steps[-1], version=6)
        # The process dies after the bodies are durable and before the record commits.
        class Crash(Exception):
            pass

        with mock.patch('herzchen.contracts.CommandEnvelope', side_effect=Crash('crash before commit')):
            with self.assertRaises(Exception):
                port.save_due('schedule', record, request_id='save-6', expected_version=6)
        files = self.body_files(bodies.files.root)
        self.assertGreater(len(files), 0, 'bodies were written first')
        # nothing references them: same events, same identity
        self.assertEqual(len(self.events(store)), events_before)
        self.assertEqual(store.get_identity(ResourceRef('owner', 'otto.due-record', 'schedule')).payload, identity_before.payload)
        # the log verifies on reopen (gapless, foreign keys) and the retry commits, reusing the orphans
        count = len(files)
        port.save_due('schedule', record, request_id='save-6', expected_version=6)
        again = self.body_files(bodies.files.root)
        self.assertEqual({p.name for p in files} - {p.name for p in again}, set())
        self.assertGreaterEqual(len(again), count)
        self.assertEqual(port.read_due('schedule')['host_evidence']['gateway_attempt']['result']['raw_result'],
                         steps[-1]['host_evidence']['gateway_attempt']['result']['raw_result'])

    def test_body_is_durable_before_any_record_names_it(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        log = []
        real_fsync, real_replace = os.fsync, os.replace
        with mock.patch('os.fsync', side_effect=lambda fd: (log.append('fsync'), real_fsync(fd))[1]), \
                mock.patch('os.replace', side_effect=lambda a, b: (log.append('rename'), real_replace(a, b))[1]):
            import herzchen.contracts as attention
            real_envelope = attention.CommandEnvelope

            def spy(*args, **kwargs):
                log.append('commit-record')
                for carrier in EventsCarryReferencesTests.carriers(args[4]):
                    log.append(('exists', bodies.files.exists(carrier['origin']['project_ref'], carrier['sha256'])))
                return real_envelope(*args, **kwargs)
            with mock.patch.object(attention, 'CommandEnvelope', side_effect=spy):
                port.save_due('schedule', dict(self.phases()[-1], version=0), request_id='order-0', expected_version=0)
        at = log.index('commit-record')
        self.assertIn('rename', log[:at])
        self.assertGreaterEqual(log[:at].count('fsync'), 2)
        self.assertTrue(all(item[1] for item in log[at:] if isinstance(item, tuple)))

    def test_failed_write_never_exposes_a_partial_body(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        with mock.patch('os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                port.save_due('schedule', dict(self.phases()[-1], version=0), request_id='disk-0', expected_version=0)
        leftovers = [p for p in Path(bodies.files.root).rglob('*') if p.is_file()]
        self.assertEqual(leftovers, [])
        self.assertEqual(self.events(store), [])


class ReclaimTests(Fixture):
    def test_purge_project_deletes_bodies_and_records_read_as_cleaned(self):
        store = self.open_store(); self.seed(store)
        bodies = self.bodies()
        port = self.port(store, bodies)
        steps = self.phases()
        self.save_all(port, steps)
        other = {'authority': 'owner', 'kind': 'work.project', 'id': 'other-project'}
        bodies.files.put(other, 'a' * 64, b'unrelated')
        self.assertGreater(bodies.files.inventory(PROJECT.to_dict())['files'], 3)
        report = bodies.purge_project(PROJECT)
        self.assertTrue(report['purged'])
        self.assertEqual(bodies.files.inventory(PROJECT.to_dict())['files'], 0)
        self.assertTrue(bodies.files.exists(other, 'a' * 64), 'another project is untouched')
        self.assertTrue(bodies.purge_project(PROJECT)['purged'], 'idempotent')
        # the record still reads; the reclaimed bodies are simply absent (as after clean-close)
        current = port.read_due('schedule')
        result = current['host_evidence']['gateway_attempt']['result']
        self.assertNotIn('stdout', result['raw_result'])
        self.assertNotIn('transcript', result['task_bound_evidence'])
        self.assertLess(len(json.dumps(current)), 20_000)
        self.assertEqual(result['context_digest_verified'], True)
        self.assertEqual(current['schedule_id'], 'schedule')
        port.read_due('schedule', hydrate_native=False)      # metadata check accepts purged carriers
        # a lost (not reclaimed) body is an error, never silently dropped
        shutil.rmtree(self.dir / 'bodies' / 'purged')
        (self.dir / 'bodies' / 'purged').mkdir()
        with self.assertRaises(ValueError):
            port.read_due('schedule')


class SizeTests(Fixture):
    def measure(self, bodies):
        store = self.open_store('m-%s.sqlite' % ('with' if bodies else 'without')); self.seed(store)
        port = self.port(store, bodies)
        base = self.store_bytes(store)
        self.save_all(port, self.phases(scale=3))
        grown = self.store_bytes(store) - base
        disk = sum(p.stat().st_size for p in self.body_files(bodies.files.root)) if bodies else 0
        return grown, disk

    def test_store_bytes_per_completed_turn_at_least_5x_smaller(self):
        before_sqlite, _ = self.measure(None)
        after_sqlite, after_files = self.measure(self.bodies('m-bodies'))
        total_after = after_sqlite + after_files
        print('SL9 bytes per completed turn: inline %d -> sqlite %d (+%d body file bytes) = %d; sqlite %.1fx, total %.1fx'
              % (before_sqlite, after_sqlite, after_files, total_after, before_sqlite / after_sqlite, before_sqlite / total_after))
        self.assertGreaterEqual(before_sqlite / after_sqlite, 5)
        self.assertGreaterEqual(before_sqlite / total_after, 5)


class FileBodyStoreTests(Fixture):
    def test_content_addressed_verified_and_private(self):
        files = FileBodyStore(self.dir / 'fb')
        project = {'authority': 'owner', 'kind': 'work.project', 'id': 'p'}
        raw = b'{"a":1}'
        sha = hashlib.sha256(raw).hexdigest()
        files.put(project, sha, raw)
        files.put(project, sha, raw)
        self.assertEqual(files.get(project, sha, len(raw)), raw)
        with self.assertRaises(ValueError):
            files.get(project, sha, len(raw) + 1)
        with self.assertRaises(ValueError):
            files.get({'authority': 'owner', 'kind': 'work.project', 'id': 'q'}, sha, len(raw))
        path = next(Path(self.dir / 'fb').rglob(sha))
        path.write_bytes(b'garbage')
        with self.assertRaises(ValueError):
            files.get(project, sha, len(raw))
        self.assertEqual(oct(os.stat(self.dir / 'fb').st_mode & 0o777), '0o700')


class HostSessionWiringTests(Fixture):
    def test_host_session_externalizes_transcripts(self):
        from otto.hostctl import config as host_config
        from otto.hostctl.owner import HostSession, create_store, native_body_root
        home = self.dir / 'home'
        config = host_config.new_installation(home, store_path=str(self.dir / 'host.sqlite'), authority='owner',
                                              owner_actor='owner', operator_actor='human-operator',
                                              credential_ref='credential', python='python3')
        config = create_store(config)
        with HostSession(config) as session:
            self.assertIsInstance(session.native_bodies, RetainedNativeBodies)
            self.assertEqual(session.native_bodies.files.root, native_body_root(config))
            session.store.put_identity(ResourceRef.from_dict(self.base_record()['assignment_ref']), {'generation': 2}, version=1)
            steps = self.phases()
            for i, record in enumerate(steps):
                session.due_port.save_due('schedule', dict(record, version=i), request_id='h-%d' % i, expected_version=i)
            events = session.store.list_events(stream='otto.due-record:schedule')
            self.assertLess(max(len(e.to_json()) for e in events), 60_000)
            self.assertEqual(session.due_port.read_due('schedule')['host_evidence']['gateway_attempt']['result']['raw_result'],
                             steps[-1]['host_evidence']['gateway_attempt']['result']['raw_result'])
        self.assertTrue(self.body_files(native_body_root(config)))


if __name__ == '__main__':
    unittest.main()

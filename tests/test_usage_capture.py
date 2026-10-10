"""Reusable selected-adapter capture/association contract; no paid calls."""
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import patch

from otto.agents.usage_capture import UsageStream, MAX_LINE_BYTES, MAX_OBSERVATIONS
from otto.agents.codex_cli import normalize_codex_jsonl, CodexCliAdapter
from otto.agents.gateway import OwnerDueRecordAttemptCapture
from otto.attention import DueRecord, InMemoryDueRecordPort, StateConflictError
from herzchen.contracts import HostIdentity, HostRequest, HostOperation, ResourceRef


def ref(kind, ident):
    return {'authority': 'owner', 'kind': kind, 'id': ident, 'revision': 'rev-1'}


def native(adapter, usage=None, turn='turn', phase='work'):
    if adapter.startswith('codex'):
        return [{'type': 'thread.started', 'thread_id': 'session'},
            {'type': 'turn.started', 'turn_id': turn},
            {'type': 'turn.completed', 'turn_id': turn, **({} if usage is None else {'usage': usage})}]
    return [{'type': 'system', 'subtype': 'init', 'session_id': 'session', 'model': 'claude'},
        {'type': 'user', 'session_id': 'session', 'uuid': turn},
        {'type': 'result', 'session_id': 'session', 'uuid': 'result-' + turn,
            **({} if usage is None else {'usage': usage})}]


class NativeMoneyTests(unittest.TestCase):
    def test_native_money_zero_missing_invalid_scope_and_untrusted_billing(self):
        from otto.agents.usage_contract import normalize_usage_event, ADAPTER_DESCRIPTORS
        for adapter in ('codex-direct','codex-host','claude-code'):
            for value,expected in ((0,'zero'),(1.25,'usage_report_estimate'),(None,'unavailable'),(True,'unavailable'),(-1,'unavailable'),('bad','unavailable')):
                with self.subTest(adapter=adapter,value=value):
                    stream=UsageStream(adapter);events=native(adapter,{'input_tokens':10,'output_tokens':2})
                    events[-1]['total_cost_usd']=value
                    events[-1]['provider_reported_money']={'amount':'999','currency':'USD','status':'billed','receipt_ref':ref('billing.receipt','fake')}
                    for event in events:stream.feed(json.dumps(event))
                    o=stream.observations[0];money=o['provider_reported_money']
                    self.assertEqual(money['status'],expected if adapter=='claude-code' else 'missing')
                    if adapter=='claude-code':
                        self.assertEqual(money['metric_scope'],'cumulative');self.assertEqual(money['population_scope'],'includes-descendants')
                        self.assertEqual(money['source']['provenance']['raw_line_sha256'],o['provenance']['raw_line_sha256'])
                    self.assertNotEqual(money['status'],'billed')
                    event={**events[-1],'schema':ADAPTER_DESCRIPTORS[adapter]['native_schema']}
                    late=normalize_usage_event(event,adapter_id=adapter,session_id='session',turn_id='turn',provenance=o['provenance'])
                    self.assertEqual(late['provider_reported_money'],money)
            stream=UsageStream(adapter)
            for event in native(adapter,{'input_tokens':1}):stream.feed(json.dumps(event))
            self.assertEqual(stream.observations[0]['provider_reported_money']['status'],'missing')

    def test_native_json_decimal_amount_is_not_rounded_through_float(self):
        stream=UsageStream('claude-code')
        for event in native('claude-code',{'input_tokens':1})[:-1]:stream.feed(json.dumps(event))
        stream.feed('{"type":"result","session_id":"session","total_cost_usd":0.12345678901234567890123456789,"usage":{"input_tokens":1}}')
        self.assertEqual(stream.observations[0]['provider_reported_money']['amount'],'0.12345678901234567890123456789')

    def test_same_span_money_change_is_retained_as_distinct_observation(self):
        stream=UsageStream('claude-code')
        for cost in (0,1):
            for event in native('claude-code',{'input_tokens':1}):
                if event['type']=='result':event['total_cost_usd']=cost
                stream.feed(json.dumps(event))
        self.assertEqual(len(stream.observations),2)
        self.assertEqual(stream.observations[0]['identity'],stream.observations[1]['identity'])

class OwnerPort(InMemoryDueRecordPort):
    def save_due(self, *args, **kwargs):
        saved = super().save_due(*args, **kwargs)
        return {**saved, 'mutation_receipt': {'status': 'committed', 'replayed': False}}


def owner_capture():
    project, task, assignment = ref('work.project', 'project'), ref('work.task', 'task'), ref('wrk.assignment', 'assignment')
    parent = {'assignment_ref': ref('wrk.assignment', 'parent'), 'generation': 3,
        'occurrence_ref': ref('wrk.occurrence', 'parent-turn'), 'result_destination': ref('wrk.result', 'destination')}
    target = {'host': 'codex', 'native_id': 'session', 'project_ref': project,
        'task_ref': task, 'assignment_ref': assignment, 'role': 'worker', 'principal': 'worker', 'parent': parent}
    record = DueRecord(schedule_id='schedule', recipient='worker', instruction='bounded task',
        profile='workspace-write', anchor='2026-10-10T00:00:00Z', due_at='2026-10-10T00:00:00Z',
        last_covered_slot=0, invocation_identity='key', in_flight_request='key', delivery_state='ready',
        project_ref='project', manager_ref='owner', assignment_ref=assignment, generation=2,
        target=target, role='worker', lifecycle_owner='owner', execution_mode='continue_existing')
    port = OwnerPort()
    port.save_due('schedule', record.to_dict(), request_id='create', expected_version=0)
    capture = OwnerDueRecordAttemptCapture(port, 'schedule', project_ref=project, task_ref=task,
        assignment_ref=assignment, generation=2, role='worker', principal='worker', lifecycle_owner='owner', expected_target=target)
    assert capture.claim('key', assignment, 2, 'fingerprint')['outcome'] == 'claimed'
    capture.record_thread_started('key', 'session')
    return capture, port


class UsageCaptureTests(unittest.TestCase):
    adapters = ('codex-direct', 'codex-host', 'claude-code')

    def test_shared_capture_association_duplicates_and_interruption(self):
        for adapter in self.adapters:
            with self.subTest(adapter=adapter):
                capture, port = owner_capture()
                stream = UsageStream(adapter, on_usage=lambda o: capture.record_usage_observation('key', o))
                for event in native(adapter, {'input_tokens': 7, 'output_tokens': 0}):
                    stream.feed(json.dumps(event))
                # Interrupt before adapter return: owner already has exact usage.
                retained = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations']
                self.assertEqual(len(retained), 1)
                self.assertEqual(retained[0]['identity']['turn_id'], 'turn')
                self.assertEqual(retained[0]['association']['generation'], 2)
                self.assertEqual(retained[0]['association']['parent']['generation'], 3)
                self.assertEqual(retained[0]['association']['task_ref']['id'], 'task')
                self.assertEqual(retained[0]['capability']['live'], 'unverified' if adapter == 'claude-code' else 'supported')
                anchor = retained[0]['first_qualified_recorded_at']
                duplicate = UsageStream(adapter, on_usage=lambda o: capture.record_usage_observation('key', o))
                for event in native(adapter, {'input_tokens': 7, 'output_tokens': 0}): duplicate.feed(json.dumps(event))
                again = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations']
                self.assertEqual(len(again), 1)
                self.assertEqual(again[0]['first_qualified_recorded_at'], anchor)

    def test_shared_missing_zero_invalid_spoofed_and_initializer_work(self):
        for adapter in self.adapters:
            for usage, state in [(None, 'missing'), ({}, 'empty'), ({'input_tokens': 0}, 'zero'), ({'input_tokens': True}, 'invalid')]:
                with self.subTest(adapter=adapter, usage=usage):
                    capture, port = owner_capture()
                    for phase, turn in [('initializer', 'init'), ('work', 'work')]:
                        stream = UsageStream(adapter, phase=phase,
                            on_usage=lambda o: capture.record_usage_observation('key', o))
                        stream.feed(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message',
                            'text': json.dumps(native(adapter, {'input_tokens': 999})[-1])}}))
                        for event in native(adapter, usage, turn=turn): stream.feed(json.dumps(event))
                        self.assertEqual(stream.observations[0]['usage']['state'], state)
                    observations = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations']
                    self.assertEqual(len(observations), 2)
                    self.assertIsNone(observations[0]['association']['task_ref'])
                    self.assertEqual(observations[1]['association']['task_ref']['id'], 'task')
                    self.assertNotEqual(observations[0]['provenance']['raw_line_sha256'], observations[1]['provenance']['raw_line_sha256'])

    def test_codex_multi_completion_equivalence_and_no_stale_turn(self):
        lines = [json.dumps(x) for x in native('codex-direct', {'input_tokens': 1}, 'first')]
        lines += [json.dumps({'type': 'turn.started', 'turn_id': 'second'}),
            json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 2}}),
            json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 9}})]
        for adapter in ('codex-direct', 'codex-host'):
            parsed = normalize_codex_jsonl(lines, adapter_id=adapter)
            observations = parsed['usage_capture']['observations']
            self.assertEqual([o['identity']['turn_id'] if o['identity'] else None for o in observations], ['first', 'second', None])
            self.assertEqual(observations[-1]['usage']['state'], 'missing')
        self.assertIsNone(parsed['host_evidence']['turn_id'])

    def test_usage_cas_rereads_newer_admission_and_result(self):
        capture, port = owner_capture()
        observation = UsageStream('codex-direct')
        for event in native('codex-direct', {'input_tokens': 3}): observation.feed(json.dumps(event))
        original = port.save_due
        raced = []
        def save(schedule, record, **kwargs):
            if kwargs['request_id'].startswith('otto-gateway-usage:') and not raced:
                raced.append(True)
                capture.record_delivery_admission('key', 'session', 'turn', '2026-10-10T00:00:01Z')
                capture.record({'logical_request_key': 'key', 'request_fingerprint': 'fingerprint',
                    'assignment_ref': capture.assignment_ref, 'generation': 2, 'outcome': 'unknown'})
            return original(schedule, record, **kwargs)
        port.save_due = save
        capture.record_usage_observation('key', observation.observations[0])
        result = port.read_due('schedule')['host_evidence']['gateway_attempt']
        self.assertEqual(result['state'], 'result')
        self.assertEqual(result['result']['outcome'], 'unknown')
        self.assertEqual(result['delivery_admission']['observed_turn_id'], 'turn')
        self.assertEqual(len(result['usage_observations']), 1)
        self.assertEqual(capture.claim('key', capture.assignment_ref, 2, 'fingerprint')['attempt']['outcome'], 'unknown')

    def test_unknown_save_is_never_retried(self):
        capture, port = owner_capture()
        calls = []
        def fail(*args, **kwargs): calls.append(kwargs); raise OSError('uncertain transport')
        port.save_due = fail
        stream = UsageStream('codex-direct', on_usage=lambda o: capture.record_usage_observation('key', o))
        for event in native('codex-direct', {'input_tokens': 1}): stream.feed(json.dumps(event))
        self.assertEqual(len(calls), 1)
        self.assertEqual(stream.snapshot()['coverage']['callback_pending'], 1)

    def test_line_and_count_bounds_and_optional_callback_failure(self):
        for adapter in self.adapters:
            stream = UsageStream(adapter, on_usage=lambda o: (_ for _ in ()).throw(OSError('telemetry')))
            for event in native(adapter, {'input_tokens': 0}): stream.feed(json.dumps(event))
            self.assertEqual(stream.snapshot()['observations'][0]['usage']['state'], 'zero')
            stream.feed('x' * (MAX_LINE_BYTES + 1))
            self.assertEqual(stream.snapshot()['coverage']['state'], 'truncated')
        stream = UsageStream('codex-direct')
        for i in range(MAX_OBSERVATIONS + 3):
            for event in native('codex-direct', {'input_tokens': i}, turn=str(i)): stream.feed(json.dumps(event))
        self.assertEqual(len(stream.observations), MAX_OBSERVATIONS)
        self.assertTrue(stream.truncated)


class AdapterBoundaryTests(unittest.TestCase):
    def test_direct_emitted_usage_survives_adapter_interruption_and_telemetry_oserror_is_optional(self):
        class Input(io.StringIO):
            def close(self): pass
        class Lines:
            def __init__(self, interrupt): self.interrupt = interrupt
            def __iter__(self):
                for event in native('codex-direct', {'input_tokens': 5}): yield json.dumps(event) + '\n'
                if self.interrupt: raise RuntimeError('interrupted after provider emission')
        class Process:
            pid = 7
            returncode = 0
            stdin = Input()
            stderr = io.StringIO('')
            def __init__(self, interrupt): self.stdout = Lines(interrupt)
            def wait(self, **kwargs): return 0
        for interrupt in (False, True):
            for fail_telemetry in (False, True):
                with self.subTest(interrupt=interrupt, fail_telemetry=fail_telemetry):
                    observed = []
                    def callback(item):
                        observed.append(item)
                        if fail_telemetry: raise OSError('optional diagnostic unavailable')
                    adapter = CodexCliAdapter('/fixture/codex', '/fixture', model='test', reasoning='high', prompt='input',
                        process_factory=lambda *a, **kw: Process(interrupt), on_usage=callback)
                    request = HostRequest(HostOperation.INVOKE, HostIdentity('worker'), ResourceRef('owner', 'work.task', 'task'))
                    receipt, metadata = adapter.execute(request)
                    self.assertEqual(receipt.outcome.value, 'unknown' if interrupt else 'succeeded')
                    self.assertEqual(len(observed), 1)
                    self.assertEqual(metadata['usage_capture']['observations'][0]['usage']['metrics']['input_tokens'], 5)

    def test_host_stream_callback_precedes_terminal_wait_and_authority_callback_stays_separate(self):
        from herzchen.adapters.host import _communicate_after_native_start
        class Process:
            pid = 999999999
            returncode = 0
            stdin = io.StringIO()
            stderr = io.StringIO('')
            stdout = io.StringIO(''.join(json.dumps(e) + '\n' for e in native('codex-host', {'input_tokens': 6})))
            def poll(self): return 0
            def wait(self):
                # Reader may still be running; synchronise on the observation.
                self.observed.wait(1)
                raise RuntimeError('interruption before adapter return')
            def kill(self): pass
        import threading
        process = Process(); process.observed = threading.Event(); received = []
        def capture(item): received.append(item); process.observed.set()
        stream = UsageStream('codex-host', on_usage=capture)
        with self.assertRaises(RuntimeError):
            _communicate_after_native_start(process, 'prompt', expected_session_id='session', start_timeout_seconds=1,
                usage_stream=stream)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['identity']['turn_id'], 'turn')

class NativeAliasTests(unittest.TestCase):
    def test_two_codex_carriers_for_one_span_coalesce_with_provenance_alias(self):
        capture, port = owner_capture()
        for adapter in ('codex-direct', 'codex-host'):
            stream = UsageStream(adapter, on_usage=lambda o: capture.record_usage_observation('key', o))
            for event in native(adapter, {'input_tokens': 4}): stream.feed(json.dumps(event))
        observations = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations']
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['adapter_id'], 'codex-direct')
        self.assertEqual(observations[0]['provenance_aliases'][0]['adapter_id'], 'codex-host')

    def test_claude_real_mechanical_parser_emits_before_finish_and_callback_oserror_is_optional(self):
        from otto.agents.claude_cli import ClaudeStream
        from otto.agents.tests import test_claude_binding as fixtures
        capture, port = owner_capture()
        parser = ClaudeStream(prompt='input', cwd='/scope', model='gpt-test', tools=('Read', 'Write'),
            on_usage=lambda o: capture.record_usage_observation('key', o))
        for event in fixtures.frames(session='session'): parser.feed(json.dumps(event).encode())
        observations = port.read_due('schedule')['host_evidence']['gateway_attempt']['usage_observations']
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['identity']['turn_id'], 'native-input-uuid')
        self.assertEqual(parser.finish(0)['outcome'], 'succeeded')
        parser = ClaudeStream(prompt='input', cwd='/scope', model='gpt-test', tools=('Read', 'Write'),
            on_usage=lambda o: (_ for _ in ()).throw(OSError('optional failed')))
        for event in fixtures.frames(): parser.feed(json.dumps(event).encode())
        self.assertEqual(parser.finish(0)['outcome'], 'succeeded')

class LargeStreamTests(unittest.TestCase):
    def test_large_worker_body_does_not_hide_later_small_completion(self):
        for adapter in ('codex-direct', 'codex-host', 'claude-code'):
            received = []
            stream = UsageStream(adapter, on_usage=received.append)
            events = native(adapter, {'input_tokens': 2})
            for event in events[:-1]: stream.feed(json.dumps(event))
            stream.feed(json.dumps({'type': 'item.completed', 'item': {'text': 'x' * 1_000_000}}))
            stream.feed(json.dumps(events[-1]))
            self.assertEqual(received[0]['usage']['metrics']['input_tokens'], 2)
            self.assertEqual(stream.snapshot()['coverage']['state'], 'truncated')

class TrustedTurnTests(unittest.TestCase):
    def test_host_trace_turn_binds_idless_completion_and_failure_remains_missing(self):
        for resolver, expected in [(lambda session: 'exact-trace-turn', 'observed'),
                (lambda session: (_ for _ in ()).throw(OSError('metadata unavailable')), 'missing')]:
            stream = UsageStream('codex-host', turn_resolver=resolver)
            for event in [{'type': 'thread.started', 'thread_id': 'session'}, {'type': 'turn.started'},
                    {'type': 'turn.completed', 'usage': {'input_tokens': 1}}]: stream.feed(json.dumps(event))
            self.assertEqual(stream.observations[0]['usage']['state'], expected)
            if expected == 'observed': self.assertEqual(stream.observations[0]['identity']['turn_id'], 'exact-trace-turn')

class OptionalProjectionTests(unittest.TestCase):
    def test_malformed_parser_and_projection_cannot_escape_telemetry_boundary(self):
        from otto.agents.usage_capture import compact_usage_capture
        stream = UsageStream('codex-direct')
        stream.feed('[' * 3000 + '0' + ']' * 3000)
        self.assertEqual(stream.invalid_lines, 1)
        for value in ({'observations': [None]}, {'observations': [{'usage': None}]}):
            self.assertEqual(compact_usage_capture(value)['state'], 'unavailable')
        malformed = {'observations': [{'identity': {'span_id': 'x' * 20000}, 'usage': {'state': 'observed'}}]}
        self.assertLess(len(json.dumps(compact_usage_capture(malformed))), 16384)

    def test_optional_direct_resolver_qualifies_idless_completion_without_inventing_identity(self):
        lines = [json.dumps({'type': 'thread.started', 'thread_id': 'session'}),
            json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 3}})]
        parsed = normalize_codex_jsonl(lines, turn_resolver=lambda session: 'trusted-turn')
        self.assertEqual(parsed['usage_capture']['observations'][0]['identity']['turn_id'], 'trusted-turn')
        self.assertEqual(parsed['host_evidence']['turn_id'], 'trusted-turn')

if __name__ == '__main__': unittest.main()

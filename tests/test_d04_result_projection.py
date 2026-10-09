"""D04 regression checks: real transport faults, explicitly fixture provider work."""
import copy
import json
import socket
import threading
import unittest
from otto.portfolio.occurrence_reads import lookup, result_view
from otto.portfolio.caller_client import call_connection
from otto.portfolio.identity_context import HostIngress
from otto.portfolio.tests import test_worker_occurrences as fixtures

class D04ResultProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.WorkerOccurrenceTests(); self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def captured(self):
        response = self.fx.launch(); self.fx.yield_parent()
        started = self.fx.owner('start-retained-child', response['schedule_id'])
        self.assertEqual(started['outcome'], 'succeeded', started)
        return self.fx.f.port.read_due(response['schedule_id'])

    def test_lookup_key_scope_is_sufficient_and_supplied_input_still_checked(self):
        due = self.captured(); retained = due['target']['launch_request']
        counts = self.fx.f.store.consumer().snapshot_counts()
        key = self.fx.request['request_key']
        first = lookup(self.fx.f.port, scope=retained['scope'], request_key=key)
        self.assertEqual(first['outcome'], 'found')
        changed = dict(self.fx.request, focus='changed')
        self.assertEqual(lookup(self.fx.f.port, scope=retained['scope'], request_key=key, request_input=changed)['outcome'], 'conflict')
        self.assertEqual(self.fx.f.store.consumer().snapshot_counts(), counts)

    def test_success_requires_capture_and_unknown_is_not_terminal(self):
        due = self.captured(); native = due['host_evidence']['gateway_attempt']['result']
        due['host_evidence'].pop('captured_result_summary')
        held = result_view(due)
        self.assertEqual(held['outcome'], 'held'); self.assertIsNone(held['conclusion'])
        native.update(outcome='unknown', delivery_state='done')
        unknown = result_view(due)
        self.assertEqual(unknown['outcome'], 'unknown'); self.assertFalse(unknown['native_terminal'])
        self.assertFalse(unknown['required_capture']); self.assertFalse(unknown['retry'])

    def test_bounded_usage_preserves_native_metrics_and_rejects_foreign_ref_shape(self):
        due = self.captured(); summary = due['host_evidence']['captured_result_summary']
        summary['usage'] = {'state':'known', 'metrics':{'input_tokens':11, 'output_tokens':4,
            'total_tokens':True, 'unbounded':{'raw':'x'*9000}}}
        view = result_view(due)
        self.assertEqual(view['usage']['metrics'], {'input_tokens':11, 'output_tokens':4})
        summary['conclusion'] = 'x'*9000
        self.assertEqual(len(result_view(due)['conclusion']),4096)
        summary['result_ref']['id'] = {'raw':'x'*9000}
        self.assertIsNone(result_view(due)['result_ref'])

    def test_lost_reply_after_attempted_fixture_work_reads_result_without_replay(self):
        due = self.captured(); request = {'command':'read-result', 'occurrence':result_view(due)['occurrence']}
        client, owner = socket.socketpair(); client.settimeout(5); owner.settimeout(5)
        self.addCleanup(client.close); self.addCleanup(owner.close)
        lost=[]; thread=threading.Thread(target=lambda:lost.append(call_connection(client,request)))
        calls=len(self.fx.f.provider.calls); counts=self.fx.f.store.consumer().snapshot_counts()
        thread.start()
        raw=b''
        while not raw.endswith(b'\n'): raw+=owner.recv(262144)
        payload=json.loads(raw); payload.pop('transport_request_id')
        reply=self.fx.host._dispatch(payload,ingress=HostIngress('file-ipc',self.fx.host.directory/'owner-read'))
        self.assertTrue(reply.get('required_capture'), reply)
        owner.shutdown(socket.SHUT_RDWR); owner.close(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(lost[0]['outcome'],'unknown'); self.assertFalse(lost[0]['retry'])
        again=self.fx.host._dispatch(request,ingress=HostIngress('file-ipc',self.fx.host.directory/'owner-read'))
        self.assertEqual(again['result_ref'],reply['result_ref']); self.assertEqual(again['delivery_identity'],reply['delivery_identity'])
        self.assertEqual(len(self.fx.f.provider.calls),calls); self.assertEqual(self.fx.f.store.consumer().snapshot_counts(),counts)

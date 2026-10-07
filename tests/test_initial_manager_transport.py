"""The first manager's real outer file command pumps an ordinary nested caller."""
from pathlib import Path
import json
import hashlib
import tempfile
import threading
import time
import unittest
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.manager_journey_client import read_command_response

class InitialManagerTransportTests(unittest.TestCase):
    def test_first_manager_wait_receives_original_worker_before_manager_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            returned = threading.Event()
            effects, identities = [], {}
            def handler(request):
                if request['command'] == 'start-manager':
                    identities['owner'] = threading.get_ident()
                    def native_wait():
                        identities['transport'] = threading.get_ident()
                        (root / 'request-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json').write_text(json.dumps({
                            'command': 'run-worker', 'request_key': 'one-original-worker'}))
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            result = read_command_response(root, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')
                            if result is not None:
                                if result.get('retained_handle') != 'original-worker-handle':
                                    raise AssertionError(result)
                                if len(effects) != 1 or returned.is_set():
                                    raise AssertionError('worker did not return before manager exit')
                                returned.set()
                                return {'outcome': 'succeeded'}
                            time.sleep(.01)
                        raise AssertionError('first manager cannot receive ordinary worker response')
                    return ExecutionHost.external_call(native_wait)
                if request['command'] == 'run-worker':
                    if threading.get_ident() != identities['owner'] or returned.is_set():
                        raise AssertionError('nested effect left serialized owner custody')
                    effects.append(request)
                    return {'outcome': 'admitted', 'retained_handle': 'original-worker-handle'}
                raise AssertionError(request)
            host = ExecutionHost(directory=root, handler=handler,
                                 owner_path=root / 'owner.json', socket_path=None)
            try:
                host.start()
                (root / 'request-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json').write_text(json.dumps({'command': 'start-manager'}))
                self.assertTrue(returned.wait(5), 'manager self-wait blocked ordinary worker ingress')
                self.assertEqual(len(effects), 1)
                self.assertNotEqual(identities['transport'], identities['owner'])
            finally:
                host.close()

    def test_exact_pre_effect_held_notification_rearms_same_handle_preserving_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {"command": "manager-worker-result", "task": "S01",
                       "principal": "original-worker", "schedule_id": "original-schedule"}
            encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
            token = hashlib.sha256(encoded.encode()).hexdigest()
            response = root / ("response-" + token + ".json")
            raw = json.dumps({"outcome": "held", "provider_called": False, "effects_started": False,
                "retry": False, "reason": "reconcile the retained manager effect before worker-result continuation"}).encode()
            response.write_bytes(raw)
            host = ExecutionHost(directory=root, handler=lambda request: None)
            with self.assertRaises(ValueError):
                host.rearm_pre_effect_worker_notification(request, expected_response_sha256="0" * 64)
            self.assertEqual(response.read_bytes(), raw)
            result = host.rearm_pre_effect_worker_notification(request,
                expected_response_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(result["retained_handle"], token)
            self.assertEqual(Path(result["source_response_path"]).read_bytes(), raw)
            self.assertFalse(response.exists())
            self.assertEqual(json.loads((root / ("request-" + token + ".json")).read_text()), request)
            self.assertTrue(host.rearm_pre_effect_worker_notification(request,
                expected_response_sha256=hashlib.sha256(raw).hexdigest())["replayed"])

    def test_exact_binding_preparation_error_rearms_observation_not_worker_execution(self):
        request = {'command': 'manager-worker-result', 'task': 'D04', 'principal': 'worker', 'schedule_id': 'worker-d04'}
        token = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = root / ('response-' + token + '.json')
            host = ExecutionHost(directory=root, handler=lambda _: self.fail('rearm must not dispatch'))
            base = {'outcome': 'error', 'error': 'OccurrencePreparationError',
                'message': 'native session has no current owner assignment binding',
                'next_action': 'inspect the exact canonical request before retry'}
            for changed in ({**base, 'error': 'UnknownProviderError'}, {**base, 'outcome': 'unknown'}):
                raw = json.dumps(changed).encode(); response.write_bytes(raw)
                with self.assertRaises(ValueError):
                    host.rearm_pre_effect_worker_notification(request, expected_response_sha256=hashlib.sha256(raw).hexdigest())
                self.assertEqual(response.read_bytes(), raw)
            raw = json.dumps(base).encode(); response.write_bytes(raw)
            result = host.rearm_pre_effect_worker_notification(request, expected_response_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(Path(result['source_response_path']).read_bytes(), raw)
            self.assertEqual(json.loads((root / ('request-' + token + '.json')).read_text()), request)
            self.assertFalse(result['provider_called'])

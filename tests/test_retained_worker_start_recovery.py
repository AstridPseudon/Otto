"""Canonical unattempted worker recovery, with real retained native fixture effects."""
import hashlib
import json
from pathlib import Path
import unittest
from otto.portfolio.execution_host import ExecutionHost
from tests import test_execution_application as fixtures

class RetainedStartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ExecutionApplicationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=Path(self.f.temporary.name)/'ipc';self.root.mkdir()
        self.host=ExecutionHost(directory=self.root,handler=lambda request:None)
        prepared=self.f.app.assign_worker(**self.f.request())
        self.request={'command':'start-retained-worker','task':'D01','principal':'worker','schedule_id':prepared['schedule_id']}
        self.token=hashlib.sha256(json.dumps(self.request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.response=self.root/('response-'+self.token+'.json')
        self.raw=(json.dumps({'correlation_id':self.token,'outcome':'error','error':'OccurrencePreparationError','message':'manual selector predecessor effects require reconciliation','next_action':'inspect the exact canonical request before retry'})+'\n').encode()
        self.response.write_bytes(self.raw);self.sha=hashlib.sha256(self.raw).hexdigest()
    def recover(self):
        return self.host.rearm_pre_effect_worker_start(self.request,application=self.f.app,expected_response_sha256=self.sha)
    def test_same_worker_one_effect_history_and_idempotent_rearm(self):
        before=self.f.port.read_due(self.request['schedule_id'])
        result=self.recover();self.assertEqual(result['retained_handle'],self.token)
        self.assertEqual(Path(result['source_response_path']).read_bytes(),self.raw)
        self.assertEqual(self.f.port.read_due(self.request['schedule_id']),before)
        self.assertFalse(self.response.exists());self.assertTrue(self.recover()['replayed'])
        self.assertEqual(self.f.provider.calls,[])
        started=self.f.app.start(schedule_id=self.request['schedule_id'])
        self.assertEqual(started['outcome'],'succeeded',started)
        self.assertEqual(self.f.app.start(schedule_id=self.request['schedule_id'])['outcome'],'replayed')
        self.assertEqual(len(self.f.provider.calls),1)
        with self.assertRaises(PermissionError):self.recover()
    def test_foreign_principal_and_changed_hash_leave_history_untouched(self):
        with self.assertRaises(PermissionError):
            self.host.rearm_pre_effect_worker_start({**self.request,'principal':'foreign'},application=self.f.app,expected_response_sha256=self.sha)
        with self.assertRaises(ValueError):
            self.host.rearm_pre_effect_worker_start(self.request,application=self.f.app,expected_response_sha256='0'*64)
        self.assertEqual(self.response.read_bytes(),self.raw)
        self.assertEqual(self.f.provider.calls,[])
    def test_unknown_native_effect_cannot_rearm_even_with_validation_text(self):
        self.f.provider.unknown=True
        self.f.app.start(schedule_id=self.request['schedule_id'])
        with self.assertRaises(PermissionError):self.recover()
        self.assertEqual(self.response.read_bytes(),self.raw)
        self.assertEqual(len(self.f.provider.calls),1)

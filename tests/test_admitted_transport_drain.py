"""A drain cannot reject transport belonging to an already admitted job."""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.owner_completion import after_owner

@dataclass
class Due:
    schedule_id: str = 'original-worker'
    project_ref: str = 'project'
    role: str = 'worker'
    target: object = None
    host_evidence: object = None
    assignment_ref: object = None
    generation: int = 1
    profile: str = 'workspace-write'
    stop_state: str = 'active'
    completion_state: str = 'none'

class AdmittedDrainTests(unittest.TestCase):
    def test_preparation_crossing_drain_preserves_exact_admitted_transport(self):
        with tempfile.TemporaryDirectory() as root:
            entered, release, done = threading.Event(), threading.Event(), threading.Event()
            due=Due(target={},assignment_ref={'authority':'fixture','id':'worker'})
            app=SimpleNamespace(runtime=SimpleNamespace(adapter=SimpleNamespace(worktree=root,owner_transport_only=True)),_read=lambda sid:due)
            calls=[]
            host=ExecutionHost(directory=Path(root)/'ipc',handler=lambda x:None,bounded_transports=True)
            def effect():
                calls.append(threading.get_ident());return 'exact-result'
            def prepare():
                entered.set();self.assertTrue(release.wait(5))
                def capture(value):
                    due.stop_state='completed';due.completion_state='succeeded';return value
                return after_owner(ExecutionHost.adapter_transport(effect),capture)
            host.handler=lambda request:host.admit_execution(app,due,prepare)
            host.start()
            result={}
            def submit():
                value=host._status_read({'command':'fixture'},lambda:host._owned(lambda:host.admit_execution(app,due,prepare)))
                host._status_read({'command':'observe'},lambda:value.then(lambda v:(result.update(value=v),done.set())))
            sender=threading.Thread(target=submit);sender.start()
            try:
                self.assertTrue(entered.wait(5));host.begin_drain()
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host.retain(name='unadmitted',operation=lambda:calls.append('wrong'))
                release.set();self.assertTrue(done.wait(5));sender.join(5)
                self.assertEqual(result,{'value':'exact-result'});self.assertEqual(len(calls),1)
                self.assertEqual(host._external_waiting,0);self.assertEqual(host._capacity_holds,{})
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host._status_read({'command':'new'},lambda:host._owned(lambda:host.admit_execution(app,Due(schedule_id='new',target={},assignment_ref={'authority':'f','id':'new'}),effect)))
            finally:
                release.set();host.close();sender.join(5)
    def test_unadmitted_rejection_releases_wait_counter_and_cannot_forge_job(self):
        with tempfile.TemporaryDirectory() as root:
            host=ExecutionHost(directory=root,handler=lambda x:None,bounded_transports=True);host.start();host.begin_drain()
            try:
                with self.assertRaisesRegex(RuntimeError,'draining'):
                    host._status_read({'command':'fixture'},lambda:host._owned(lambda:ExecutionHost.adapter_transport(lambda:None)))
                self.assertEqual(host._external_waiting,0)
                with self.assertRaises(PermissionError):
                    host.retain(name='forged',operation=lambda:None,_admitted_execution=(host,{'scope':{'schedule_id':'fake'},'running':True}))
            finally:host.close()

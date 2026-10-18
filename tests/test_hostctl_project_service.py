"""One Store/owner lane, shared cap, and retained supervisor policy."""
import hashlib
import json
import plistlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from otto.hostctl import config as host_config, lanes
from otto.hostctl.owner import create_store, HostSession
from otto.hostctl.project_service import ProjectOwnerService
from otto.hostctl.cli import _task_dispatch_status
from otto.hostctl.supervision import launchd_definition
from otto.portfolio.execution_host import CapacityPolicy, ExecutionHost
from tests import test_bounded_project_host as bounded_fixture


class SharedHostAdmissionTests(unittest.TestCase):
    def test_edited_admitted_task_status_names_readmission_and_changed_fields(self):
        from herzchen.contracts import ResourceRef
        from herzchen.domains.work.admission import authoring_stamp

        ref = ResourceRef('owner', 'work.task', 'task-C', 'rev-edited')
        admitted = {'kind': 'task', 'id': 'task-C', 'title': 'Reviewed', 'instructions': 'Old'}
        current = {**admitted, 'instructions': 'Edited'}
        current['metadata_namespaces'] = {'work.admission': authoring_stamp('rev-admitted', admitted, 'reviewer')}

        class Store:
            def get_revision(self, pin):
                self.pin = pin
                return SimpleNamespace(payload=admitted)

        result = _task_dispatch_status({}, task_payload=current, task_ref=ref, store=Store())

        self.assertEqual(result['state'], 'admitted')
        self.assertEqual(result['reason'], 'readmission needed')
        self.assertEqual(result['changed_fields'], ['instructions'])

    def test_status_reports_admitted_turn_limits(self):
        cases = (
            ("default", CapacityPolicy(), (8, 6, 6)),
            ("configured", CapacityPolicy(
                turn_units=4, manager_reserve=1, heavy_headroom=2,
                worker_floor=1), (5, 4, 4)),
        )
        for name, policy, expected in cases:
            with self.subTest(policy=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                config = {
                    "home": str(home),
                    "owner": {"actor": "owner"},
                    "store": {
                        "authority": "status-test",
                        "domain_descriptor_digest": "digest",
                    },
                    "hosts": {},
                    "max_active_manager_turns": policy.manager_units,
                }
                host = SimpleNamespace(
                    bounded_transports=True,
                    capacity=SimpleNamespace(policy=policy),
                    capacity_holds=lambda: {},
                    _executions={},
                    _capacity_holds={},
                )
                router = SimpleNamespace(host=host, store=object(), services={})
                service = ProjectOwnerService(config, router=router)
                capacity = service._status()["native_capacity"]

                self.assertEqual(
                    tuple(capacity[key] for key in (
                        "total_limit", "worker_limit", "manager_limit")),
                    expected,
                )
                self.assertEqual(policy.total_turn_units, expected[0])
                self.assertTrue(policy.admits_turn("worker", expected[1] - 1, 0))
                self.assertFalse(policy.admits_turn("worker", expected[1], 0))
                workers, managers = policy.worker_floor, expected[2]
                self.assertEqual(workers + managers, expected[0])
                self.assertTrue(policy.admits_turn("manager", workers, managers - 1))
                self.assertFalse(policy.admits_turn("manager", workers, managers))
                self.assertTrue(policy.admits_turn("worker", workers - 1, managers))
                self.assertFalse(policy.admits_turn("worker", workers, managers))

    def test_owner_status_gives_retained_hold_a_settling_command(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = {"home": str(home), "owner": {"actor": "owner"},
                "store": {"authority": "hold-status", "domain_descriptor_digest": "digest"},
                "hosts": {}, "max_active_manager_turns": 3}
            policy = CapacityPolicy()
            scope = {"role": "worker", "project": "project-A", "schedule_id": "schedule-A"}
            host = SimpleNamespace(bounded_transports=True, capacity=SimpleNamespace(policy=policy),
                capacity_holds=lambda: {}, _executions={}, _capacity_holds={"schedule-A": scope})
            service = ProjectOwnerService(config, router=SimpleNamespace(host=host, store=object(), services={}))

            action = service._status()["native_capacity"]["hold_actions"][0]

            self.assertEqual(action["schedule_id"], "schedule-A")
            self.assertIn("complete-task", action["settling_command"])
            self.assertIn("project-A", action["next_action"])

    def test_host_admission_borrows_store_and_foreign_project_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            config = host_config.new_installation(home, store_path=str(home/'owner.sqlite'),
                authority='shared-test', owner_actor='owner', operator_actor='human-operator',
                credential_ref='owner-credential', python='/usr/bin/python3')
            config['max_active_manager_turns'] = 3
            created = create_store(config)
            host_config.write(home, config)
            with HostSession(config) as owner:
                host = SimpleNamespace(bounded_transports=True,
                    capacity=SimpleNamespace(policy=CapacityPolicy(turn_units=2, manager_reserve=1, heavy_headroom=1, worker_floor=0)),
                    _executions={}, _capacity_holds={}, capacity_holds=lambda: {}, directory=home/'shared-ipc',
                    _status_read=lambda request, fn: fn())
                router = SimpleNamespace(host=host, store=owner.store, services={})
                service = ProjectOwnerService(config, router=router)
                with patch('herzchen.kernel.store.Store.open', side_effect=AssertionError('second Store opener')):
                    first = service.call(lambda: service._admit_host({'host':'claude-code', 'client_home':str(home/'claude-client')}))
                    repeated = service.call(lambda: service._admit_host({'host':'claude-code', 'client_home':str(home/'claude-client')}))
                    self.assertEqual(first['outcome'], 'admitted')
                    self.assertEqual(repeated['outcome'], 'replayed')
                    self.assertEqual(first['host']['root_assignment_ref'], repeated['host']['root_assignment_ref'])
                    self.assertFalse(first['provider_called'])
                    with self.assertRaises(LookupError):
                        service._view_for('claude-code', 'foreign-project')
                self.assertIs(service.store, owner.store)
                self.assertEqual(service._status()['native_capacity']['manager_limit'],3)
                self.assertEqual(service._status()['store_open_count'],1)
                with self.assertRaisesRegex(RuntimeError,'never open another'):
                    service.run()
                host._capacity_holds['unknown-old']={'role':'worker','project':'old'}
                held=service.call(lambda: self.fail('mutation during uncertain native'),hold_during_turn=True)
                self.assertEqual(held['outcome'],'held')

    def test_three_managers_share_total_three_with_queued_worker(self):
        f=bounded_fixture.BoundedProjectHostTests()
        f.capacity_policy=CapacityPolicy(turn_units=2, manager_reserve=1, heavy_headroom=1, worker_floor=0)  # the former limit 3
        f.setUp()
        try:
            starts={letter:f.send(letter,{'command':'start-manager'}) for letter in 'ABC'}
            f.wait(lambda:all(f.native.has_started('manager-'+letter) for letter in 'ABC'))
            worker=f.delegate('A')
            self.assertEqual(worker['outcome'],'admitted')
            self.assertFalse(f.native.has_started('worker-A'))
            f.native.release('manager-A')
            self.assertEqual(f.response(starts['A'])['outcome'],'succeeded')
            f.wait(lambda:f.native.has_started('worker-A'))
            self.assertFalse(starts['B'].exists()); self.assertFalse(starts['C'].exists())
            self.assertEqual(f.native.peaks['total'],3)
            self.assertEqual(f.native.peaks['manager'],3)
            self.assertEqual(len(set(f.owner_threads)),1)
        finally:
            f.doCleanups()

    def test_launchd_restarts_only_unsuccessful_supervisor_and_pins_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapper=Path(directory)/'waiter.py'; wrapper.write_text('print("closed")\n')
            config={'max_active_manager_turns':3,'owner_composition':{'kind':'shared-project-services',
                'argv':['/usr/bin/python3',str(wrapper)], 'cwd':directory,
                'file_sha256':{str(wrapper):hashlib.sha256(wrapper.read_bytes()).hexdigest()},
                'stdout':str(Path(directory)/'out'), 'stderr':str(Path(directory)/'err')}}
            value=plistlib.loads(launchd_definition(config,label='org.otto.shared-owner'))
            self.assertEqual(value['KeepAlive'],{'SuccessfulExit':False})
            wrapper.write_text('changed')
            with self.assertRaises(PermissionError): launchd_definition(config,label='org.otto.shared-owner')

    def test_fifo_supervisor_forwards_explicit_retained_resume(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            fifo=Path(directory)/'input'; os.mkfifo(fifo,0o600)
            with patch.object(ExecutionHost,'supervise',return_value={'outcome':'held'}) as supervise:
                result=ExecutionHost.supervise_owner_service(argv=['/usr/bin/python3','owner.py'],cwd=directory,
                    stdin_fifo=fifo, log_path=Path(directory)/'log',receipt_path=Path(directory)/'policy',
                    source_identity={'commit':'pin'},reconcile=lambda _: {'ready':False},
                    disposition=lambda:'active',request_stop=lambda _:None,resume=True)
                self.assertEqual(result['outcome'],'held'); self.assertTrue(supervise.call_args.kwargs['resume'])

    def test_resume_cannot_reset_exhausted_restart_count(self):
        with tempfile.TemporaryDirectory() as directory:
            class Process:
                pid=123
                def wait(self,timeout): return 9
            values=dict(argv=['/usr/bin/true'],receipt_path=Path(directory)/'policy',source_identity={'pin':'same'},
                reconcile=lambda _: {'ready':True}, disposition=lambda:'active',request_stop=lambda _:None,
                max_restarts=1,restart_delay=.001,max_restart_delay=.001)
            first=ExecutionHost.supervise(**values,process_factory=lambda *a,**k:Process())
            self.assertEqual(first['outcome'],'restart_exhausted')
            second=ExecutionHost.supervise(**values,resume=True,process_factory=lambda *a,**k:self.fail('reset counter'))
            self.assertEqual(second['outcome'],'restart_exhausted')
            self.assertEqual(second['restart_allowance']['remaining'],0)

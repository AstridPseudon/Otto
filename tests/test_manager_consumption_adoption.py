"""Ordinary consumption continuity; synthetic provider, real owner adoption history."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from herzchen.contracts import ResourceRef
from otto.portfolio.worker_occurrences import manager_consumption_parent
from tests.test_execution_application import ExecutionApplicationTests

class ManagerConsumptionAdoptionTests(unittest.TestCase):
    def setUp(self):
        f = self.f = ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        manager, guide, mandate = f.role_handles('manager', 'manager', 'manager-session')
        prepared = f.app.prepare_role(role='manager', project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=manager.ref.to_dict(), generation=1,
            mandate_ref=mandate, context_refs=(guide, mandate), request_key='original-manager',
            instruction='Inspect this task', model='gpt-test', reasoning='high',
            profile='workspace-write', native_session_id='manager-session')
        self.assertEqual(f.app.start(schedule_id=prepared['schedule_id'])['outcome'], 'succeeded')
        worker = f.app.assign_and_start(**f.request())
        self.assertEqual(worker['outcome'], 'succeeded')
        callback = f.app.continue_manager_from_worker(manager_schedule_id=prepared['schedule_id'],
            worker_schedule_id=worker['schedule_id'], execute=True)
        self.assertEqual(callback['outcome'], 'succeeded', callback)
        self.callback = f.port.read_due(callback['schedule_id'])
        self.child = f.port.read_due(worker['schedule_id'])
        self.manager = manager
        self.guide, self.mandate = guide, mandate

    def prepare_current(self, adoptions=2):
        f = self.f
        manager = self.manager
        for i in range(adoptions):
            manager = f.app.assignments.adopt_resources(manager.ref,
                resources=manager.payload['resource_adoptions'], expected_revision=manager.revision,
                expected_generation=1, logical_request_key='refresh-' + str(i), actor=f.actor)
        prepared = f.app.prepare_role(role='manager', project_ref=f.project.ref.to_dict(),
            task_ref=f.task.ref.to_dict(), assignment_ref=manager.ref.to_dict(), generation=1,
            mandate_ref=self.mandate, context_refs=(self.guide, self.mandate),
            request_key='consume-after-refresh', instruction='Consume original result', model='gpt-test',
            reasoning='high', profile='workspace-write', native_session_id='manager-session',
            binding_schedule_id=self.callback['schedule_id'])
        self.current = f.port.read_due(prepared['schedule_id'])
        self.context = {'role': 'manager', 'assignment_ref': manager.ref.to_dict(), 'generation': 1,
            'occurrence_ref': {'schedule_id': prepared['schedule_id']}, 'native_session': {'id': 'manager-session'}}
        self.service = SimpleNamespace(server=SimpleNamespace(
            state={'assignment_ref': manager.ref.to_dict(), 'manager_generation': 1, 'manager': 'manager'},
            owner=f.owner, portfolio=f.app.portfolio, due_port=f.port))
        return manager

    def test_two_real_resource_adoptions_preserve_original_parent_and_child(self):
        current = self.prepare_current()
        parent = manager_consumption_parent(self.service, self.context, self.child)
        self.assertNotEqual(current.ref.to_dict(), self.callback['assignment_ref'])
        self.assertEqual(parent['assignment_ref'], self.callback['assignment_ref'])
        self.assertEqual(parent['callback_schedule_id'], self.callback['schedule_id'])
        self.assertEqual(parent['child_schedule_id'], self.child['schedule_id'])
        self.assertEqual(self.f.port.read_due(self.callback['schedule_id']), self.callback)

    def test_same_exact_assignment_keeps_existing_path(self):
        self.prepare_current(adoptions=0)
        parent = manager_consumption_parent(self.service, self.context, self.child)
        self.assertEqual(parent['assignment_ref'], self.callback['assignment_ref'])

    def test_missing_consecutive_history_rejects(self):
        self.prepare_current()
        original = self.f.app.portfolio.operations._owner_reader
        class MissingHistory:
            def list_events(inner, **kwargs):
                return tuple(e for e in original.list_events(**kwargs)
                    if e.subject.revision != 'rev-3')
        with patch.object(self.f.app.portfolio.operations, '_owner_reader', MissingHistory()):
            with self.assertRaises(PermissionError):
                manager_consumption_parent(self.service, self.context, self.child)

    def test_changed_generation_rejects(self):
        self.prepare_current()
        self.context['generation'] = self.service.server.state['manager_generation'] = 2
        with self.assertRaises(PermissionError):
            manager_consumption_parent(self.service, self.context, self.child)

    def test_foreign_callback_assignment_cannot_be_rebound_by_a_matching_pin(self):
        self.prepare_current()
        from otto.portfolio.execution import _digest
        callback = dict(self.callback, assignment_ref={**self.callback['assignment_ref'], 'id': 'foreign-manager'})
        current = self.f.port.read_due(self.current['schedule_id'])
        target = dict(current['target'], native_binding={'schedule_id': callback['schedule_id'], 'due_sha256': _digest(callback)})
        forged = dict(current, target=target)
        # The real Due CAS already rejects changing assignment identity.
        # Inject a corrupted read projection to test this independent guard.
        port = self.f.port
        class ForeignReadProjection:
            def read_due(inner, schedule):
                if schedule == callback['schedule_id']:
                    return callback
                if schedule == current['schedule_id']:
                    return forged
                return port.read_due(schedule)
        self.service.server.due_port = ForeignReadProjection()
        with self.assertRaises(PermissionError):
            manager_consumption_parent(self.service, self.context, self.child)

    def test_changed_native_or_pin_rejects_before_consumption(self):
        self.prepare_current()
        for field, value in [('native', 'foreign-native'), ('digest', '0' * 64)]:
            with self.subTest(field=field):
                if field == 'native':
                    context = {**self.context, 'native_session': {'id': value}}
                    with self.assertRaises(PermissionError):
                        manager_consumption_parent(self.service, context, self.child)
                else:
                    current = self.f.port.read_due(self.current['schedule_id'])
                    target = dict(current['target'], native_binding={**current['target']['native_binding'], 'due_sha256': value})
                    self.f.port.save_due(current['schedule_id'], dict(current, target=target), request_id='bad-pin', expected_version=current['version'])
                    with self.assertRaises(PermissionError):
                        manager_consumption_parent(self.service, self.context, self.child)

if __name__ == '__main__':
    unittest.main()

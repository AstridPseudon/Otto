"""Owner issue inventories do not materialize unrelated observation/event bodies."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.domains.work.sheet import _ProjectSheetEngine
from otto.portfolio.owner_issue_loop import OwnerIssueReaders
from tests import test_execution_application as owner_fixture


class IssueMetadataInventoryTests(unittest.TestCase):
    def fixture(self):
        f = owner_fixture.ExecutionApplicationTests(); f.setUp()
        self.addCleanup(f.doCleanups)
        return f

    def test_current_manager_inventory_preserves_eventless_scopes_without_full_export(self):
        f = self.fixture()
        port = f.owner.assignments.command_port
        manager = port.assign(f.project.ref, role='manager', principal='manager', manager='manager',
            pins=[], logical_request_key='inventory-manager', actor=f.actor)
        child = port.assign(f.task.ref, role='worker', principal='child', manager='manager',
            pins=[], logical_request_key='inventory-child', actor=f.actor)
        foreign = ResourceRef(f.store.authority, 'wrk.assignment', 'foreign-scope', 'rev-1')
        f.store.put_identity(foreign, {'scope': {**f.project.ref.to_dict(), 'authority': 'elsewhere'},
            'body': 'x' * 32768})
        legacy = ResourceRef(f.store.authority, 'wrk.assignment', 'eventless-assignment', 'rev-1')
        f.store.put_identity(legacy, {'scope': {**f.task.ref.to_dict(), 'revision': 'historical'}})
        port.append_report(manager.ref, {'schema': 'otto.checkin.v1', 'body': 'x' * 262144},
            expected_generation=1, logical_request_key='inventory-large-report', actor=f.actor)
        expected = {manager.ref.id, child.ref.id, legacy.id}
        # Every legacy full export route is forbidden, including decision/DAT
        # and observation joins. This fixture still uses the actual WRK port.
        with patch.object(_ProjectSheetEngine, 'export', side_effect=AssertionError('full sheet')):
            inventory = f.owner.sheet.assignment_inventory(f.project.ref)
            self.assertEqual({r['id'] for r in inventory['assignment_refs']}, expected)
            self.assertEqual(inventory['task_refs'], (f.task.ref.to_dict(),))
            reader = OwnerIssueReaders(f.owner.consumer_operations(), f.port)
            # Current-manager selection never decodes unrelated task-scoped
            # legacy assignment bodies, matching the old project row boundary.
            self.assertEqual(inventory['project_assignment_refs'], (manager.ref.to_dict(),))
            self.assertEqual(reader.current_manager(f.project.ref.to_dict()).ref, manager.ref)

    def test_event_subject_metadata_matches_complete_events_without_effects_decode(self):
        f = self.fixture(); port = f.owner.assignments.command_port
        manager = port.assign(f.project.ref, role='manager', principal='manager', manager='manager',
            pins=[], logical_request_key='metadata-manager', actor=f.actor)
        for n in range(4):
            port.append_report(manager.ref, {'body': 'x' * 262144}, expected_generation=1,
                logical_request_key='metadata-report-' + str(n), actor=f.actor)
        stream = 'report:' + manager.ref.id
        expected = tuple(event.subject for event in f.store.list_events(stream=stream))
        sql = []
        f.store._connection.set_trace_callback(sql.append)
        try:
            with patch.object(type(f.store), '_event_from_row', side_effect=AssertionError('body decode')):
                actual = f.store.consumer().list_event_subjects(stream=stream)
        finally:
            f.store._connection.set_trace_callback(None)
        self.assertEqual(actual, expected)
        self.assertTrue(sql)
        self.assertFalse(any('effects_json' in q or 'SELECT e.*' in q for q in sql))
        self.assertEqual(f.store.list_event_subjects(stream='missing'), ())
        with self.assertRaises(ValueError): f.store.list_event_subjects(stream='')

    def test_reports_use_inventory_and_metadata_preserving_old_and_result_bodies(self):
        project = ResourceRef('owner', 'work.project', 'project', 'rev-3')
        manager = ResourceRef('owner', 'wrk.assignment', 'manager', 'rev-4')
        old = ResourceRef('owner', 'wrk.assignment', 'old', 'rev-1')
        refs = [ResourceRef('owner', kind, ident, 'rev-1') for kind, ident in
            [('wrk.report', 'checkin'), ('wrk.result', 'result'), ('wrk.report', 'old-help')]]
        values = [{'schema': 'otto.checkin.v1'}, {'schema': 'arbitrary-retained-result', 'body': 'keep'},
                  {'schema': 'otto.issue.v1'}]
        records = {r.id: NS(ref=r, version=1, payload={'assignment': manager.to_dict(),
            'observation_kind': 'result' if r.kind=='wrk.result' else 'report',
            'generation': 1, 'value': {**v, 'project_ref': project.to_dict()}})
            for r, v in zip(refs, values)}
        calls = []
        def subjects(*, stream):
            calls.append(stream)
            return {'report:manager': [refs[0]], 'result:manager': [refs[1]],
                    'report:old': [refs[2]]}.get(stream, [])
        def events(*, stream, subjects):
            self.assertEqual(stream, 'work:project')
            return [NS(before_refs=(old,), after_refs=(manager,), effects={})]
        operations = NS(sheet_port=NS(assignment_inventory=lambda ref:
            {'task_refs': (), 'assignment_refs': (manager.to_dict(),)},
            export=lambda ref: self.fail('full sheet export')),
            _owner_reader=NS(list_event_subjects=subjects, list_events=events,
                             get_record=lambda ref: records[ref.id]))
        reader = OwnerIssueReaders(operations, None)
        reader.project = lambda ref: NS(ref=project, payload={})
        actual = reader.reports(project.to_dict())
        self.assertEqual({r['ref']['id'] for r in actual}, set(records))
        self.assertEqual(next(r for r in actual if r['ref']['id']=='result')['value']['body'], 'keep')
        self.assertIn('result:old', calls)


if __name__ == '__main__': unittest.main()

"""SL11: clean-close at completion, as an owner operation.

Real Store, real Due port, real full admission. Projects are rows of kind
``work.project`` whose lifecycle decides what may be reclaimed.
"""
import json
import logging
import sqlite3
import unittest
from unittest import mock

from herzchen.contracts import ResourceRef
from herzchen.kernel.store import Store
from otto.agents.clean_close import CleanClose, SCHEMA, STRIP_PATHS
from otto.attention import due_record_contribution

from tests import test_transcript_once as tt


def project_ref(name):
    return ResourceRef('owner', 'work.project', name)


class CleanCloseFixture(tt.Fixture):
    def setUp(self):
        super().setUp()
        self.store = self.open_store()
        self.bodies_ = self.bodies()
        self.legacy_port = self.port(self.store)                   # inline (pre-SL9) transcripts
        self.file_port = self.port(self.store, self.bodies_)       # file-backed transcripts

    def project(self, name, lifecycle):
        self.store.put_identity(project_ref(name), {'lifecycle': lifecycle, 'title': name}, version=1)

    def record(self, name, schedule):
        value = self.base_record()
        value['schedule_id'] = schedule
        value['project_ref'] = name
        value['target']['project_ref'] = project_ref(name).to_dict()
        value['assignment_ref'] = {'authority': 'owner', 'kind': 'wrk.assignment', 'id': 'attempt-' + schedule,
                                   'revision': 'rev-1'}
        self.store.put_identity(ResourceRef.from_dict(value['assignment_ref']), {'generation': 2}, version=1)
        return value

    def history(self, name, schedule, port):
        """Save the ~10 phases of one callback's life for one project."""
        base = self.record(name, schedule)
        for i, step in enumerate(self.phases()):
            record = json.loads(json.dumps(base))
            record['host_evidence'] = json.loads(json.dumps(step['host_evidence']))
            attempt = record['host_evidence'].get('gateway_attempt')
            if attempt:
                attempt['delivery_authorization']['assignment_ref'] = base['assignment_ref']
            record['version'] = i
            port.save_due(schedule, record, request_id='%s-%d' % (schedule, i), expected_version=i)

    def snapshot(self, project_name):
        """Every row that belongs to one project's due records, byte for byte."""
        c = self.store.connection
        ids = [r[0] for r in c.execute(
            "SELECT id FROM identities WHERE kind='otto.due-record' AND json_extract(payload_json,'$.project_ref')=?",
            (project_name,))]
        marks = ','.join('?' * len(ids))
        return (c.execute("SELECT id, payload_json, version, current_revision, updated_at FROM identities "
                          "WHERE kind='otto.due-record' AND id IN (%s) ORDER BY id" % marks, ids).fetchall(),
                c.execute("SELECT event_id, effects_json, append_position FROM events WHERE subject_kind='otto.due-record' "
                          "AND subject_id IN (%s) ORDER BY append_position" % marks, ids).fetchall())

    def everything(self):
        c = self.store.connection
        return [(t, c.execute('SELECT * FROM %s ORDER BY 1,2,3' % t).fetchall()) for t in ('identities', 'events')]

    def world(self):
        """done-legacy (completed, inline), done-files (withdrawn, file bodies), live (pending), live2 (active)."""
        self.project('done-legacy', 'completed')
        self.project('done-files', 'withdrawn')
        self.project('live', 'pending')
        self.project('live2', 'active')
        self.history('done-legacy', 'sched-legacy', self.legacy_port)
        self.history('done-files', 'sched-files', self.file_port)
        self.history('live', 'sched-live', self.legacy_port)
        self.history('live2', 'sched-live2', self.file_port)
        return CleanClose(self.store, self.bodies_)

    def has_transcript(self, text):
        return any(path[len('$.'):].split('.')[-1] in ('raw_result', 'task_bound_evidence') and
                   self.store.connection.execute("SELECT 1 WHERE json_type(?, ?) IS NOT NULL", (text, path)).fetchone()
                   for path in STRIP_PATHS)


class CleanCloseTests(CleanCloseFixture):
    def test_clean_close_touches_only_finished_projects(self):
        cc = self.world()
        before_live, before_live2 = self.snapshot('live'), self.snapshot('live2')
        live_files = self.bodies_.files.entries(project_ref('live2').to_dict())
        self.assertTrue(live_files)
        other = [r for r in self.everything()]
        for name in ('live', 'live2'):
            report = cc.run(project_ref(name), dry_run=False)
            self.assertEqual(report['outcome'], 'refused')
        done = cc.run(project_ref('done-legacy'), dry_run=False)
        self.assertEqual(done['outcome'], 'cleaned')
        done = cc.run(project_ref('done-files'), dry_run=False)
        self.assertEqual(done['outcome'], 'cleaned')
        self.assertEqual(self.snapshot('live'), before_live)
        self.assertEqual(self.snapshot('live2'), before_live2)
        self.assertEqual(self.bodies_.files.entries(project_ref('live2').to_dict()), live_files)
        # the finished projects lost their transcripts, and nothing else changed shape
        after = dict(self.everything())
        before = dict(other)
        self.assertEqual(len(after['identities']), len(before['identities']))
        self.assertEqual(len(after['events']), len(before['events']))
        legacy_rows, legacy_events = self.snapshot('done-legacy')
        for row in legacy_rows:
            self.assertFalse(self.has_transcript(row[1]))
            self.assertLess(len(row[1]), 400_000)   # was ~2.5 MB; resource_evidence and artifacts are not clean-close keys
        for event in legacy_events:
            self.assertFalse(self.has_transcript(json.dumps(json.loads(event[1])['record'])))
            self.assertLess(len(event[1]), 400_000)
        self.assertEqual(self.bodies_.files.entries(project_ref('done-files').to_dict()), [])
        # every changed row differs only in the stripped keys
        for old, new in zip(before['identities'], after['identities']):
            if old != new:
                self.assertEqual(old[:6] + old[7:], new[:6] + new[7:])    # all but payload_json equal
                self.assertEqual(old[3], new[3])

    def test_clean_close_store_admits(self):
        cc = self.world()
        for name in ('done-legacy', 'done-files'):
            self.assertEqual(cc.run(project_ref(name), dry_run=False)['outcome'], 'cleaned')
        c = self.store.connection
        events, top = c.execute('SELECT count(*), max(append_position) FROM events').fetchone()
        self.assertEqual(events, top)
        path = self.store.path
        self.store.close()
        reopened = Store.open(path, authority='owner', expected_domains=(due_record_contribution(),), admission='full')
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.admission_report['mode'], 'full')
        self.assertEqual(reopened.connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(reopened.connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        # small inline readers still work after the rewrite
        row = reopened.connection.execute(
            "SELECT json_type(effects_json,'$.record.host_evidence.gateway_attempt.result.context_digest_verified'),"
            "json_extract(effects_json,'$.record.host_evidence.gateway_attempt.delivery_authorization.physical_session_id') "
            "FROM events WHERE subject_id='sched-legacy' ORDER BY append_position DESC LIMIT 1").fetchone()
        self.assertEqual(tuple(row), ('true', tt.SESSION))
        reopened.prepare_identity_lookup_indexes()
        plan = ' '.join(r[3] for r in reopened.connection.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM identities WHERE authority='owner' AND kind='otto.due-record' "
            "AND json_extract(payload_json,'$.target.native_adapter')='claude-code' "
            "AND json_extract(payload_json,'$.host_evidence.gateway_attempt.delivery_authorization.physical_session_id')=?",
            (tt.SESSION,)))
        self.assertIn('identities_due_native_lookup', plan)

    def test_clean_close_dry_run_lists_every_row_and_changes_nothing(self):
        cc = self.world()
        raw_before = self.everything()
        files_before = self.bodies_.files.entries(project_ref('done-files').to_dict())
        marker = self.bodies_.files.purged(project_ref('done-files').to_dict())
        for name in ('done-legacy', 'done-files'):
            report = cc.run(project_ref(name))                       # dry run is the default
            self.assertTrue(report['dry_run'])
            self.assertEqual(report['schema'], SCHEMA)
            self.assertEqual(report['outcome'], 'planned')
            for row in report['rows']:
                self.assertEqual(set(row), {'table', 'key', 'field', 'bytes_before', 'bytes_after'})
                self.assertIn(row['table'], ('identities', 'events'))
                self.assertGreater(row['bytes_before'], row['bytes_after'])
        self.assertEqual(self.everything(), raw_before, 'no row changed')
        self.assertEqual(self.bodies_.files.entries(project_ref('done-files').to_dict()), files_before)
        self.assertEqual(self.bodies_.files.purged(project_ref('done-files').to_dict()), marker)
        legacy = cc.run(project_ref('done-legacy'), dry_run=True)
        files = cc.run(project_ref('done-files'), dry_run=True)
        # every row the real run changes is listed, and nothing else
        self.assertEqual(files['bodies'], [dict(table='native-bodies', key=e['key'], bytes_before=e['bytes'], bytes_after=0)
                                           for e in files_before])
        self.assertTrue(files['bodies'])
        changed = {}
        for name, report in (('done-legacy', legacy), ('done-files', files)):
            real = cc.run(project_ref(name), dry_run=False)
            self.assertEqual(real['rows'], report['rows'])
            self.assertEqual(real['bodies'], report['bodies'])
        after = self.everything()
        listed = {('identities', r['key']) for r in legacy['rows'] + files['rows'] if r['table'] == 'identities'}
        listed_events = {r['key'] for r in legacy['rows'] + files['rows'] if r['table'] == 'events'}
        n_changed_id = sum(1 for a, b in zip(dict(raw_before)['identities'], dict(after)['identities']) if a != b)
        n_changed_ev = sum(1 for a, b in zip(dict(raw_before)['events'], dict(after)['events']) if a != b)
        self.assertEqual(n_changed_id, len(listed))
        self.assertEqual(n_changed_ev, len(listed_events))
        self.assertEqual(legacy['evidence_backend']['status'], 'not-applicable')

    def test_clean_close_runs_on_completion_and_is_idempotent(self):
        cc = self.world()
        # the hook is what the lifecycle transition calls; a failure there never raises
        owner = mock.Mock()
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        hook = PortfolioOwnerBootstrap.project_finished
        owner.on_project_finished = cc.on_finished
        hook(owner, project_ref('done-legacy'))
        self.assertEqual(self.snapshot('done-legacy')[0][0][1].count('raw_result'), 0)
        first = self.everything()
        again = cc.run(project_ref('done-legacy'), dry_run=False)
        self.assertEqual(again['outcome'], 'nothing-to-do')
        self.assertEqual((again['totals']['rows'], again['totals']['bodies']), (0, 0))
        hook(owner, project_ref('done-legacy'))
        self.assertEqual(self.everything(), first, 'the second run changed nothing')
        # file-backed project: twice as well
        self.assertEqual(cc.run(project_ref('done-files'), dry_run=False)['outcome'], 'cleaned')
        files_state = self.everything()
        self.assertEqual(cc.run(project_ref('done-files'), dry_run=False)['outcome'], 'nothing-to-do')
        self.assertEqual(self.everything(), files_state)

    def test_failure_never_blocks_the_transition(self):
        cc = self.world()
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        owner = mock.Mock()
        owner.on_project_finished = cc.on_finished
        before = self.everything()
        with mock.patch.object(CleanClose, '_bodies', side_effect=OSError('disk')), \
                self.assertLogs('otto.clean_close', level=logging.WARNING):
            # does not raise ...
            PortfolioOwnerBootstrap.project_finished(owner, project_ref('done-files'))
        # ... and the rewrite is not left half done: the rows were stripped (committed), bodies remain for a manual run
        self.assertTrue(self.bodies_.files.entries(project_ref('done-files').to_dict()))
        retry = cc.run(project_ref('done-files'), dry_run=False)
        self.assertEqual(retry['outcome'], 'cleaned')
        self.assertEqual(self.bodies_.files.entries(project_ref('done-files').to_dict()), [])
        # a verification failure rolls the whole rewrite back
        self.project('done-bad', 'completed')
        self.history('done-bad', 'sched-bad', self.legacy_port)
        snapshot = self.everything()
        with mock.patch('otto.agents.clean_close.EVENT_AFTER', 'effects_json'):
            with self.assertRaises(RuntimeError):
                cc.run(project_ref('done-bad'), dry_run=False)
        self.assertEqual(self.everything(), snapshot)
        del before

    def test_reopened_project_reads_after_clean_close(self):
        cc = self.world()
        for name in ('done-legacy', 'done-files'):
            cc.run(project_ref(name), dry_run=False)
        # reopened: lifecycle goes back to active; reads and further saves work
        for name in ('done-legacy', 'done-files'):
            self.store.connection.execute(
                "UPDATE identities SET payload_json=json_set(payload_json,'$.lifecycle','active') WHERE kind='work.project' AND id=?",
                (name,))
        for schedule, port in (('sched-legacy', self.legacy_port), ('sched-files', self.file_port)):
            current = port.read_due(schedule)
            result = current['host_evidence']['gateway_attempt']['result']
            self.assertNotIn('raw_result', result)
            self.assertNotIn('task_bound_evidence', result)
            self.assertEqual(result['context_digest_verified'], True)
            self.assertEqual(current['schedule_id'], schedule)
            port.read_due(schedule, hydrate_native=False)
            current = dict(current, version=current['version'] + 1, message='resumed')
            saved = port.save_due(schedule, current, request_id='resume-' + schedule, expected_version=current['version'] - 1)
            self.assertEqual(saved['message'], 'resumed')
        self.assertEqual(cc.run(project_ref('done-files'))['outcome'], 'refused', 'a reopened project is not cleaned')
        # the file-backed captured artifacts read as absent, not as an error
        files = self.file_port.read_due('sched-files')
        self.assertEqual([sorted(a) for a in files['host_evidence']['captured_artifacts']], [['path']] * 3)
        listing = self.file_port.list_due({'native_adapter': 'claude-code', 'native_session_id': tt.SESSION})
        self.assertIn('sched-files', [r['schedule_id'] for r in listing])


class HostSessionWiringTests(CleanCloseFixture):
    def test_host_session_installs_clean_close_as_the_finished_hook(self):
        from otto.hostctl import config as host_config
        from otto.hostctl.owner import HostSession, create_store
        config = host_config.new_installation(self.dir / 'home', store_path=str(self.dir / 'host.sqlite'), authority='owner',
                                              owner_actor='owner', operator_actor='human-operator',
                                              credential_ref='credential', python='python3')
        with HostSession(create_store(config)) as session:
            self.assertIsInstance(session.clean_close, CleanClose)
            self.assertEqual(session.owner.on_project_finished, session.clean_close.on_finished)
            session.store.put_identity(project_ref('p'), {'lifecycle': 'completed'}, version=1)
            report = session.clean_close.run(project_ref('p'))
            self.assertEqual((report['dry_run'], report['outcome']), (True, 'planned'))   # marker still to write
            self.assertEqual(session.owner.project_finished(project_ref('p'))['outcome'], 'cleaned')   # writes the purge marker
            self.assertEqual(session.owner.project_finished(project_ref('p'))['outcome'], 'nothing-to-do')


class EvidenceBackendTests(CleanCloseFixture):
    def test_evidence_backend_is_reported_out_of_scope(self):
        self.project('p', 'completed')
        fake = mock.Mock(files=None, evidence=object())
        report = CleanClose(self.store, fake).run(project_ref('p'))
        self.assertEqual(report['evidence_backend']['status'], 'out_of_scope')
        self.assertIn('reclaim_preview', report['evidence_backend']['reason'])


if __name__ == '__main__':
    unittest.main()


class FinishProjectTriggerTests(unittest.TestCase):
    """The real finish-project path (real lifecycle transitions) fires clean-close once the project is completed."""

    def setUp(self):
        import sys
        from pathlib import Path
        controller = str(Path(__file__).resolve().parents[1] / 'install' / 'controller')
        if controller not in sys.path:
            sys.path.append(controller)          # completion_intent_selection, as the journey suite arranges
        from tests import test_manager_journey_command as journey
        self.journey = journey.ManagerJourneyCommandTests('close')
        self.journey.setUp()
        self.addCleanup(self.journey.doCleanups)

    def seed_due(self, store, project_id):
        payload = {'schedule_id': 'seed', 'project_ref': project_id,
                   'host_evidence': {'gateway_attempt': {'result': {'context_digest_verified': True,
                                                                    'raw_result': {'stdout': 'x' * 50_000},
                                                                    'task_bound_evidence': {'t': 'y' * 50_000}}}}}
        store.put_identity(ResourceRef(store.authority, 'otto.due-record', 'seed'), payload, version=1)

    def test_finish_project_cleans_the_project_it_completes(self):
        j = self.journey
        owner = j.application.owner
        project = j.application.project.ref
        self.seed_due(owner.store, project.id)
        seen = []
        owner.on_project_finished = lambda ref: (seen.append(ref), CleanClose(owner.store).on_finished(ref))
        j.complete_required()
        self.assertEqual(seen, [], 'not fired while the project is pending')
        result = j.close('finish-trigger')
        self.assertEqual(result['outcome'], 'completed', result)
        self.assertTrue(seen)
        row = owner.store.connection.execute(
            "SELECT payload_json FROM identities WHERE kind='otto.due-record' AND id='seed'").fetchone()[0]
        self.assertNotIn('raw_result', row)
        self.assertEqual(json.loads(row)['host_evidence']['gateway_attempt']['result']['context_digest_verified'], True)

    def test_a_failing_hook_does_not_undo_completion(self):
        j = self.journey
        j.application.owner.on_project_finished = mock.Mock(side_effect=RuntimeError('boom'))
        j.complete_required()
        with self.assertLogs('otto.clean_close', level=logging.WARNING):
            result = j.close('finish-boom')
        self.assertEqual(result['outcome'], 'completed')
        self.assertEqual(result['readback']['lifecycle'], 'completed')

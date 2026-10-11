"""Portfolio dependency commands through real host and owner file lanes."""
import json
from pathlib import Path
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from otto.hostctl import config as host_config, lanes
from otto.hostctl.owner import HostSession
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from test_hostctl_cli import HostctlFixture, _write_bundle


class HostctlPortfolioTests(HostctlFixture):
    def setUp(self):
        super().setUp()
        self._init()
        self._register()
        other_bundle = Path(self.bundle).parent / 'contracts'
        other_bundle.mkdir()
        _write_bundle(str(other_bundle))
        run = json.loads((other_bundle / 'run.json').read_text())
        run['run_id'] = 'contracts'
        (other_bundle / 'run.json').write_text(json.dumps(run))
        code, receipt = self._ottoctl('project', 'register', '--bundle', str(other_bundle), '--worktree', self.worktree)
        self.assertEqual(code, 0, receipt)
        self.upstream = receipt['project_ref']
        def seed(session):
            return session.owner.graph.create_gate(self.upstream, alias='contracts-frozen', logical_request_key='contracts-gate')
        self.gate = self._owner(seed)

    def _owner(self, callback):
        def run():
            config = host_config.load(Path(self.home))
            with HostSession(config, host=config['hosts']['claude-code']) as session:
                return callback(session)
        return self.owner_service.call(run)

    def test_host_lane_blocked_activation_precedes_materialization_and_override_is_retained(self):
        code, linked = self._ottoctl('project', 'depend', '--project', 'demo-run', '--on', 'contracts#contracts-frozen')
        self.assertEqual(code, 0, linked)
        self.assertEqual(linked['readiness']['status'], 'blocked')
        with patch('otto.hostctl.register.materialize') as materialize:
            code, blocked = self._ottoctl('project', 'activate', '--project', 'demo-run', '--worktree', self.worktree)
            self.assertNotEqual(code, 0)
            self.assertEqual(blocked['error']['code'], 'project_readiness_blocked')
            materialize.assert_not_called()
        # Setup adoption invokes unrelated OS preflight; materialization remains real.
        with patch('otto.hostctl.cli._compose_setup', return_value={'outcome': 'test_prepared'}):
            code, activated = self._ottoctl('project', 'activate', '--project', 'demo-run', '--worktree', self.worktree,
                '--override-readiness', '--reason', 'Approved integration skeleton')
        self.assertEqual(code, 0, activated)
        self.assertEqual(activated['outcome'], 'prepared')
        self.assertEqual(activated['readiness']['outcome'], 'overridden')
        code, read = self._ottoctl('project', 'dependencies', '--project', 'demo-run')
        self.assertEqual(code, 0, read)
        self.assertEqual(read['override']['reason'], 'Approved integration skeleton')
        self.assertFalse(read['ready'])
        from otto.hostctl.cli import _resolve_project
        current = self._owner(lambda session: _resolve_project(session, 'demo-run'))
        self.assertTrue(current.payload['tasks'], 'override must reach real task materialization')

    def test_gate_completion_and_dependency_removal_are_visible_through_lanes(self):
        code, _ = self._ottoctl('project', 'depend', '--project', 'demo-run', '--on', 'contracts#contracts-frozen')
        self.assertEqual(code, 0)
        self._owner(lambda session: session.owner.graph.set_lifecycle(self.gate.ref, 'completed', logical_request_key='gate-passed'))
        code, read = self._ottoctl('project', 'dependencies', '--project', 'demo-run')
        self.assertEqual(code, 0, read)
        self.assertTrue(read['ready'])
        code, removed = self._ottoctl('project', 'depend', '--project', 'demo-run', '--on', 'contracts#contracts-frozen', '--remove')
        self.assertEqual(code, 0, removed)
        self.assertEqual(removed['outcome'], 'removed')
        self.assertEqual(removed['readiness']['dependencies'], [])

    def test_forged_owner_flags_do_not_cross_portfolios(self):
        def seed(session):
            portfolio = ResourceRef(session.store.authority, 'wrk.portfolio', 'foreign')
            root = session.owner.assignments.assign(portfolio, role='orchestrator', principal='foreign-principal', logical_request_key='foreign-root')
            owner = PortfolioOwnerBootstrap(session.store, binding=session.binding, owner_actor=session.owner.owner_actor.actor,
                portfolio_ref=portfolio, main_assignment_ref=root.ref)
            project = owner.graph.create_project(title='Foreign project', logical_request_key='foreign-project')
            owner.consumer_operations().execute('work.orchestrator.projects.attach', {
                'target_assignment_ref': root.ref.to_dict(), 'target_assignment_revision': root.revision,
                'target_assignment_generation': root.generation,
                'projects': [{'project_ref': project.ref.to_dict(), 'project_version': project.version,
                              'assignment_ref': None, 'assignment_revision': None, 'assignment_generation': None}]},
                request_id='foreign-attach', actor=session.owner.owner_actor.actor)
            return project
        foreign = self._owner(seed)
        config = host_config.load(Path(self.home))
        lane = Path(config['hosts']['claude-code']['lane'])
        request = {'schema': lanes.REQUEST_SCHEMA, 'command': 'project', 'sub': 'depend',
                   'args': {'project': foreign.id, 'on': 'contracts', 'remove': False,
                            'owner_authorized': True, 'host': 'foreign', 'portfolio': 'foreign'}}
        token = lanes.submit(lane, request)
        result = lanes.wait(lane, token, timeout_seconds=10)
        self.assertEqual(result['outcome'], 'error', result)
        self.assertIn('portfolio', json.dumps(result).lower())
        current = self._owner(lambda session: session.owner.graph.get(foreign.ref))
        self.assertEqual(current.dependencies, ())

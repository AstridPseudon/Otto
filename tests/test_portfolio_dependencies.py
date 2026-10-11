import tempfile
import unittest
from pathlib import Path

from herzchen.contracts import ResourceRef
from herzchen.domains.work.model import GraphCycleError, WorkValidationError
from herzchen.kernel import Store
from otto.hostctl.owner import host_domains
from otto.portfolio.dependencies import PortfolioDependencies, identity
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class PortfolioDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / 'owner.sqlite', authority='owner')
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(host_domains())
        self.binding = HerzchenBindingConfig('owner', 'credential')
        self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor='owner')
        self.portfolio = ResourceRef('owner', 'wrk.portfolio', 'portfolio')
        self.root = self.owner.assignments.assign(self.portfolio, role='orchestrator', principal='orchestrator', logical_request_key='root')
        self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor='owner',
            portfolio_ref=self.portfolio, main_assignment_ref=self.root.ref)
        self.graph = self.owner.graph
        self.projects = [self.graph.create_project(title='Project ' + str(i), logical_request_key='project-' + str(i)) for i in range(3)]
        self.owner.consumer_operations().execute('work.orchestrator.projects.attach', {
            'target_assignment_ref': self.root.ref.to_dict(), 'target_assignment_revision': self.root.revision,
            'target_assignment_generation': self.root.generation,
            'projects': [{'project_ref': p.ref.to_dict(), 'project_version': p.version,
                          'assignment_ref': None, 'assignment_revision': None, 'assignment_generation': None} for p in self.projects]},
            request_id='attach', actor='owner')
        self.deps = PortfolioDependencies(self.graph, self.store.consumer(),
            actor=self.binding.authenticated_actor('orchestrator'), owner_actor=self.owner.owner_actor,
            portfolio_ref=self.portfolio)
        self.gate = self.graph.create_gate(self.projects[0].ref, alias='contracts-frozen', logical_request_key='gate')

    def test_projects_and_gates_flip_readiness_on_completion(self):
        self.deps.change(self.projects[1], self.gate, request_id='link-gate')
        self.deps.change(self.projects[2], self.projects[0], request_id='link-project')
        self.assertEqual(self.deps.readiness(self.projects[1])['status'], 'blocked')
        self.assertFalse(self.deps.readiness(self.projects[2])['ready'])
        self.graph.set_readiness(self.gate.ref, {'ready': True, 'status': 'passed'})
        self.assertFalse(self.deps.readiness(self.projects[1])['ready'])
        self.graph.set_lifecycle(self.gate.ref, 'completed')
        self.graph.set_lifecycle(self.projects[0].ref, 'completed')
        self.assertTrue(self.deps.readiness(self.projects[1])['ready'])
        self.assertTrue(self.deps.readiness(self.projects[2])['ready'])
        self.assertEqual(self.deps.resolve_prerequisite(self.projects[0], 'contracts-frozen').id, self.gate.id)
        self.assertEqual(self.deps.resolve_prerequisite(self.projects[0], self.gate.id).id, self.gate.id)

    def test_refuses_wrong_kinds_foreign_portfolio_and_own_gate(self):
        task = self.graph.create_task(self.projects[0].ref, logical_request_key='task')
        foreign = self.graph.create_project(title='Foreign', logical_request_key='foreign')
        for source, target in ((self.projects[1], task), (task, self.projects[0]),
                               (self.projects[1], foreign), (self.projects[0], self.gate)):
            with self.subTest(source=source.id, target=target.id):
                with self.assertRaises(WorkValidationError):
                    self.deps.change(source, target, request_id='invalid-' + source.id + target.id)

    def test_refuses_another_attached_portfolio(self):
        portfolio = ResourceRef('owner', 'wrk.portfolio', 'foreign-portfolio')
        root = self.owner.assignments.assign(portfolio, role='orchestrator', principal='other', logical_request_key='other-root')
        other = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor='owner',
            portfolio_ref=portfolio, main_assignment_ref=root.ref)
        project = other.graph.create_project(title='Other portfolio', logical_request_key='other-project')
        other.consumer_operations().execute('work.orchestrator.projects.attach', {
            'target_assignment_ref': root.ref.to_dict(), 'target_assignment_revision': root.revision,
            'target_assignment_generation': root.generation,
            'projects': [{'project_ref': project.ref.to_dict(), 'project_version': project.version,
                          'assignment_ref': None, 'assignment_revision': None, 'assignment_generation': None}]},
            request_id='other-attach', actor='owner')
        gate = self.graph.create_gate(project.ref, logical_request_key='other-gate')
        for target in (project, gate):
            with self.assertRaisesRegex(WorkValidationError, 'share a portfolio'):
                self.deps.change(self.projects[1], target, request_id='foreign-' + target.id)

    def test_cycle_reused_and_remove_is_retained_and_replayable(self):
        self.deps.change(self.projects[1], self.projects[0], request_id='link')
        with self.assertRaises(GraphCycleError):
            self.deps.change(self.projects[0], self.projects[1], request_id='cycle')
        with self.assertRaises(GraphCycleError):
            self.deps.change(self.projects[0], self.projects[0], request_id='self-cycle')
        removed = self.deps.change(self.projects[1], self.projects[0], request_id='remove', remove=True)
        self.assertEqual(removed['outcome'], 'removed')
        self.assertTrue(removed['receipt'])
        self.assertTrue(self.deps.readiness(self.projects[1])['ready'])
        replay = self.deps.change(self.projects[1], self.projects[0], request_id='remove', remove=True)
        self.assertTrue(replay['replayed'])

    def test_blocked_activation_and_reason_are_retained(self):
        self.deps.change(self.projects[1], self.gate, request_id='link')
        refused = self.deps.activation_check(self.projects[1], request_id='activate')
        self.assertEqual(refused['error']['code'], 'project_readiness_blocked')
        with self.assertRaises(WorkValidationError):
            self.deps.activation_check(self.projects[1], override=True, reason=' ', request_id='empty')
        allowed = self.deps.activation_check(self.projects[1], override=True, reason='Approved walking skeleton', request_id='override')
        self.assertEqual(allowed['outcome'], 'overridden')
        self.assertIsNotNone(allowed['receipt'])
        observed = self.deps.readiness(self.projects[1])
        self.assertEqual(observed['override']['reason'], 'Approved walking skeleton')
        self.assertFalse(observed['ready'])
        replay = self.deps.activation_check(self.projects[1], override=True, reason='Approved walking skeleton', request_id='override')
        self.assertEqual(replay['receipt']['event_ids'], allowed['receipt']['event_ids'])

    def test_gate_membership_cannot_hide_project_cycle(self):
        self.deps.change(self.projects[1], self.gate, request_id='gate-edge')
        with self.assertRaises(GraphCycleError):
            self.deps.change(self.projects[0], self.projects[1], request_id='gate-project-cycle')
        second_gate = self.graph.create_gate(self.projects[1].ref, logical_request_key='second-gate')
        with self.assertRaises(GraphCycleError):
            self.deps.change(self.projects[0], second_gate, request_id='gate-gate-cycle')

    def test_only_current_orchestrator_and_owner_authorized(self):
        for name in ('manager', 'worker', 'stranger'):
            unauthorized = PortfolioDependencies(self.graph, self.store.consumer(),
                actor=self.binding.authenticated_actor(name), owner_actor=self.owner.owner_actor,
                portfolio_ref=self.portfolio)
            with self.assertRaises(PermissionError):
                unauthorized.change(self.projects[1], self.gate, request_id=name)
        owner = PortfolioDependencies(self.graph, self.store.consumer(), actor=self.owner.owner_actor,
            owner_actor=self.owner.owner_actor, portfolio_ref=self.portfolio)
        self.assertEqual(owner.change(self.projects[1], self.gate, request_id='owner-link')['outcome'], 'linked')

    def test_read_only_status_cache_does_not_write(self):
        self.deps.change(self.projects[1], self.gate, request_id='link')
        before = self.store.consumer().snapshot_counts()
        cache = {}
        self.deps.readiness(self.projects[1], observe=False, cache=cache)
        self.deps.readiness(self.projects[1], observe=False, cache=cache)
        self.assertEqual(self.store.consumer().snapshot_counts(), before)
        self.assertIn(('owner', 'work.gate', self.gate.id), cache)

    def test_finite_binding_preserves_task_refresh_restriction(self):
        operations = self.owner.consumer_operations()
        result = operations.execute('work.project.dependency.link', {
            'project_ref': self.projects[1].ref.to_dict(), 'dependency_ref': self.gate.ref.to_dict()},
            request_id='finite', actor='orchestrator')
        self.assertEqual(result['outcome'], 'linked')
        refused = operations.execute('work.task.dependency-refresh', {
            'task_ref': self.projects[1].ref.to_dict(), 'dependency_ref': self.gate.ref.to_dict()},
            request_id='still-task-only', actor='orchestrator')
        self.assertEqual(refused['outcome'], 'error')


if __name__ == '__main__':
    unittest.main()

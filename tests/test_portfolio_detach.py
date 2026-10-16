import unittest
from types import SimpleNamespace

from herzchen.domains.work.model import WorkValidationError
from otto.hostctl.portfolio_detach import detach_project
from otto.portfolio.shared_documents import sync_portfolio_documents, project_shared_documents
import test_portfolio_dependencies as fixture


class PortfolioDetachTests(unittest.TestCase):
    def setUp(self):
        fixture.PortfolioDependenciesTests.setUp(self)
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor='owner',
            portfolio_ref=self.portfolio, main_assignment_ref=self.root.ref,
            privileged_actor_ids=('orchestrator',))

    def session(self):
        return SimpleNamespace(store=self.store, owner=self.owner, binding=self.binding,
            actor=self.owner.owner_actor, host={'principal': 'orchestrator', 'portfolio_ref': self.portfolio.to_dict(),
                                              'root_generation': self.root.generation},
            host_principal=lambda: 'orchestrator', root_assignment=lambda: self.root)

    def test_detach_revokes_shared_documents_atomically_and_keeps_project(self):
        session = self.session()
        project = self.graph.current(self.projects[1].ref)
        digest = self.store.domain_descriptor_digest
        sync_portfolio_documents(session, self.portfolio, {'files': {'contract.md': 'Frozen contract'}})
        self.assertEqual(project_shared_documents(self.owner, project.ref)['outcome'], 'listed')
        self.deps.change(self.projects[2], project, request_id='downstream')
        result = detach_project(session, project, SimpleNamespace())
        self.assertEqual(result['outcome'], 'detached')
        self.assertTrue(result['document_receipts'])
        self.assertNotIn('otto_orchestrator', self.graph.current(project.ref).payload['metadata'])
        self.assertEqual(project_shared_documents(self.owner, project.ref)['documents'], [])
        self.assertFalse(self.deps.readiness(self.projects[2])['ready'])
        self.deps.change(self.projects[2], project, request_id='remove-detached', remove=True)
        self.assertTrue(self.deps.readiness(self.projects[2])['ready'])
        self.assertEqual(self.store.domain_descriptor_digest, digest)

    def test_in_flight_manager_refuses_before_unlink(self):
        session = self.session()
        project = self.graph.current(self.projects[1].ref)
        sync_portfolio_documents(session, self.portfolio, {'files': {'contract.md': 'Frozen contract'}})
        manager = self.owner.assignments.assign(project.ref, role='manager', principal='manager', logical_request_key='manager')
        from otto.attention import DueRecord, issue_store_due_record_port, due_record_contribution
        due = DueRecord(schedule_id='manager-due', recipient='manager', instruction='coordinate', profile='manager',
            anchor='2026-10-11T10:00:00+00:00', last_covered_slot=0, invocation_identity='invocation',
            due_at='2026-10-11T10:00:00+00:00', project_ref=project.id, role='manager',
            in_flight_request='running', stop_state='active')
        port = issue_store_due_record_port(self.store.domain_handler((due_record_contribution(),)), self.owner.owner_actor)
        port.save_due(due.schedule_id, due.to_dict(), request_id='due', expected_version=0)
        result = detach_project(session, project, SimpleNamespace())
        self.assertEqual(result['error']['code'], 'manager_running')
        self.assertIn('otto_orchestrator', self.graph.current(project.ref).payload['metadata'])
        self.assertTrue(project_shared_documents(self.owner, project.ref)['documents'])

    def test_live_service_turn_refuses_even_before_assignment_projection(self):
        project = self.graph.current(self.projects[1].ref)
        result = detach_project(self.session(), project, SimpleNamespace(service_status={
            'attached_project': {'project_id': project.id}, 'manager_turn_active': True}))
        self.assertEqual(result['error']['code'], 'manager_running')
        self.assertIn('otto_orchestrator', self.graph.current(project.ref).payload['metadata'])

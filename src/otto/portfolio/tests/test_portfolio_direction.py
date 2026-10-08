"""Portfolio direction uses the canonical selected-project join, never a read grant alone."""
from dataclasses import replace
from hashlib import sha256
import unittest
from herzchen.content import ContentRevision
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef
from otto.portfolio.direction import DirectionBindingError
from otto.portfolio.direction_context import read_direction_context
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from . import test_direction_bindings as fixtures


class PortfolioDirectionTests(unittest.TestCase):
    setUp = fixtures.DirectionBindingsTests.setUp
    compose = fixtures.DirectionBindingsTests.compose
    context = fixtures.DirectionBindingsTests.context
    create_document = fixtures.DirectionBindingsTests.create_document

    def setup_portfolio(self):
        portfolio = ResourceRef(self.store.authority, 'wrk.portfolio', 'selected')
        root = self.owner.assignments.assign(portfolio, role='orchestrator', principal='owner', logical_request_key='root')
        subject = ResourceRef.from_dict(root.payload['responsibility_ref'])
        document = self.create_document('root-direction', subject)
        pin = replace(document.ref, revision='rev-1')
        binding = self.directions.bind(subject, document.ref, actor=self.actor, logical_request_key='root-bind')
        self.directions.adopt(subject, pin, expected_binding_ref=binding['binding_ref'], actor=self.actor, logical_request_key='root-adopt')
        base = self.create_document('root-base', subject, role='role_instructions')
        text = 'Shared orchestrator template with exact individual direction'
        body = {'schema': 'herzchen.instructions.v1', 'name': 'BASE', 'entrypoint': 'ORCHESTRATOR.md',
                'instructions': text, 'bundle_digest': sha256(text.encode()).hexdigest(),
                'export_manifest_digest': 'fixture', 'required': True, 'supporting_refs': [pin.to_dict()]}
        revision = ContentRevision(base.ref, 'rev-2', body, self.actor, parent_revision='rev-1')
        self.owner.content.execute(self.owner.content.build_append_revision(self.context('root-base-revision', expected_revision='rev-1'), base, revision))
        root = self.owner.assignments.adopt_resources(root.ref, resources=[{'resource_ref': revision.ref.to_dict(),
              'resource_name': 'BASE', 'content_digest': validate_instruction_content(body), 'required': True}],
              expected_revision=root.revision, expected_generation=root.generation, logical_request_key='root-base-adopt', actor=self.actor)
        owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor='owner', portfolio_ref=portfolio, main_assignment_ref=root.ref)
        project = owner.graph.create_project(title='Queued selected', logical_request_key='queued-selected')
        owner.consumer_operations().execute('work.orchestrator.projects.attach', {
            'target_assignment_ref': root.ref.to_dict(), 'target_assignment_revision': root.revision,
            'target_assignment_generation': root.generation, 'projects': [{'project_ref': project.ref.to_dict(),
            'project_version': project.version, 'assignment_ref': None, 'assignment_revision': None, 'assignment_generation': None}]},
            request_id='enroll', actor='owner')
        return root, subject, pin, owner.graph.get(project.ref)

    def test_adopted_portfolio_direction_is_effective_only_for_canonical_selection(self):
        root, subject, pin, project = self.setup_portfolio()
        resolved = self.directions.resolve(subject, actor=self.actor, assignment_ref=root.ref, expected_generation=1)
        self.assertEqual(resolved['effective_ref'], pin.to_dict())
        context = read_direction_context(self.directions, actor=self.actor, assignment_ref=root.ref.to_dict(), generation=1, project_ref=project.ref.to_dict())
        self.assertEqual(context[-1]['effective_ref'], pin.to_dict())
        self.assertEqual(project.payload['lifecycle'], 'pending')
        with self.assertRaisesRegex(PermissionError, 'enrolled portfolio'):
            read_direction_context(self.directions, actor=self.actor, assignment_ref=root.ref.to_dict(), generation=1, project_ref=self.project.ref.to_dict())
        with self.assertRaisesRegex(PermissionError, 'enrolled portfolio'):
            read_direction_context(self.directions, actor=self.actor, assignment_ref=root.ref.to_dict(), generation=2, project_ref=project.ref.to_dict())
        with self.assertRaises(PermissionError):
            read_direction_context(self.directions, actor=self.binding.authenticated_actor('foreign'), assignment_ref=root.ref.to_dict(), generation=1, project_ref=project.ref.to_dict())

    def test_reassignment_invalidates_old_enrollment_and_nonorchestrator_portfolio_denied(self):
        root, subject, pin, project = self.setup_portfolio()
        replacement = self.owner.assignments.reassign(root.ref, principal='owner', expected_generation=1, logical_request_key='root-replace')
        with self.assertRaisesRegex(PermissionError, 'enrolled portfolio'):
            read_direction_context(self.directions, actor=self.actor, assignment_ref=replacement.ref.to_dict(), generation=2, project_ref=project.ref.to_dict())
        wrong = self.owner.assignments.assign(ResourceRef(self.store.authority, 'wrk.portfolio', 'wrong'), role='manager', principal='owner', logical_request_key='wrong-role')
        with self.assertRaisesRegex(DirectionBindingError, 'orchestrator responsibility'):
            self.directions.read(wrong.ref, actor=self.actor)

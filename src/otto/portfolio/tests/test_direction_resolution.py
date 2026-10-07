"""D02 exact scope/assignment resolution in disposable canonical Stores."""
from dataclasses import replace
from hashlib import sha256
import unittest
import threading

from herzchen.content import ContentRevision
from herzchen.content.model import ContentError
from herzchen.content.instructions import validate_instruction_content
from herzchen.contracts import ResourceRef, ReplayConflictError
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.model import WorkValidationError
from otto.portfolio.direction import DirectionResolutionError, owner_direction_subject
from . import test_direction_bindings as fixtures


class DirectionResolutionTests(unittest.TestCase):
    setUp = fixtures.DirectionBindingsTests.setUp
    compose = fixtures.DirectionBindingsTests.compose
    context = fixtures.DirectionBindingsTests.context
    create_document = fixtures.DirectionBindingsTests.create_document
    bind = fixtures.DirectionBindingsTests.bind

    def append(self, document, number, content):
        revision = ContentRevision(document.ref, 'rev-' + str(number), content, self.actor,
                                   parent_revision='rev-' + str(number - 1))
        self.owner.content.execute(self.owner.content.build_append_revision(
            self.context('append:' + document.ref.id + ':' + str(number), expected_revision=revision.parent_revision),
            document, revision))
        return revision.ref

    def adopt(self, pin=None, key='adopt', subject=None, expected=None, actor=None):
        subject = subject or self.subject
        expected = expected or self.directions.read(subject, actor=self.actor)['binding_ref']
        return self.directions.adopt(subject, pin or replace(self.document.ref, revision='rev-1'),
            expected_binding_ref=expected, actor=actor or self.actor, logical_request_key=key)

    def resolve(self, **kwargs):
        return self.directions.resolve(self.subject, actor=self.actor, **kwargs)

    def assignment_base(self, pins, key='base'):
        guide = self.create_document(key, self.task.ref, role='guide')
        instructions = 'Execute the bounded outcome'
        content = {'schema': 'herzchen.instructions.v1', 'name': key, 'entrypoint': 'WORKER.md',
                   'instructions': instructions, 'bundle_digest': sha256(instructions.encode()).hexdigest(),
                   'export_manifest_digest': 'fixture', 'required': True,
                   'supporting_refs': [pin.to_dict() for pin in pins]}
        revision = self.append(guide, 2, content)
        current = self.owner.assignments.get(self.assignment.ref)
        result = self.owner.assignments.adopt_resources(current.ref, resources=[{
            'resource_ref': revision.to_dict(), 'resource_name': key,
            'content_digest': validate_instruction_content(content), 'required': True}],
            expected_revision=current.revision, expected_generation=current.generation,
            logical_request_key='adopt:' + key, actor=self.binding.authenticated_actor('manager-a'))
        self.assignment = result
        return result

    def test_exact_scope_supporting_inputs_survive_newer_drafts(self):
        support = self.create_document('evidence', self.subject, role='research')
        support_pin = replace(support.ref, revision='rev-1')
        primary = self.append(self.document, 2, {'text': 'Authorized', 'supporting_refs': [support_pin.to_dict()]})
        self.bind()
        self.adopt(primary)
        self.append(self.document, 3, {'text': 'Unadopted draft'})
        self.append(support, 2, {'text': 'New evidence draft'})
        result = self.resolve()
        self.assertEqual(result['effective_ref'], primary.to_dict())
        self.assertEqual(result['scope_adopted_ref'], primary.to_dict())
        self.assertEqual(result['latest_ref']['revision'], 'rev-3')
        self.assertEqual([item['ref'] for item in result['inputs']], [primary.to_dict(), support_pin.to_dict()])
        self.assertEqual(result['inputs'][0]['content']['text'], 'Authorized')
        self.assertTrue(result['pending_scope_adoption'])
        self.assertIsNone(result['delivered_ref'])
        self.assertEqual(result['delivery_status'], 'not_inspected')

    def test_missing_binding_adoption_revision_and_current_access_have_remedies(self):
        with self.assertRaisesRegex(DirectionResolutionError, 'unbound_direction'):
            self.resolve()
        self.bind()
        with self.assertRaisesRegex(DirectionResolutionError, 'unadopted_direction'):
            self.resolve()
        with self.assertRaisesRegex(DirectionResolutionError, 'missing_input'):
            self.adopt(replace(self.document.ref, revision='rev-404'))
        self.adopt()
        # Current metadata governs access even to an old immutable revision.
        self.owner.content.execute(self.owner.content.build_append_revision(
            self.context('revoke', expected_revision='rev-1'), replace(self.document, maintainer='other-owner'),
            ContentRevision(self.document.ref, 'rev-2', {'text': 'Draft'}, self.actor, parent_revision='rev-1')))
        with self.assertRaisesRegex(DirectionResolutionError, 'inaccessible_input'):
            self.resolve()

    def test_scope_adoption_replay_cas_and_identity_are_exact(self):
        initial = self.bind()
        first_pin = replace(self.document.ref, revision='rev-1')
        first = self.adopt(expected=initial['binding_ref'])
        second_pin = self.append(self.document, 2, {'text': 'Next'})
        self.adopt(second_pin, key='next')
        counts = self.store.consumer().snapshot_counts()
        self.assertEqual(self.adopt(first_pin, expected=initial['binding_ref']), first)
        with self.assertRaises(ReplayConflictError):
            self.adopt(second_pin, expected=initial['binding_ref'])
        with self.assertRaisesRegex(DirectionResolutionError, 'stale_binding'):
            self.adopt(first_pin, expected=initial['binding_ref'], key='stale')
        with self.assertRaisesRegex(DirectionResolutionError, 'fixed_identity'):
            self.adopt(replace(self.other.ref, revision='rev-1'), key='changed-document')
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        self.assertEqual(self.resolve()['effective_ref'], second_pin.to_dict())
        self.assertEqual(len(self.store.list_events(stream='direction:' + initial['binding_ref']['id'])), 3)

    def test_scope_authority_is_distinct_from_assignment_adoption(self):
        self.bind()
        for actor in (self.binding.authenticated_actor('manager-a'), self.binding.authenticated_actor('worker-a')):
            with self.assertRaises(PermissionError):
                self.adopt(actor=actor)
        self.adopt()
        pin = self.append(self.document, 2, {'text': 'Not owner adopted'})
        current = self.assignment_base([pin])
        with self.assertRaisesRegex(DirectionResolutionError, 'unauthorized_revision'):
            self.resolve(assignment_ref=current.ref, expected_generation=1)

    def test_assignment_keeps_authorized_old_revision_until_work_refresh(self):
        self.bind()
        old = replace(self.document.ref, revision='rev-1')
        self.adopt(old)
        current = self.assignment_base([old])
        newer = self.append(self.document, 2, {'text': 'New owner direction'})
        self.adopt(newer, key='scope-update')
        result = self.resolve(assignment_ref=current.ref, expected_generation=1)
        self.assertEqual(result['scope_adopted_ref'], newer.to_dict())
        self.assertEqual(result['assignment_adopted_ref'], old.to_dict())
        self.assertEqual(result['effective_ref'], old.to_dict())
        self.assertTrue(result['pending_assignment_application'])
        refreshed = self.assignment_base([newer], key='refreshed-base')
        result = self.resolve(assignment_ref=refreshed.ref, expected_generation=1)
        self.assertEqual(result['effective_ref'], newer.to_dict())
        self.assertFalse(result['pending_assignment_application'])
        with self.assertRaisesRegex(DirectionResolutionError, 'stale_assignment'):
            self.resolve(assignment_ref=current.ref, expected_generation=1)
        replacement = self.owner.assignments.reassign(refreshed.ref, principal='worker-b', session='native-b',
            expected_generation=1, logical_request_key='replace')
        with self.assertRaisesRegex(DirectionResolutionError, 'stale_assignment'):
            self.resolve(assignment_ref=replacement.ref, expected_generation=1)
        resolved = self.resolve(assignment_ref=replacement.ref, expected_generation=2)
        self.assertEqual(resolved['document_ref'], self.document.ref.to_dict())
        self.assertEqual(resolved['effective_ref'], newer.to_dict())

    def test_assignment_missing_conflicting_and_foreign_scope_pins_fail(self):
        self.bind()
        old = replace(self.document.ref, revision='rev-1')
        self.adopt(old)
        current = self.assignment_base([])
        with self.assertRaisesRegex(DirectionResolutionError, 'missing_assignment_direction'):
            self.resolve(assignment_ref=current.ref, expected_generation=1)
        newer = self.append(self.document, 2, {'text': 'New'})
        current = self.assignment_base([old, newer], key='conflicting-base')
        with self.assertRaisesRegex(DirectionResolutionError, 'conflicting_assignment_direction'):
            self.resolve(assignment_ref=current.ref, expected_generation=1)
        another_project = self.owner.graph.create_project(title='Independent', logical_request_key='other-project')
        direction = self.create_document('project-direction', another_project.ref)
        self.bind(direction, subject=another_project.ref, key='project-bind')
        self.adopt(replace(direction.ref, revision='rev-1'), subject=another_project.ref, key='project-adopt')
        with self.assertRaisesRegex(DirectionResolutionError, 'unauthorized_scope'):
            self.directions.resolve(another_project.ref, actor=self.actor, assignment_ref=current.ref, expected_generation=1)

    def test_declared_supporting_inputs_are_bounded_exact_and_nonconflicting(self):
        self.bind()
        cases = [([self.other.ref.to_dict()], 'invalid_pin'),
                 ([replace(self.other.ref, revision='rev-404').to_dict()], 'missing_input'),
                 ([replace(self.other.ref, revision='rev-1').to_dict(), replace(self.other.ref, revision='rev-2').to_dict()], 'conflicting_inputs'),
                 ([replace(self.document.ref, revision='rev-1').to_dict()], 'conflicting_inputs'),
                 ([ResourceRef('foreign', 'dat.content.document', 'source', 'rev-1').to_dict()], 'invalid_pin'),
                 ([replace(self.other.ref, revision='rev-1').to_dict()] * 33, 'invalid_supporting_refs')]
        for number, (refs, error) in enumerate(cases, 2):
            pin = self.append(self.document, number, {'text': 'Candidate', 'supporting_refs': refs})
            counts = self.store.consumer().snapshot_counts()
            with self.assertRaisesRegex(DirectionResolutionError, error):
                self.adopt(pin, key='bad:' + str(number))
            self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_generic_create_target_metadata_and_sheet_edits_do_not_bypass(self):
        self.bind()
        self.adopt()
        content = self.owner.content
        with self.assertRaises(ContentError):
            content.execute(content.build_create_document(self.context('overwrite-document'), self.document,
                ContentRevision(self.document.ref, 'rev-new', {'text': 'Reset'}, self.actor, initial=True)))
        append = content.build_append_revision(self.context('wrong-target', expected_revision='rev-1'), self.other,
            ContentRevision(self.other.ref, 'rev-2', {'text': 'Other'}, self.actor, parent_revision='rev-1'))
        with self.assertRaises(ContentError):
            content.execute(replace(append, target=self.document.ref))
        with self.assertRaises(ContentError):
            content.execute(content.build_append_revision(self.context('change-scope', expected_revision='rev-1'),
                replace(self.document, authoring_scope=owner_direction_subject(self.store.authority)),
                ContentRevision(self.document.ref, 'rev-2', {'text': 'Broader'}, self.actor, parent_revision='rev-1')))
        with self.assertRaises(WorkValidationError):
            ProjectBatches(self.store, actor=self.actor).apply_project_sheet(self.project.ref,
                {'document_changes': [{'document_ref': self.document.ref.to_dict(), 'content': {'text': 'Bypass'}}]},
                logical_request_key='sheet-edit')
        self.assertEqual(self.resolve()['effective_ref']['revision'], 'rev-1')

    def test_authorized_overall_direction_applies_without_universal_hierarchy(self):
        subject = owner_direction_subject(self.store.authority)
        overall = self.create_document('overall', subject)
        pin = replace(overall.ref, revision='rev-1')
        self.bind(overall, subject=subject)
        self.adopt(pin, subject=subject)
        current = self.assignment_base([pin])
        result = self.directions.resolve(subject, actor=self.actor, assignment_ref=current.ref, expected_generation=1)
        self.assertEqual(result['effective_ref'], pin.to_dict())
        self.assertEqual(result['kind'], 'owner')

    def test_competing_scope_adoptions_have_one_cas_winner(self):
        initial = self.bind()
        old = replace(self.document.ref, revision='rev-1')
        new = self.append(self.document, 2, {'text': 'Next'})
        barrier = threading.Barrier(2)
        results, errors = [], []

        def adopt(pin):
            barrier.wait()
            try:
                results.append(self.adopt(pin, key='race:' + pin.revision, expected=initial['binding_ref']))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=adopt, args=(pin,)) for pin in (old, new)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DirectionResolutionError)
        self.assertIn('stale_binding', str(errors[0]))
        self.assertEqual(self.resolve()['effective_ref'], results[0]['ref'])
        self.assertEqual(len(self.store.list_events(stream='direction:' + initial['binding_ref']['id'])), 2)

    def test_pending_inaccessible_scope_inputs_do_not_invalidate_older_assignment(self):
        self.bind()
        old = replace(self.document.ref, revision='rev-1')
        self.adopt(old)
        current = self.assignment_base([old])
        support = self.create_document('new-input', self.subject, role='research')
        support_pin = replace(support.ref, revision='rev-1')
        new = self.append(self.document, 2, {'text': 'Next', 'supporting_refs': [support_pin.to_dict()]})
        self.adopt(new, key='new-input-adoption')
        self.owner.content.execute(self.owner.content.build_append_revision(
            self.context('revoke-new-input', expected_revision='rev-1'), replace(support, maintainer='another-owner'),
            ContentRevision(support.ref, 'rev-2', {'text': 'Private'}, self.actor, parent_revision='rev-1')))
        result = self.resolve(assignment_ref=current.ref, expected_generation=1)
        self.assertEqual(result['effective_ref'], old.to_dict())
        with self.assertRaisesRegex(DirectionResolutionError, 'inaccessible_input'):
            self.resolve()

    def test_draft_update_history_and_replay_keep_one_document_identity(self):
        binding = self.bind()
        self.adopt()
        current_binding = self.directions.read(self.subject, actor=self.actor)["binding_ref"]
        draft = self.directions.save_draft(
            self.subject, {"text": "Draft only"}, actor=self.actor,
            logical_request_key="draft-only", expected_revision="rev-1")
        self.assertFalse(draft["adopted"])
        resolved = self.resolve()
        self.assertEqual(resolved["effective_ref"]["revision"], "rev-1")
        self.assertEqual(resolved["latest_ref"]["revision"], draft["revision_ref"]["revision"])
        replay = self.directions.save_draft(
            self.subject, {"text": "Draft only"}, actor=self.actor,
            logical_request_key="draft-only", expected_revision="rev-1")
        self.assertTrue(replay["replayed"])
        updated = self.directions.update(
            self.subject, draft["revision_ref"], actor=self.actor,
            expected_binding_ref=current_binding, logical_request_key="explicit-update")
        self.assertEqual(updated["outcome"], "updated")
        self.assertEqual(self.resolve()["effective_ref"], draft["revision_ref"])
        self.assertEqual(
            self.directions.update(
                self.subject, draft["revision_ref"], actor=self.actor,
                expected_binding_ref=current_binding, logical_request_key="explicit-update"),
            updated)
        history = self.directions.history(self.subject, actor=self.actor)
        self.assertEqual(history["document_ref"], self.document.ref.to_dict())
        self.assertEqual([item["ref"]["revision"] for item in history["revisions"]], ["rev-1", draft["revision_ref"]["revision"]])
        self.assertEqual(len(history["scope_adoptions"]), 2)
        self.assertEqual(history["scope_adoptions"][0]["adoption"]["ref"]["revision"], "rev-1")
        self.assertEqual(history["scope_adoptions"][1]["adoption"]["ref"], draft["revision_ref"])
        self.assertEqual(history["admitted_evidence"][0][0]["ref"]["revision"], "rev-1")
        self.assertEqual(history["admitted_evidence"][1][0]["ref"], draft["revision_ref"])

    def test_update_uses_cas_and_recoverable_assignment_refresh_partial(self):
        initial = self.bind()
        self.adopt()
        current_binding = self.directions.read(self.subject, actor=self.actor)["binding_ref"]
        current = self.assignment_base([replace(self.document.ref, revision="rev-1")])
        draft = self.directions.save_draft(
            self.subject, {"text": "Future direction"}, actor=self.actor,
            logical_request_key="future-draft", expected_revision="rev-1")
        guide = self.create_document("future-base", self.task.ref, role="guide")
        instructions = "Execute the bounded outcome"
        guide_content = {"schema": "herzchen.instructions.v1", "name": "future-base",
                         "entrypoint": "WORKER.md", "instructions": instructions,
                         "bundle_digest": sha256(instructions.encode()).hexdigest(),
                         "export_manifest_digest": "future", "required": True,
                         "supporting_refs": [draft["revision_ref"]]}
        guide_revision = ContentRevision(guide.ref, "rev-2", guide_content, self.actor, parent_revision="rev-1")
        self.owner.content.execute(self.owner.content.build_append_revision(
            self.context("future-base-revision", expected_revision="rev-1"), guide, guide_revision))
        future_resources = [{"resource_ref": guide_revision.ref.to_dict(), "resource_name": "future-base",
                             "content_digest": validate_instruction_content(guide_content), "required": True}]
        wrong_actor = self.binding.authenticated_actor("not-manager")
        partial = self.directions.update(
            self.subject, draft["revision_ref"], actor=self.actor,
            expected_binding_ref=current_binding, logical_request_key="future-update",
            assignment_ref=current.ref, expected_generation=current.generation,
            assignment_resources=future_resources, assignment_actor=wrong_actor)
        self.assertEqual(partial["outcome"], "partial")
        self.assertTrue(partial["admitted_evidence_preserved"])
        self.assertEqual(self.resolve(assignment_ref=current.ref, expected_generation=1)["effective_ref"]["revision"], "rev-1")
        recovered = self.directions.update(
            self.subject, draft["revision_ref"], actor=self.actor,
            expected_binding_ref=current_binding, logical_request_key="future-update",
            assignment_ref=current.ref, expected_generation=current.generation,
            assignment_resources=future_resources,
            assignment_actor=self.binding.authenticated_actor("manager-a"))
        self.assertEqual(recovered["outcome"], "updated")
        self.assertEqual(recovered["assignment_refresh"]["outcome"], "committed")
        self.assertEqual(self.resolve(assignment_ref=recovered["assignment_refresh"]["assignment_ref"], expected_generation=1)["effective_ref"], draft["revision_ref"])
        with self.assertRaisesRegex(DirectionResolutionError, "stale_binding"):
            self.directions.update(
                self.subject, draft["revision_ref"], actor=self.actor,
                expected_binding_ref=initial["binding_ref"], logical_request_key="different-update")

    def test_update_requires_explicit_future_assignment_boundary_without_rewriting_history(self):
        initial = self.bind()
        self.adopt()
        current_binding = self.directions.read(self.subject, actor=self.actor)["binding_ref"]
        draft = self.directions.save_draft(
            self.subject, {"text": "Held until future"}, actor=self.actor,
            logical_request_key="held-draft", expected_revision="rev-1")
        current = self.owner.assignments.get(self.assignment.ref)
        result = self.directions.update(
            self.subject, draft["revision_ref"], actor=self.actor,
            expected_binding_ref=current_binding, logical_request_key="held-update",
            assignment_ref=current.ref, expected_generation=current.generation)
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["assignment_refresh"]["code"], "resources_not_supplied")
        self.assertEqual(self.resolve()["effective_ref"], draft["revision_ref"])

    def test_reopen_keeps_exact_adoption_and_detects_corrupt_evidence(self):
        self.bind()
        self.adopt()
        before = self.resolve()
        expected = self.store.registered_domains()
        self.store.close()
        from herzchen.kernel import Store
        self.store = Store.open(self.path, authority=self.binding.authority, expected_domains=expected)
        self.compose()
        self.assertEqual(self.resolve(), before)
        target = ResourceRef.from_dict(before['binding_ref'])
        record = self.store.get_record(target)
        adoption = dict(record.payload['scope_adoption'], inputs=[])
        self.store.revise_identity(target, dict(record.payload, scope_adoption=adoption), revision='rev-3',
            expected_revision=target.revision, expected_version=record.version)
        with self.assertRaisesRegex(DirectionResolutionError, 'conflicting_adoption'):
            self.resolve()

    def test_base_supporting_overlap_cannot_override_scope_inputs(self):
        support = self.create_document('support', self.subject, role='research')
        old_support = replace(support.ref, revision='rev-1')
        new_support = self.append(support, 2, {'text': 'Other'})
        primary = self.append(self.document, 2, {'text': 'Direction', 'supporting_refs': [old_support.to_dict()]})
        self.bind()
        self.adopt(primary)
        current = self.assignment_base([primary, new_support])
        with self.assertRaisesRegex(DirectionResolutionError, 'conflicting_assignment_inputs'):
            self.resolve(assignment_ref=current.ref, expected_generation=1)


if __name__ == '__main__':
    unittest.main()

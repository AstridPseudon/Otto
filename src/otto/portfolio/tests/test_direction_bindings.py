"""D01 identity/authority evidence using disposable canonical owner Stores."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import threading
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import ContentDocument, ContentRevision, DocumentAssociation, domain_contribution
from herzchen.content.direction_contract import PRIMARY_DIRECTION_NAMESPACE
from herzchen.content.model import ContentError
from herzchen.content.instructions import validate_instruction_content
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.contracts import AuthenticatedActor, ReferenceBinding, ReplayConflictError, ResourceRef, TransactionContext
from herzchen.domains.work import contributions
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.model import WorkValidationError
from herzchen.kernel import Store
from otto.portfolio.direction import DirectionBindingError, owner_direction_subject
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class DirectionBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "owner.sqlite"
        self.store = Store.create(self.path, authority="direction-test-owner")
        self.store.register_domain_handler((*contributions(), domain_contribution(),
                                            authoring_contribution(), packet_contribution()))
        self.binding = HerzchenBindingConfig(self.store.authority, "owner-credential")
        self.compose()
        self.project = self.owner.graph.create_project(title="Direction", logical_request_key="project")
        self.task = self.owner.graph.create_task(self.project.ref, title="Outcome", logical_request_key="task")
        self.assignment = self.owner.assignments.assign(self.task.ref, role="worker", principal="worker-a",
                                                       manager="manager-a", session="native-a", logical_request_key="assignment")
        self.subject = ResourceRef.from_dict(self.assignment.payload["responsibility_ref"])
        self.document = self.create_document("direction", self.subject)
        self.other = self.create_document("other", self.subject)
        self.addCleanup(lambda: self.store.close())

    def compose(self, owner_actor="owner"):
        self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor=owner_actor)
        self.actor = self.owner.owner_actor
        self.directions = self.owner.direction_bindings()

    def context(self, key, *, expected_revision=None):
        return TransactionContext(self.actor, key, sha256(key.encode()).hexdigest(), expected_revision=expected_revision)

    def create_document(self, ident, scope, *, role="direction", imported=False):
        ref = ResourceRef(self.store.authority, "dat.content.document", ident)
        document = ContentDocument(ref, role, "private", "append", self.actor.actor, scope)
        revision = ContentRevision(ref, "rev-1", {"text": "Priorities"}, self.actor, initial=True)
        if imported:
            # Model a retained read-only import, without a local revision write.
            document = replace(document, source_ref=ResourceRef("foreign", "dat.content.document", "source", "rev-1"),
                               import_mode="pinned", writable=False, access_mode="read")
            self.store.put_identity(ref, {"record_type": "dat.content.document", "document": document,
                                          "current_revision": revision.ref}, version=1)
        else:
            content = self.owner.content
            content.execute(content.build_create_document(self.context("create:" + ident), document, revision))
        return document

    def bind(self, document=None, key="bind", subject=None, actor=None):
        return self.directions.bind(subject or self.subject, (document or self.document).ref,
                                    actor=actor or self.actor, logical_request_key=key)

    def test_initial_binding_is_idempotent_and_changed_document_retries_fail(self):
        first = self.bind()
        counts = self.store.consumer().snapshot_counts()
        self.assertEqual(self.bind(), first)
        self.assertEqual(self.bind(key="same-identity-new-key"), first)
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        with self.assertRaises(ReplayConflictError):
            self.bind(self.other)
        with self.assertRaises(DirectionBindingError):
            self.bind(self.other, key="replace")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        events = self.store.list_events(stream="direction:" + first["binding_ref"]["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor, self.actor)
        self.assertEqual(first["document_ref"], self.document.ref.to_dict())
        self.assertIsNone(first["scope_adopted_ref"])

    def test_revisions_replacement_retirement_resume_and_reopen_preserve_identity(self):
        first = self.bind()
        for number in (2, 3):
            revision = ContentRevision(self.document.ref, "rev-" + str(number), {"text": "Updated " + str(number)},
                                       self.actor, parent_revision="rev-" + str(number - 1))
            content = self.owner.content
            content.execute(content.build_append_revision(self.context("append:" + str(number), expected_revision=revision.parent_revision),
                                                          self.document, revision))
        replacement = self.owner.assignments.reassign(self.assignment.ref, principal="worker-b", session="native-b",
                                                      expected_generation=1, logical_request_key="replacement")
        read = self.directions.read(replacement.ref, actor=self.actor)
        self.assertEqual(read["document_ref"], first["document_ref"])
        self.assertEqual(read["binding_ref"], first["binding_ref"])
        self.assertEqual(read["subject_ref"], self.subject.to_dict())
        self.assertEqual((read["generation"], read["principal"], read["session"]), (2, "worker-b", "native-b"))
        self.owner.graph.withdraw(self.task.ref, logical_request_key="retire-scope")
        self.assertEqual(self.directions.read(self.subject, actor=self.actor)["binding_ref"], first["binding_ref"])
        resumed = self.owner.assignments.reassign(replacement.ref, expected_generation=2, reason="resume",
                                                  logical_request_key="resume")
        self.assertEqual(self.directions.read(resumed.ref, actor=self.actor)["document_ref"], first["document_ref"])
        expected = self.store.registered_domains()
        self.store.close()
        self.store = Store.open(self.path, authority=self.binding.authority, expected_domains=expected)
        self.compose()
        self.assertEqual(self.bind()["binding_ref"], first["binding_ref"])
        with self.assertRaises(DirectionBindingError):
            self.bind(self.other, key="after-retirement-rebind")

    def test_assignment_manager_and_spoofed_owner_credential_have_no_direction_authority(self):
        manager = self.binding.authenticated_actor("manager-a")
        # The manager really can adopt this assignment's BASE; that authority
        # still cannot bind its direction, including a broader owner direction.
        instructions = "Execute the assigned outcome"
        content = {"schema": "herzchen.instructions.v1", "name": "worker-base", "entrypoint": "WORKER.md",
                   "instructions": instructions, "bundle_digest": sha256(instructions.encode()).hexdigest(),
                   "export_manifest_digest": "fixture", "required": True, "supporting_refs": []}
        guide = self.create_document("base", self.task.ref, role="guide")
        revision = ContentRevision(guide.ref, "rev-2", content, manager, parent_revision="rev-1")
        self.owner.content.execute(self.owner.content.build_append_revision(self.context("base-revision", expected_revision="rev-1"), guide, revision))
        adopted = self.owner.assignments.adopt_resources(self.assignment.ref,
            resources=[{"resource_ref": revision.ref.to_dict(), "resource_name": content["name"],
                        "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=self.assignment.revision, expected_generation=1, logical_request_key="adopt-base", actor=manager)
        self.assertEqual(adopted.payload["resource_adoptions"][0]["resource_ref"], revision.ref.to_dict())
        counts = self.store.consumer().snapshot_counts()
        for actor in (self.binding.authenticated_actor("manager-a"), self.binding.authenticated_actor("worker-a"),
                      AuthenticatedActor(self.store.authority, self.actor.actor, "wrong-credential"),
                      AuthenticatedActor("foreign", self.actor.actor, self.actor.credential_ref)):
            with self.subTest(actor=actor):
                with self.assertRaises(PermissionError):
                    self.bind(actor=actor)
                with self.assertRaises(PermissionError):
                    self.directions.read(self.subject, actor=actor)
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        self.assertNotIn("directions", vars(self.owner.consumer_operations()))

    def test_competing_initial_bindings_have_one_winner_and_one_canonical_event(self):
        barrier = threading.Barrier(2)
        results, errors = [], []

        def bind(document):
            barrier.wait()
            try:
                results.append(self.bind(document, key="race:" + document.ref.id))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=bind, args=(document,)) for document in (self.document, self.other)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DirectionBindingError)
        self.assertEqual(len(self.store.list_events(stream="direction:" + results[0]["binding_ref"]["id"])), 1)

    def test_owner_wide_scope_outlives_owner_operator_and_rejects_foreign_scopes(self):
        subject = owner_direction_subject(self.store.authority)
        overall = self.create_document("overall", subject)
        first = self.bind(overall, subject=subject)
        self.compose(owner_actor="replacement-owner")
        read = self.directions.read(subject, actor=self.actor)
        self.assertEqual(read["binding_ref"], first["binding_ref"])
        self.assertEqual(read["binding_operator"]["actor"], "owner")
        self.assertEqual(read["document_ref"], overall.ref.to_dict())
        for subject in (ResourceRef("foreign", "work.project", "project"),
                        ResourceRef(self.store.authority, "native.session", "native-a"),
                        ResourceRef(self.store.authority, "work.project", "missing")):
            with self.assertRaises(DirectionBindingError):
                self.directions.read(subject, actor=self.actor)

    def test_ordinary_dat_links_unlinks_revision_aliases_and_overwrite_cannot_bypass(self):
        first = self.bind()
        content = self.owner.content
        counts = self.store.consumer().snapshot_counts()
        for subject in (self.subject, replace(self.subject, revision="rev-99")):
            association = DocumentAssociation(subject, PRIMARY_DIRECTION_NAMESPACE, "primary", ReferenceBinding(self.other.ref, "current"))
            self.assertEqual(association.identity, first["binding_ref"]["id"])
            for build in (content.build_link, content.build_unlink):
                with self.assertRaises(ContentError):
                    content.execute(build(self.context("bypass:" + build.__name__), association))
        # DAT supports generic document kinds; even that path cannot overwrite
        # the retained reserved association with document content.
        target = ResourceRef.from_dict(first["binding_ref"])
        counterfeit = replace(self.document, ref=ResourceRef(target.authority, target.kind, target.id))
        revision = ContentRevision(counterfeit.ref, "rev-2", {"text": "overwrite"}, self.actor, initial=True)
        with self.assertRaises(ContentError):
            content.execute(content.build_create_document(self.context("overwrite"), counterfeit, revision))
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        # Generic role-guide membership keeps its ordinary selection semantics.
        guide = self.create_document("guide", self.subject, role="guide")
        generic = DocumentAssociation(self.subject, "role.guides", "base", ReferenceBinding(guide.ref, "current"))
        content.execute(content.build_link(self.context("guide-link"), generic))
        content.execute(content.build_unlink(self.context("guide-unlink"), generic))
        self.assertEqual(self.directions.read(self.subject, actor=self.actor)["document_ref"], first["document_ref"])

    def test_sheet_link_and_document_import_cannot_overwrite_primary_binding(self):
        first = self.bind()
        batches = ProjectBatches(self.store, actor=self.actor)
        counts = self.store.consumer().snapshot_counts()
        for sheet in ({"document_links": [{"document_ref": self.other.ref.to_dict(), "namespace": PRIMARY_DIRECTION_NAMESPACE,
                                          "key": "primary"}]},
                      {"document_changes": [{"document_ref": first["binding_ref"], "content": {"text": "replace"}}]}):
            with self.subTest(sheet=sheet):
                with self.assertRaises(WorkValidationError):
                    batches.apply_project_sheet(self.project.ref, sheet, logical_request_key="sheet-bypass")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_initial_binding_distinguishes_direction_guides_mandates_and_owned_sources(self):
        for role in ("guide", "mandate"):
            document = self.create_document(role, self.subject, role=role)
            with self.assertRaises(DirectionBindingError):
                self.bind(document, key="bind:" + role)
        imported = self.create_document("imported", self.subject, imported=True)
        with self.assertRaises(DirectionBindingError):
            self.bind(imported, key="bind-import")
        wrong_scope = self.create_document("wrong-scope", owner_direction_subject(self.store.authority))
        with self.assertRaises(DirectionBindingError):
            self.bind(wrong_scope, key="wrong-scope")

    def test_name_reuse_is_not_responsibility_recreation_or_authority_transfer(self):
        first = self.bind()
        # Reusing the original creation key cannot rewrite the enduring subject.
        with self.assertRaises(ReplayConflictError):
            self.owner.assignments.assign(self.task.ref, role="worker", principal="other",
                                          logical_request_key="assignment")
        independent = self.owner.assignments.assign(self.task.ref, role="worker", principal="worker-a",
                                                    logical_request_key="independent-responsibility")
        read = self.directions.read(independent.ref, actor=self.actor)
        self.assertNotEqual(read["subject_ref"], first["subject_ref"])
        self.assertIsNone(read["document_ref"])
        self.assertEqual(self.bind()["document_ref"], first["document_ref"])

    def test_existing_project_task_subjects_are_distinct_and_binding_does_not_change_work(self):
        for scope in (self.project.ref, self.task.ref):
            unversioned = ResourceRef(scope.authority, scope.kind, scope.id)
            document = self.create_document(scope.kind, unversioned)
            before = self.store.get_record(scope)
            bound = self.bind(document, subject=scope, key="bind:" + scope.kind)
            self.assertEqual(bound["subject_ref"], unversioned.to_dict())
            self.assertEqual(self.store.get_record(scope), before)
        self.assertIsNone(self.directions.read(self.subject, actor=self.actor)["document_ref"])

    def test_project_owned_direction_uses_existing_authoring_scope_and_current_work_mapping(self):
        # Existing public authoring pins authoring_scope to a project revision.
        document = self.create_document("project-owned", self.project.ref)
        bound = self.bind(document)
        self.assertEqual(bound["project_ref"], self.project.ref.to_dict())
        self.assertEqual(bound["task_ref"], self.task.ref.to_dict())
        self.assertEqual(bound["subject_ref"], self.subject.to_dict())

    def test_corrupt_retired_membership_fails_closed_and_cannot_unlink_rebind(self):
        first = self.bind()
        target = ResourceRef.from_dict(first["binding_ref"])
        current = self.store.get_record(target)
        # Deliberate corruption in a disposable fixture models an exceptional
        # legacy repair case; no public direction operation permits retirement.
        self.store.revise_identity(target, dict(current.payload, active=False), revision="rev-2",
                                   expected_revision=target.revision, expected_version=current.version)
        counts = self.store.consumer().snapshot_counts()
        with self.assertRaises(DirectionBindingError):
            self.directions.read(self.subject, actor=self.actor)
        for key in ("bind", "recreate"):
            with self.assertRaises(DirectionBindingError):
                self.bind(key=key)
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)


if __name__ == "__main__":
    unittest.main()

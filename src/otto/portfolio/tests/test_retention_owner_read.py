from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import ReplayConflictError, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from otto.portfolio.execution_host import _nested_capability
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.retention_owner_read import RetentionOwnerRead
from . import test_direction_bindings as fixtures


class RetentionOwnerReadTests(unittest.TestCase):
    setUp = fixtures.DirectionBindingsTests.setUp
    compose = fixtures.DirectionBindingsTests.compose
    context = fixtures.DirectionBindingsTests.context
    create_document = fixtures.DirectionBindingsTests.create_document

    def setup_portfolio(self):
        from dataclasses import replace
        from hashlib import sha256
        from herzchen.content import ContentRevision
        from herzchen.content.instructions import validate_instruction_content
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap

        portfolio = ResourceRef(self.store.authority, "wrk.portfolio", "selected")
        root = self.owner.assignments.assign(portfolio, role="orchestrator", principal="owner", logical_request_key="root")
        subject = ResourceRef.from_dict(root.payload["responsibility_ref"])
        document = self.create_document("root-direction", subject)
        pin = replace(document.ref, revision="rev-1")
        binding = self.directions.bind(subject, document.ref, actor=self.actor, logical_request_key="root-bind")
        self.directions.adopt(subject, pin, expected_binding_ref=binding["binding_ref"],
                              actor=self.actor, logical_request_key="root-adopt")
        base = self.create_document("root-base", subject, role="role_instructions")
        text = "Shared orchestrator template with exact individual direction"
        body = {"schema": "herzchen.instructions.v1", "name": "BASE", "entrypoint": "ORCHESTRATOR.md",
                "instructions": text, "bundle_digest": sha256(text.encode()).hexdigest(),
                "export_manifest_digest": "fixture", "required": True, "supporting_refs": [pin.to_dict()]}
        revision = ContentRevision(base.ref, "rev-2", body, self.actor, parent_revision="rev-1")
        self.owner.content.execute(self.owner.content.build_append_revision(
            self.context("root-base-revision", expected_revision="rev-1"), base, revision))
        root = self.owner.assignments.adopt_resources(root.ref,
            resources=[{"resource_ref": revision.ref.to_dict(), "resource_name": "BASE",
                        "content_digest": validate_instruction_content(body), "required": True}],
            expected_revision=root.revision, expected_generation=root.generation,
            logical_request_key="root-base-adopt", actor=self.actor)
        owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner",
            portfolio_ref=portfolio, main_assignment_ref=root.ref)
        project = owner.graph.create_project(title="Queued selected", logical_request_key="queued-selected")
        owner.graph.create_task(project.ref, title="Bounded structural row", logical_request_key="retention-task")
        project = owner.graph.get(project.ref)
        owner.consumer_operations().execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": root.ref.to_dict(), "target_assignment_revision": root.revision,
            "target_assignment_generation": root.generation,
            "projects": [{"project_ref": project.ref.to_dict(), "project_version": project.version,
                          "assignment_ref": None, "assignment_revision": None, "assignment_generation": None}]},
            request_id="enroll", actor="owner")
        return root, subject, pin, owner.graph.get(project.ref)

    def complete_project_for_preview(self, project):
        current = self.owner.graph.get(project.ref)
        next_ref = ResourceRef(current.ref.authority, current.ref.kind, current.ref.id,
                               "rev-" + str(current.version + 1))
        metadata = dict(current.payload.get("metadata", {}))
        relation = dict(metadata["otto_orchestrator"], project_ref=next_ref.to_dict())
        metadata["otto_orchestrator"] = relation
        payload = dict(current.payload, lifecycle="completed", metadata=metadata,
                       lifecycle_control={"reconciliation": {"status": "reconciled"}})
        self.store.revise_identity(current.ref, payload, revision=next_ref.revision,
            expected_revision=current.ref.revision, expected_version=current.version)
        return self.owner.graph.get(next_ref)

    def test_owner_route_is_bounded_and_lifecycle_never_claims_empty_complete(self):
        root, _subject, _pin, project = self.setup_portfolio()
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            capability = RetentionOwnerRead(service)
            request = {"command": "owner-context", "operation": "retention-read",
                       "request_key": "lifecycle-read", "handle": {"view": "lifecycle"}}
            ingress = ManagerJourneyService.__new__(ManagerJourneyService)
            ingress.server = service.server
            ingress.authoring_authorizer = lambda _request: self.actor
            ingress.retention_owner_read = capability
            result = ingress._owner_context(request)
            self.assertEqual(result["outcome"], "read")
            self.assertFalse(result["complete"])
            self.assertEqual(result["task_inventory"]["selected_count"], 1)
            self.assertEqual(result["tasks"][0]["lifecycle"], "pending")
            self.assertEqual(result["reconciliation"]["state"], "unknown")
            self.assertEqual(result["observation_subjects"]["state"], "unavailable")
            self.assertEqual(_nested_capability(request), "admitted")
            self.assertEqual(_nested_capability({**request, "project_ref": project.ref.to_dict()}), "held")
            with self.assertRaises(ValueError):
                capability.call({**request, "handle": {"view": "lifecycle", "project_ref": project.ref.to_dict()}},
                                root=root, actor=self.actor)
            with self.assertRaises(PermissionError):
                capability.call(request, root=root, actor=self.binding.authenticated_actor("foreign"))
            service.server.state["orchestrator_assignment_ref"] = {
                **root.ref.to_dict(), "id": "stale-root"}
            with self.assertRaises(PermissionError):
                capability.call(request, root=root, actor=self.actor)

    def test_storage_returns_only_injected_partial_receipt_and_preview_unavailable_without_handler(self):
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        receipt = {"schema": "otto.owner-storage-diagnostic-partial.v1", "at": "2026-10-11T23:08:00Z",
                   "outcome": "cancelled-resource-pressure", "complete_storage_diagnostic": False,
                   "capacity_fit": "unavailable", "observed_free_before_bytes": 1234,
                   "sample_ref": "/trusted/retained/sample.txt",
                   "unsafe_private": "must not escape"}
        capability = RetentionOwnerRead(service, storage_receipt=receipt)
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            result = capability.call({"handle": {"view": "storage"}}, root=root, actor=self.actor)
            self.assertEqual(result["outcome"], "partial")
            self.assertEqual(result["currentness"], "not-revalidated")
            self.assertNotIn("unsafe_private", result["receipt"])
            self.assertEqual(result["receipt"]["observed_free_before_bytes"], 1234)
            self.assertEqual(result["receipt"]["sample_locator"], "/trusted/retained/sample.txt")
            future = RetentionOwnerRead(service, storage_receipt={
                "schema": "otto.closed-storage-diagnostic-receipt.v1", "observed_at": "2026-10-12T00:00:00Z",
                "source_commit": "a" * 40,
                "custody": {"ordinary_exit_status": 0, "store_closed": True,
                            "owner_alive": False, "supervisor_alive": False,
                            "store_ref": {"authority": "owner", "kind": "store", "id": "one"},
                            "receipt_sha256": "b" * 64, "secret": "omit"},
                "diagnostics": {"source_bytes": 1000, "file_allocated_bytes": 4096, "page_size": 4096,
                    "page_count": 1, "freelist_pages": 0, "freelist_bytes": 0,
                    "work": {"state": "complete", "reason": "bounded"},
                    "stages": {**{name: {"state": "complete"} for name in
                        ("pages", "tables", "payload_groups")}, "allocation": {"state": "available"}},
                    "tables": [{"name": "identity", "rows": 3}],
                    "payload_groups": {"state": "complete", "groups": 2},
                    "page_allocation": {"allocated_bytes": 4096},
                    "records_modified": False, "physical_unique_CoW_bytes": "unavailable"},
                "provider_called": False})
            closed = future.call({"handle": {"view": "storage"}}, root=root, actor=self.actor)
            self.assertTrue(closed["complete"])
            self.assertEqual(closed["diagnostics"]["source_bytes"], 1000)
            self.assertEqual(closed["diagnostics"]["stages"]["allocation"]["state"], "available")
            self.assertEqual(closed["diagnostics"]["payload_groups"]["groups"], 2)
            self.assertEqual(closed["diagnostics"]["physical_unique_CoW_bytes"], "unavailable")
            self.assertIs(closed["diagnostics"]["records_modified"], False)
            self.assertEqual(closed["custody"]["store_closed"], True)
            self.assertEqual(closed["custody"]["receipt_sha256"], "b" * 64)
            self.assertEqual(closed["custody"]["store_ref"]["id"], "one")
            self.assertNotIn("secret", closed["custody"])
            self.assertFalse(closed["provider_called"])
            held = capability.call({"request_key": "p", "handle": {"view": "reclaim-preview",
                "cutoff": "9999-01-01T00:00:00Z", "cursor": "", "limit": 10}}, root=root, actor=self.actor)
        self.assertEqual(held["outcome"], "unavailable")
        self.assertEqual(held["deletion_count"], 0)

    def test_real_evidence_preview_is_fixed_bounded_and_replay_fenced(self):
        try:
            from tests.test_evidence_reclaim import _current_pack
        except ImportError:
            from test_evidence_reclaim import _current_pack
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        register_evidence(self.store)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        handler = EvidenceCommandHandler(self.store, Path(directory.name) / "managed",
            pack=_current_pack(), adopted_pins=[item.to_dict() for item in _current_pack().resources])
        submitted = handler.submit(b"small disposable payload", actor=self.actor, logical_request_key="retention-submit",
                                   project_ref=project.ref, original_creator="fixture")
        status = handler.status(submitted["revision_ref"], actor=self.actor)
        managed_path = Path(directory.name) / "managed" / status["manifest"]["storage"]["location"]
        self.assertTrue(managed_path.is_file())
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        capability = RetentionOwnerRead(service, evidence_handler=handler)
        handle = {"view": "reclaim-preview", "cutoff": "9999-01-01T00:00:00Z", "cursor": "", "limit": 20}
        request = {"request_key": "preview-once", "handle": handle}
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            first = capability.call(request, root=root, actor=self.actor)
            second = capability.call(request, root=root, actor=self.actor)
            self.assertEqual(first["outcome"], "previewed")
            self.assertEqual(second["outcome"], "replayed")
            self.assertEqual(first["project_ref"], project.ref.to_dict())
            self.assertTrue(first["canonical_selection_recorded"])
            self.assertFalse(first["read_only"])
            self.assertEqual(first["deletion_count"], 0)
            self.assertEqual(first["managed_bytes_removed"], 0)
            self.assertEqual(first["items"][0]["hold"], "dependency-unknown")
            self.assertTrue(managed_path.is_file())
            lifecycle = capability.call({"request_key": "lifecycle-after-preview",
                "handle": {"view": "lifecycle"}}, root=root, actor=self.actor)
            self.assertFalse(lifecycle["complete"])
            with self.assertRaises(ReplayConflictError):
                capability.call({**request, "handle": {**handle, "cutoff": "9998-01-01T00:00:00Z"}},
                                 root=root, actor=self.actor)


if __name__ == "__main__":
    unittest.main()

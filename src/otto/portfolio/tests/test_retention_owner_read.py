from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import ReplayConflictError, ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.kernel.store import Store
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
        task = owner.graph.create_task(project.ref, title="Bounded structural row", logical_request_key="retention-task")
        project = owner.graph.current(project.ref)
        project_ref = ResourceRef(project.ref.authority, project.ref.kind, project.ref.id,
                                  "rev-" + str(project.version + 1))
        project_payload = dict(project.payload, tasks=[task.ref.to_dict()])
        self.store.revise_identity(project.ref, project_payload, revision=project_ref.revision,
            expected_revision=project.ref.revision, expected_version=project.version)
        project = owner.graph.current(project_ref)
        owner.consumer_operations().execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": root.ref.to_dict(), "target_assignment_revision": root.revision,
            "target_assignment_generation": root.generation,
            "projects": [{"project_ref": project.ref.to_dict(), "project_version": project.version,
                          "assignment_ref": None, "assignment_revision": None, "assignment_generation": None}]},
            request_id="enroll", actor="owner")
        return root, subject, pin, owner.graph.current(project.ref)

    def complete_project_for_preview(self, project):
        current = self.owner.graph.current(project.ref)
        next_ref = ResourceRef(current.ref.authority, current.ref.kind, current.ref.id,
                               "rev-" + str(current.version + 1))
        metadata = dict(current.payload.get("metadata", {}))
        relation = dict(metadata["otto_orchestrator"], project_ref=next_ref.to_dict())
        metadata["otto_orchestrator"] = relation
        payload = dict(current.payload, lifecycle="completed", metadata=metadata,
                       lifecycle_control={"reconciliation": {"status": "reconciled"}})
        self.store.revise_identity(current.ref, payload, revision=next_ref.revision,
            expected_revision=current.ref.revision, expected_version=current.version)
        return self.owner.graph.current(next_ref)

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

    def test_lifecycle_projects_only_exact_task_pins_and_retains_completion_survivors(self):
        root, _subject, _pin, project = self.setup_portfolio()
        task_ref = ResourceRef.from_dict(project.payload["tasks"][0])
        task = self.owner.graph.current(task_ref)
        payload = dict(task.payload)
        candidate_doc = self.create_document("retention-candidate", _subject)
        result_doc = self.create_document("retention-result", _subject)
        evidence_doc = self.create_document("retention-evidence", _subject)
        gate_doc = self.create_document("retention-gate", _subject)
        candidate = ResourceRef(candidate_doc.ref.authority, candidate_doc.ref.kind, candidate_doc.ref.id, "rev-1")
        result = ResourceRef(result_doc.ref.authority, result_doc.ref.kind, result_doc.ref.id, "rev-1")
        evidence = ResourceRef(evidence_doc.ref.authority, evidence_doc.ref.kind, evidence_doc.ref.id, "rev-1")
        gate = ResourceRef(gate_doc.ref.authority, gate_doc.ref.kind, gate_doc.ref.id, "rev-1")
        payload["completion"] = {"candidate_ref": candidate.to_dict(), "result_ref": None,
            "evidence_refs": [evidence.to_dict()], "gate_refs": [gate.to_dict()],
            "attempt_ref": None, "assignment_ref": root.ref.to_dict()}
        payload["unrelated_large_notes"] = "x" * 20000
        next_task_ref = ResourceRef(task.ref.authority, task.ref.kind, task.ref.id,
                                    "rev-" + str(task.version + 1))
        self.store.revise_identity(task.ref, payload, revision=next_task_ref.revision,
            expected_revision=task.ref.revision, expected_version=task.version)

        # Keep the project-declared exact task pin current and provide complete
        # structural reconciliation evidence without reading global history.
        current_project = self.owner.graph.current(project.ref)
        metadata = dict(current_project.payload.get("metadata", {}))
        next_project_ref = ResourceRef(current_project.ref.authority, current_project.ref.kind,
            current_project.ref.id, "rev-" + str(current_project.version + 1))
        join = dict(metadata["otto_orchestrator"], project_ref=next_project_ref.to_dict())
        metadata["otto_orchestrator"] = join
        unversioned_membership = {"authority": task_ref.authority, "kind": task_ref.kind,
                                  "id": task_ref.id, "revision": None}
        shared_records = [{"schedule_id": f"shared-kept-{index}", "status": "preserved",
                           "record_ref": evidence.to_dict()} for index in range(24)]
        close_report = ResourceRef(self.store.authority, "wrk.report", "close-report", "rev-1")
        current_payload = dict(current_project.payload, metadata=metadata,
            tasks=[unversioned_membership], lifecycle="completed",
            lifecycle_control={"close_request": {"project_ref": next_project_ref.to_dict(),
                "manager_assignment": root.ref.to_dict(), "task_refs": [next_task_ref.to_dict()],
                "report_ref": close_report.to_dict(), "receipt": result.to_dict(), "generation": root.generation},
                "terminal_evidence": {name: {"status": "verified"} for name in
                    ("acceptance", "publication", "remote", "runtime")},
                "reconciliation": {"status": "reconciled", "mode": "no-owned-schedule",
                    "survivor_refs": [result.to_dict()], "observation": {"mode": "no-owned-schedule",
                        "pm_owned_schedule_ids": [], "unknown_ownership": False,
                        "coverage": {"authority": self.store.authority, "project_id": project.ref.id,
                            "source": "complete project-scoped public Due list", "record_count": 24},
                        "shared_records": shared_records}}})
        self.store.revise_identity(current_project.ref, current_payload, revision=next_project_ref.revision,
            expected_revision=current_project.ref.revision, expected_version=current_project.version)
        unrelated = ResourceRef(self.store.authority, "work.task", "000-unrelated-large", "rev-1")
        self.store.put_identity(unrelated, {"project_ref": project.ref.to_dict(),
            "unrelated_large_notes": "z" * 50000})
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            result_view = RetentionOwnerRead(service).call({"handle": {"view": "lifecycle"}},
                                                          root=root, actor=self.actor)
        self.assertEqual(result_view["task_inventory"]["state"], "complete")
        self.assertEqual(result_view["task_inventory"]["read_mode"], "exact-primary-key-projection")
        self.assertEqual(result_view["task_inventory"]["pin_source"],
                         "completed-close-request-exact-identity-set")
        self.assertEqual(result_view["task_inventory"]["identities_examined"], 1)
        self.assertNotIn("state", result_view["tasks"][0])
        groups = result_view["tasks"][0]["survivor_facets"]["groups"]
        self.assertEqual(groups["completion"]["fields"]["candidate_ref"]["ref"], candidate.to_dict())
        self.assertTrue(groups["completion"]["complete"])
        self.assertEqual(groups["completion"]["fields"]["result_ref"]["state"], "unavailable")
        self.assertEqual(groups["completion"]["fields"]["attempt_ref"]["state"], "unavailable")
        self.assertEqual(groups["completion"]["fields"]["evidence_refs"]["refs"], [evidence.to_dict()])
        self.assertEqual(groups["effect"]["state"], "unavailable")
        self.assertEqual(groups["settlement"]["state"], "unavailable")
        self.assertEqual(result_view["reconciliation"]["observation"]["shared_records"]["count"], 24)
        self.assertEqual(result_view["reconciliation"]["observation"]["coverage"]["fields"]["source"],
                         "complete project-scoped public Due list")
        self.assertEqual(result_view["lifecycle_control"]["close_request"]["state"], "available")
        self.assertEqual(result_view["lifecycle_control"]["terminal_evidence"]["state"], "available")
        self.assertTrue(result_view["complete"])

    def test_lifecycle_marks_stale_or_foreign_task_pins_partial(self):
        root, _subject, _pin, project = self.setup_portfolio()
        current = self.owner.graph.current(project.ref)
        bad = ResourceRef(self.store.authority, "work.task", "missing-task", "rev-1")
        foreign = ResourceRef("foreign-authority", "work.task", "foreign-task", "rev-1")
        next_ref = ResourceRef(current.ref.authority, current.ref.kind, current.ref.id,
                               "rev-" + str(current.version + 1))
        metadata = dict(current.payload["metadata"])
        metadata["otto_orchestrator"] = dict(metadata["otto_orchestrator"], project_ref=next_ref.to_dict())
        updated = dict(current.payload, metadata=metadata, tasks=[bad.to_dict(), foreign.to_dict()])
        self.store.revise_identity(current.ref, updated, revision=next_ref.revision,
            expected_revision=current.ref.revision, expected_version=current.version)
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            result_view = RetentionOwnerRead(service).call({"handle": {"view": "lifecycle"}},
                                                          root=root, actor=self.actor)
        self.assertEqual(result_view["task_inventory"]["state"], "partial-or-unknown")
        self.assertFalse(result_view["complete"])
        self.assertEqual(result_view["task_inventory"]["held"], 2)

    def test_completed_close_pins_require_exact_unversioned_membership_and_current_revisions(self):
        root, _subject, _pin, project = self.setup_portfolio()
        membership = project.payload["tasks"][0]
        member = {"authority": membership["authority"], "kind": membership["kind"],
                  "id": membership["id"], "revision": None}
        current_task = self.store.get_identity_ref(ResourceRef(member["authority"], member["kind"], member["id"]))
        self.assertIsNotNone(current_task)
        extra = ResourceRef(self.store.authority, "work.task", "extra-task", "rev-1")
        foreign = ResourceRef("foreign-authority", "work.task", member["id"], current_task.revision)
        cases = [
            ("missing", [], "close-pinset-mismatch"),
            ("extra", [current_task.to_dict(), extra.to_dict()], "close-pinset-mismatch"),
            ("foreign", [foreign.to_dict()], "close-pinset-mismatch"),
            ("duplicate", [current_task.to_dict(), current_task.to_dict()], "close-pinset-mismatch"),
            ("foreign-project", [current_task.to_dict()], "close-pinset-mismatch"),
            ("stale", [ResourceRef(current_task.authority, current_task.kind,
                                    current_task.id, "rev-0").to_dict()], "stale"),
        ]
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        for label, close_pins, expected_task_state in cases:
            with self.subTest(case=label):
                current_project_ref = self.store.get_identity_ref(ResourceRef(
                    project.ref.authority, project.ref.kind, project.ref.id))
                current_project = self.owner.graph.current(current_project_ref)
                next_project_ref = ResourceRef(current_project.ref.authority, current_project.ref.kind,
                    current_project.ref.id, "rev-" + str(current_project.version + 1))
                metadata = dict(current_project.payload.get("metadata", {}))
                join = dict(metadata["otto_orchestrator"], project_ref=next_project_ref.to_dict())
                metadata["otto_orchestrator"] = join
                close_project_ref = (ResourceRef(self.store.authority, "work.project", "foreign-project", "rev-1")
                                     if label == "foreign-project" else next_project_ref)
                close_request = {"project_ref": close_project_ref.to_dict(),
                    "manager_assignment": root.ref.to_dict(), "task_refs": close_pins,
                    "report_ref": ResourceRef(self.store.authority, "wrk.report", "close-report", "rev-1").to_dict(),
                    "generation": root.generation}
                payload = dict(current_project.payload, metadata=metadata, lifecycle="completed",
                    tasks=[member], lifecycle_control={"close_request": close_request,
                        "reconciliation": {"status": "reconciled", "mode": "no-owned-schedule",
                            "survivor_refs": [], "observation": {"mode": "no-owned-schedule",
                                "pm_owned_schedule_ids": [], "unknown_ownership": False,
                                "coverage": {"authority": self.store.authority, "project_id": project.ref.id,
                                    "source": "complete project-scoped public Due list", "record_count": 0},
                                "shared_records": []}}})
                self.store.revise_identity(current_project.ref, payload, revision=next_project_ref.revision,
                    expected_revision=current_project.ref.revision, expected_version=current_project.version)
                with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
                    view = RetentionOwnerRead(service).call({"handle": {"view": "lifecycle"}},
                                                          root=root, actor=self.actor)
                self.assertFalse(view["complete"])
                if expected_task_state == "stale":
                    self.assertEqual(view["task_inventory"]["identities_examined"], 1)
                    self.assertEqual(view["tasks"][0]["state"], "stale")
                else:
                    self.assertEqual(view["task_inventory"]["identities_examined"], 0)
                    self.assertEqual(view["tasks"][0]["state"], expected_task_state)

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

    def test_empty_nonterminal_evidence_page_stays_incomplete(self):
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        selection_ref = ResourceRef(self.store.authority, "dat.content.document", "empty-preview", "rev-1")
        class EmptyPageHandler:
            def reclaim_preview(self, project_ref, **kwargs):
                return {"outcome": "previewed", "items": [], "next_cursor": "phase-links",
                    "selection_ref": selection_ref, "selection": {
                        "selection_digest": "a" * 64, "project_ref": project_ref.to_dict()},
                    "io_work": {"identities_examined": 2}, "managed_bytes_removed": 0}
        capability = RetentionOwnerRead(service, evidence_handler=EmptyPageHandler())
        handle = {"view": "reclaim-preview", "cutoff": "9999-01-01T00:00:00Z",
                  "cursor": "", "limit": 10}
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            page = capability.call({"request_key": "empty-page", "handle": handle},
                                   root=root, actor=self.actor)
        self.assertEqual(page["items"], [])
        self.assertEqual(page["next_cursor"], "phase-links")
        self.assertFalse(page["complete"])
        self.assertEqual(page["page_state"], "bounded-page")
        self.assertEqual(page["coverage_state"], "continuation-available")
        self.assertEqual(page["page_summary"]["item_count"], 0)

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
            self.assertEqual(first["items"][0]["material_class"], "managed-evidence")
            self.assertEqual(first["items"][0]["current_head"], status["current_head"].to_dict())
            self.assertEqual(first["items"][0]["byte_digest"], status["manifest"]["byte_digest"])
            self.assertEqual(first["items"][0]["provenance"]["project_ref"], project.ref.to_dict())
            self.assertIn("identities_examined", first["page_summary"]["io_work"])
            self.assertGreater(first["page_summary"]["held_bytes"], 0)
            self.assertIsNotNone(first["next_cursor"])
            self.assertTrue(managed_path.is_file())
            lifecycle = capability.call({"request_key": "lifecycle-after-preview",
                "handle": {"view": "lifecycle"}}, root=root, actor=self.actor)
            self.assertFalse(lifecycle["complete"])
            with self.assertRaises(ReplayConflictError):
                capability.call({**request, "handle": {**handle, "cutoff": "9998-01-01T00:00:00Z"}},
                                 root=root, actor=self.actor)


class ExactIdentityProjectionTests(unittest.TestCase):
    def test_projection_is_exact_pinned_and_bounded_without_global_payload_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store.create(Path(directory) / "projection.sqlite", authority="projection-test")
            self.addCleanup(store.close)
            project_ref = ResourceRef("projection-test", "work.project", "project", "rev-1")
            selected = ResourceRef("projection-test", "work.task", "selected", "rev-1")
            unrelated = ResourceRef("projection-test", "work.task", "000-unrelated-oversize", "rev-1")
            store.put_identity(project_ref, {"lifecycle": "completed"})
            store.put_identity(selected, {"project_ref": project_ref.to_dict(),
                "completion": {"candidate_ref": ResourceRef("projection-test", "dat.candidate", "c", "rev-1").to_dict()},
                "notes": "x" * 20000})
            store.put_identity(unrelated, {"project_ref": project_ref.to_dict(), "notes": "z" * 50000})
            projection = store.consumer().project_identity_fields_for_refs([selected], fields={
                "project_ref": ("project_ref",), "candidate": ("completion", "candidate_ref"),
                "notes": ("notes",), "missing": ("missing_field",)}, max_projection_bytes=32768)
            self.assertEqual(len(projection), 1)
            self.assertEqual(projection[0]["state"], "available")
            self.assertEqual(projection[0]["fields"]["project_ref"], project_ref.to_dict())
            self.assertEqual(projection[0]["fields"]["candidate"]["id"], "c")
            self.assertEqual(projection[0]["present"]["missing"], 0)
            self.assertLessEqual(projection[0]["projected_bytes"], 32768)
            stale = store.consumer().project_identity_fields_for_refs([
                ResourceRef(selected.authority, selected.kind, selected.id, "rev-0")],
                fields={"project_ref": ("project_ref",)})
            self.assertEqual(stale[0]["state"], "stale")
            oversize = store.consumer().project_identity_fields_for_refs([selected],
                fields={"notes": ("notes",)}, max_projection_bytes=128)
            self.assertEqual(oversize[0]["state"], "oversize")
            with self.assertRaises(ValueError):
                store.consumer().project_identity_fields_for_refs([
                    ResourceRef("foreign", "work.task", "task", "rev-1")],
                    fields={"project_ref": ("project_ref",)})


if __name__ == "__main__":
    unittest.main()

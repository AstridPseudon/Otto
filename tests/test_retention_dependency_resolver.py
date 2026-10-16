"""Provider-free owner fixture for the bounded Evidence dependency resolver."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.retention_owner_read import RetentionOwnerRead, _dependency_state, _survivor_refs
from otto.portfolio.tests.test_retention_owner_read import RetentionOwnerReadTests


class RetentionDependencyResolverTests(RetentionOwnerReadTests):
    def _canonical_candidate(self, project, task, assignment, name="candidate", lifecycle=None):
        ref = ResourceRef(self.store.authority, "wrk.result", name, "rev-1")
        payload = {
            "record_type": "work.observation", "observation_kind": "result",
            "assignment": assignment.ref.to_dict(), "generation": assignment.generation,
            "value": {"assignment_ref": assignment.ref.to_dict(),
                       "project_ref": project.ref.to_dict(), "task_ref": task.to_dict(),
                       "logical_request_key": name, "operation": "work.result.append",
                       "delivery_state": "recorded", "outcome": "succeeded"},
        }
        if lifecycle is not None:
            payload["lifecycle"] = lifecycle
        self.store.put_identity(ref, payload)
        return ref

    def test_unknown_failed_foreign_and_bounded_link_shapes_fail_closed(self):
        authority = "owner"
        self.assertEqual(_dependency_state({"lifecycle": "UNKNOWN"}, require_terminal=False),
                         "dependency-unknown")
        self.assertEqual(_dependency_state({"status": "failed"}, require_terminal=False),
                         "dependency-unknown")
        candidate = {"authority": "foreign", "kind": "wrk.result", "id": "x", "revision": "rev-1"}
        present = {"completion_candidate_ref": 1, "completion_evidence_refs": 0,
                   "completion_result_ref": 0, "completion_attempt_ref": 0}
        self.assertIsNone(_survivor_refs({"completion_candidate_ref": candidate}, present, authority))
        oversized = [{"authority": authority, "kind": "dat.content.document", "id": str(i),
                      "revision": "rev-1"} for i in range(101)]
        self.assertIsNone(_survivor_refs({"completion_evidence_refs": oversized},
                                         {"completion_evidence_refs": 1}, authority))
        self.assertIsNone(_survivor_refs({"completion_candidate_ref": "truncated"},
                                         {"completion_candidate_ref": 1}, authority))

    def test_completed_linked_task_attempt_and_survivor_are_resolved(self):
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        task_ref = ResourceRef.from_dict(project.payload["tasks"][0])
        current_task = self.owner.graph.current(task_ref)
        candidate = self._canonical_candidate(project, task_ref, root, "survivor")
        survivor = candidate
        task_revision = ResourceRef(current_task.ref.authority, current_task.ref.kind,
                                    current_task.ref.id, "rev-" + str(current_task.version + 1))
        task_payload = dict(current_task.payload, lifecycle="completed",
                            completion={"candidate_ref": survivor.to_dict(), "result_ref": None,
                                        "attempt_ref": None, "assignment_ref": root.ref.to_dict(),
                                        "project_ref": project.ref.to_dict(), "task_ref": task_revision.to_dict()})
        self.store.revise_identity(current_task.ref, task_payload,
                                   revision=task_revision.revision,
                                   expected_revision=current_task.ref.revision,
                                   expected_version=current_task.version)
        attempt = ResourceRef(self.store.authority, "work.attempt", "attempt", "rev-1")
        self.store.put_identity(attempt, {"project_ref": project.ref.to_dict(),
                                          "task_ref": task_revision.to_dict(),
                                          "lifecycle": "completed"})
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        register_evidence(self.store)
        try:
            from tests.test_evidence_reclaim import _current_pack
        except ImportError:
            from test_evidence_reclaim import _current_pack
        handler = EvidenceCommandHandler(
            self.store, Path(directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources])
        submitted = handler.submit(
            b"linked payload", actor=self.actor, logical_request_key="linked-submit",
            project_ref=project.ref, task_ref=task_revision, attempt_ref=attempt,
            original_creator="fixture")
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        capability = RetentionOwnerRead(service, evidence_handler=handler)
        handle = {"view": "reclaim-preview", "cutoff": "9999-01-01T00:00:00Z",
                  "cursor": "", "limit": 10}
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            page = capability.call({"request_key": "linked-preview", "handle": handle},
                                   root=root, actor=self.actor)
        self.assertEqual(page["items"][0]["reference"], submitted["revision_ref"].to_dict())
        self.assertTrue(page["items"][0]["eligible"], page)
        self.assertNotIn("hold", page["items"][0], page)
        self.assertGreaterEqual(page["page_summary"]["item_count"], 1)

    def test_active_foreign_missing_and_unknown_dependencies_remain_held(self):
        # The existing Evidence status and reclaim hold paths remain the source
        # of truth for unavailable payloads and foreign/unknown joins.
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        register_evidence(self.store)
        try:
            from tests.test_evidence_reclaim import _current_pack
        except ImportError:
            from test_evidence_reclaim import _current_pack
        foreign_project = ResourceRef(self.store.authority, "work.project", "foreign-project")
        self.store.put_identity(foreign_project, {"record_type": "work.project", "lifecycle": "completed"})
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        handler = EvidenceCommandHandler(
            self.store, Path(directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources])
        foreign = handler.submit(b"foreign payload", actor=self.actor,
                                logical_request_key="foreign-submit",
                                project_ref=foreign_project, original_creator="fixture")
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        capability = RetentionOwnerRead(service, evidence_handler=handler)
        foreign_result = capability._resolve_dependencies(
            foreign["revision_ref"], project.ref, root=root, actor=self.actor)
        self.assertFalse(foreign_result["complete"])
        self.assertEqual(foreign_result["holds"], ("dependency-unknown",))
        result = capability._resolve_dependencies(
            ResourceRef(self.store.authority, "dat.content.document", "missing", "rev-1"),
            project.ref, root=root, actor=self.actor)
        self.assertFalse(result["complete"])
        self.assertEqual(result["holds"], ("dependency-unknown",))

    def test_active_linked_dependency_is_recovery_hold_and_missing_payload_stays_unavailable(self):
        root, _subject, _pin, project = self.setup_portfolio()
        project = self.complete_project_for_preview(project)
        task_ref = ResourceRef.from_dict(project.payload["tasks"][0])
        current_task = self.owner.graph.current(task_ref)
        task_revision = ResourceRef(current_task.ref.authority, current_task.ref.kind,
                                    current_task.ref.id, "rev-" + str(current_task.version + 1))
        survivor = ResourceRef(self.store.authority, "wrk.result", "active-survivor", "rev-1")
        survivor_membership = ResourceRef(survivor.authority, survivor.kind, survivor.id)
        self.store.revise_identity(current_task.ref,
                                   dict(current_task.payload, lifecycle="completed",
                                        completion={"candidate_ref": survivor_membership.to_dict(), "result_ref": None,
                                                    "attempt_ref": None, "assignment_ref": root.ref.to_dict(),
                                                    "project_ref": project.ref.to_dict(), "task_ref": task_revision.to_dict()}),
                                   revision=task_revision.revision,
                                   expected_revision=current_task.ref.revision,
                                   expected_version=current_task.version)
        self.store.put_identity(survivor, {
            "record_type": "work.observation", "observation_kind": "result",
            "assignment": root.ref.to_dict(), "generation": root.generation,
            "value": {"assignment_ref": root.ref.to_dict(), "project_ref": project.ref.to_dict(),
                       "task_ref": task_revision.to_dict(), "logical_request_key": "active-survivor",
                       "operation": "work.result.append", "delivery_state": "recorded", "outcome": "succeeded"},
            "lifecycle": "active"})
        attempt = ResourceRef(self.store.authority, "work.attempt", "active-attempt", "rev-1")
        self.store.put_identity(attempt, {"project_ref": project.ref.to_dict(),
                                          "task_ref": task_revision.to_dict(), "lifecycle": "completed"})
        register_evidence(self.store)
        try:
            from tests.test_evidence_reclaim import _current_pack
        except ImportError:
            from test_evidence_reclaim import _current_pack
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        handler = EvidenceCommandHandler(
            self.store, Path(directory.name) / "managed", pack=_current_pack(),
            adopted_pins=[item.to_dict() for item in _current_pack().resources])
        submitted = handler.submit(
            b"active payload", actor=self.actor, logical_request_key="active-submit",
            project_ref=project.ref,
            task_ref=ResourceRef(task_revision.authority, task_revision.kind, task_revision.id),
            attempt_ref=ResourceRef(attempt.authority, attempt.kind, attempt.id),
            original_creator="fixture")
        service = SimpleNamespace(server=SimpleNamespace(owner=self.owner,
            state={"orchestrator_assignment_ref": root.ref.to_dict()}))
        capability = RetentionOwnerRead(service, evidence_handler=handler)
        handle = {"view": "reclaim-preview", "cutoff": "9999-01-01T00:00:00Z",
                  "cursor": "", "limit": 10}
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            held = capability.call({"request_key": "active-preview", "handle": handle},
                                   root=root, actor=self.actor)
        self.assertEqual(held["items"][0]["hold"], "in-flight-recovery")
        self.assertFalse(held["items"][0]["eligible"])
        managed_path = Path(directory.name) / "managed" / handler.status(
            submitted["revision_ref"], actor=self.actor)["manifest"]["storage"]["location"]
        managed_path.unlink()
        survivor_record = self.store.get_identity(survivor)
        self.store.revise_identity(survivor, dict(survivor_record.payload, lifecycle="completed"),
                                   revision="rev-2", expected_revision=survivor.revision,
                                   expected_version=survivor_record.version)
        with patch("otto.portfolio.retention_owner_read.USAGE_PROJECT_ID", project.ref.id):
            missing = capability.call({"request_key": "missing-preview", "handle": handle},
                                      root=root, actor=self.actor)
        self.assertEqual(missing["items"][0]["hold"], "unavailable")
        self.assertFalse(missing["items"][0]["eligible"])


if __name__ == "__main__":
    unittest.main()

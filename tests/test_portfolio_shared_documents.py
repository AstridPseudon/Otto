"""Disposable DAT/WRK proofs for portfolio document scope and digest sync."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from herzchen.content import ContentCommandHandler, domain_contribution
from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.content.packets import ContextPacketService
from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.sheet import ProjectSheet
from herzchen.kernel.store import Store
from otto.hostctl.owner import host_domains
from otto.portfolio.documents import ProjectDocumentReader
from otto.portfolio.shared_documents import (
    _association, _document_ref, _link, _write, portfolio_documents, project_shared_documents,
    read_document_directory, remove_project_associations, sync_portfolio_documents,
)


class PortfolioSharedDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="portfolio-docs-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "new.sqlite", authority="test")
        self.store.register_domain_handler(host_domains())
        self.addCleanup(self.store.close)
        self.actor = AuthenticatedActor("test", "owner", "test-credential")
        self.scope = ResourceRef("test", "wrk.portfolio", "test-portfolio")
        self.graph = WorkGraph(self.store, actor=self.actor)
        self.content = ContentCommandHandler(self.store)
        self.owner = SimpleNamespace(graph=self.graph, content=self.content, store=self.store)
        self.session = SimpleNamespace(owner=self.owner, actor=self.actor, host=None, store=self.store)
        self.projects = [self.project("p" + str(i)) for i in range(3)]
        self.outside = self.graph.create_project(title="outside", logical_request_key="outside")
        self.reader = ProjectDocumentReader(sheet_reader=ProjectSheet(self.store, actor=self.actor),
            content_reader=self.content, visibility_reader=ContextPacketService(self.store.domain_handler((domain_contribution(),))))

    def project(self, key):
        return self.graph.create_project(title=key, logical_request_key=key,
            metadata={"otto_orchestrator": {"portfolio_ref": self.scope.to_dict()}})

    def sync(self, files):
        return sync_portfolio_documents(self.session, self.scope, {"files": files})

    def test_nested_archive_and_review_paths_round_trip_and_traversal_is_refused(self):
        files = {'archive/single-project/plan.md': 'historical plan',
                 'reviews/contracts/decision.md': 'accepted ruling'}
        self.assertEqual(self.sync(files)['outcome'], 'synced')
        for path, content in files.items():
            self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref,
                operation='read', path=path)['content'], content)
        self.assertEqual(self.sync(files)['outcome'], 'in_sync')
        with self.assertRaises(ValueError):
            self.sync({'../escape.md': 'invalid'})

    def test_manager_worker_read_only_and_outside_project_hidden(self):
        result = self.sync({"contract.md": "Contract frozen"})
        self.assertEqual(result["outcome"], "synced")
        self.assertEqual(len(result["attached"]), 3)
        ref = _document_ref(self.scope, "contract.md")
        for role in ("manager", "worker"):
            actor = AuthenticatedActor("test", role, "test-" + role)
            listed = self.reader.list_documents(self.projects[2].ref, actor=actor, roles=(role,))
            self.assertEqual(len(listed["documents"]), 1, listed)
            read = self.reader.read_document(self.projects[2].ref, ref, actor=actor, roles=(role,))
            self.assertEqual(read.get("content"), "Contract frozen", read)
            self.assertEqual(self.reader.read_document(self.outside.ref, ref, actor=actor)["outcome"], "unavailable")
            authoring = DocumentAuthoringHandler(self.store)
            edit = authoring.open_owned(ref, actor, request_id="worker-edit:" + role)
            self.assertEqual(edit.open_result.status, "ineligible")
            self.assertEqual(edit.projection.reason, "read_only_document")
        self.assertEqual(project_shared_documents(self.owner, self.outside.ref)["documents"], [])

    def test_conflicts_keep_otto_edits_and_enroll_later_project(self):
        self.sync({"spec.md": "original"})
        newcomer = self.project("later")
        self.assertEqual(project_shared_documents(self.owner, newcomer.ref)["documents"], [])
        result = self.sync({"spec.md": "original"})
        self.assertEqual(len(result["attached"]), 1)
        self.assertEqual(result["recorded"], [])
        self.assertEqual(len(project_shared_documents(self.owner, newcomer.ref)["documents"]), 1)
        self.assertEqual(self.sync({"spec.md": "new disk"})["recorded"], ["spec.md"])
        _write(self.owner, self.actor, self.scope, _document_ref(self.scope, "spec.md"), "Otto edit")
        held = self.sync({"spec.md": "new disk"})
        self.assertEqual(held["documents"][0]["state"], "otto_newer")
        conflict = self.sync({"spec.md": "disk edit too"})
        self.assertEqual(conflict["documents"][0]["state"], "conflict")
        self.assertEqual(conflict["recorded"], [])
        read = portfolio_documents(self.session, self.scope, operation="read", path="spec.md")
        self.assertEqual(read["content"], "Otto edit")
        self.assertEqual(self.sync({})["documents"][0]["state"], "removed_from_run_dir")

    def test_foreign_portfolio_and_non_orchestrator_cannot_sync(self):
        self.session.host = {"principal": "worker", "portfolio_ref": self.scope.to_dict()}
        self.session.root_assignment = lambda: SimpleNamespace(principal="worker", role="worker")
        with self.assertRaises(PermissionError):
            self.sync({"no.md": "no"})
        with self.assertRaises(PermissionError):
            portfolio_documents(self.session, ResourceRef("test", "wrk.portfolio", "other"))

    def test_detach_unlinks_only_project_and_preserves_document(self):
        self.sync({"spec.md": "frozen"})
        external = _document_ref(self.scope, "extra.md")
        _write(self.owner, self.actor, self.scope, external, "Added directly through DAT")
        _link(self.owner, self.actor, _association(self.projects[0].ref, "extra.md", external))
        receipts = remove_project_associations(self.owner, self.projects[0].ref, self.scope, actor=self.actor)
        self.assertEqual(len(receipts), 2)
        self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref)["documents"], [])
        self.assertEqual(self.reader.list_documents(self.projects[0].ref, actor=self.actor)["documents"], [])
        self.assertEqual(len(project_shared_documents(self.owner, self.projects[1].ref)["documents"]), 1)
        self.assertEqual(portfolio_documents(self.session, self.scope, operation="read", path="spec.md")["content"], "frozen")

    def test_sync_transaction_rolls_back_failed_associations(self):
        from unittest.mock import patch
        with patch("otto.portfolio.shared_documents._link", side_effect=RuntimeError("fail")):
            with self.assertRaises(RuntimeError):
                self.sync({"broken.md": "never committed"})
        self.assertEqual(portfolio_documents(self.session, self.scope)["documents"], [])
        self.assertFalse(self.content.read(_document_ref(self.scope, "broken.md")))

    def test_bound_manager_read_has_portfolio_section_and_unambiguous_path(self):
        from otto.hostctl.serve import HostOwnerService
        from otto.portfolio.manager_journey_service import _CALLER
        self.sync({"spec.md": "Portfolio contract"})
        server = SimpleNamespace(owner=self.owner,
            state={"project_ref": self.projects[2].ref.to_dict(), "manager": "p3-manager"},
            _documents=lambda ref: [{"path": "spec.md", "role": "notes", "revision_ref": {}, "text": "Project contract"}])
        with self.assertRaises(PermissionError):
            HostOwnerService._project_documents(server, {"command": "project-documents"})
        token = _CALLER.set({"role": "manager", "principal": "p3-manager"})
        try:
            listed = HostOwnerService._project_documents(server, {"command": "project-documents", "operation": "list"})
            self.assertEqual(listed["documents"][0]["path"], "spec.md")
            self.assertEqual(listed["portfolio"][0]["path"], "portfolio/spec.md")
            read = HostOwnerService._project_documents(server,
                {"command": "project-documents", "operation": "read", "path": "portfolio/spec.md"})
            self.assertEqual(read["content"], "Portfolio contract")
            local = HostOwnerService._project_documents(server,
                {"command": "project-documents", "operation": "read", "path": "spec.md"})
            self.assertEqual(local["content"], "Project contract")
        finally:
            _CALLER.reset(token)

    def test_stale_assignment_cannot_write_and_current_orchestrator_can(self):
        self.session.host = {"principal": "orchestrator", "portfolio_ref": self.scope.to_dict(), "root_generation": 1}
        assignment = SimpleNamespace(principal="orchestrator", role="orchestrator", scope=self.scope,
                                     generation=2, status="queued")
        self.session.root_assignment = lambda: assignment
        self.session.binding = SimpleNamespace(authenticated_actor=lambda value: AuthenticatedActor("test", value, "test-credential"))
        with self.assertRaises(PermissionError):
            self.sync({"no.md": "no"})
        assignment.generation = 1
        self.assertEqual(self.sync({"spec.md": "allowed"})["recorded"], ["spec.md"])
        assignment.status = "completed"
        with self.assertRaises(PermissionError):
            self.sync({"spec.md": "refused"})

    def test_directory_utf8_depth_and_symlink_checks(self):
        root = Path(self.temp.name) / "input"
        root.mkdir()
        nested = root / "a" / "b" / "c" / "d"
        nested.mkdir(parents=True)
        (nested / "spec.md").write_text("Unicode €", encoding="utf-8")
        self.assertEqual(read_document_directory(root)["files"], {"a/b/c/d/spec.md": "Unicode €"})
        (root / "link.md").symlink_to(nested / "spec.md")
        with self.assertRaises(ValueError):
            read_document_directory(root)
        (root / "link.md").unlink()
        (nested / "too-deep").mkdir()
        with self.assertRaises(ValueError):
            read_document_directory(root)
        with self.assertRaises(ValueError):
            self.sync({"../outside.md": "no"})


if __name__ == "__main__":
    unittest.main()

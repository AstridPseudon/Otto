"""Shared portfolio reads follow canonical DAT document associations."""
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
    _association, _document_ref, _link, _write, portfolio_documents,
    project_shared_documents, remove_project_associations,
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

    def attach(self, path, text, project=None, *, namespace=None):
        project = project or self.projects[0]
        ref = _document_ref(self.scope, path, root_namespace=namespace)
        _write(self.owner, self.actor, self.scope, ref, text)
        _link(self.owner, self.actor, _association(project.ref, path, ref, root_namespace=namespace))
        return ref

    def test_read_path_uses_document_associations_and_preserves_direct_edits(self):
        ref = self.attach("spec.md", "Canonical content")
        self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref,
            operation="read", path="spec.md")["content"], "Canonical content")
        self.assertEqual(portfolio_documents(self.session, self.scope, operation="read", path="spec.md")["content"],
                         "Canonical content")
        _write(self.owner, self.actor, self.scope, ref, "Owner authored revision")
        self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref,
            operation="read", path="spec.md")["content"], "Owner authored revision")
        self.assertEqual(project_shared_documents(self.owner, self.outside.ref)["documents"], [])

    def test_new_association_is_visible_without_a_manifest_copy(self):
        self.attach("nested/archive/plan.md", "Existing DAT source")
        listing = project_shared_documents(self.owner, self.projects[0].ref)
        self.assertEqual([row["path"] for row in listing["documents"]], ["nested/archive/plan.md"])
        self.assertEqual(portfolio_documents(self.session, self.scope)["documents"][0]["path"], "nested/archive/plan.md")

    def test_manager_worker_read_only_and_outside_project_hidden(self):
        ref = self.attach("contract.md", "Contract frozen", project=self.projects[2])
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

    def test_detach_unlinks_associations_but_preserves_document(self):
        ref = self.attach("spec.md", "frozen")
        receipts = remove_project_associations(self.owner, self.projects[0].ref, self.scope, actor=self.actor)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref)["documents"], [])
        self.assertEqual(self.reader.list_documents(self.projects[0].ref, actor=self.actor)["documents"], [])
        self.assertEqual(self.content.read(ref)["revision"]["content"], "frozen")

    def test_namespaced_read_and_retire_unlink(self):
        self.attach("plan.md", "Scoped", namespace="root-a")
        self.assertEqual(portfolio_documents(self.session, self.scope, operation="read", path="plan.md",
                                             root_namespace="root-a")["content"], "Scoped")
        result = __import__("otto.portfolio.shared_documents", fromlist=["retire_portfolio_document"]).retire_portfolio_document(
            self.session, self.scope, "plan.md", root_namespace="root-a")
        self.assertEqual(result["outcome"], "retired")
        self.assertEqual(project_shared_documents(self.owner, self.projects[0].ref)["documents"], [])

    def test_bound_manager_read_has_portfolio_section_and_unambiguous_path(self):
        from otto.hostctl.serve import HostOwnerService
        from otto.portfolio.manager_journey_service import _CALLER
        self.attach("spec.md", "Portfolio contract", project=self.projects[2])
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

    def test_non_orchestrator_cannot_select_foreign_portfolio(self):
        self.session.host = {"principal": "worker", "portfolio_ref": self.scope.to_dict()}
        self.session.root_assignment = lambda: SimpleNamespace(principal="worker", role="worker")
        with self.assertRaises(PermissionError):
            portfolio_documents(self.session, ResourceRef("test", "wrk.portfolio", "other"))


if __name__ == "__main__":
    unittest.main()

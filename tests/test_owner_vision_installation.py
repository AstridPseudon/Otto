"""Connected owner/agent fixture; source pins here are fixture-only.

Actual public managed-source provisioning/readback is separately retained by
the installation custodian. These tests open only one tiny disposable Store.
"""
from copy import deepcopy
import unittest

from herzchen.content import ContentDocument
from herzchen.content.vision_queries import VisionAuthorizationError
from herzchen.contracts import ResourceRef
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.owner_vision import OwnerVision
from otto.portfolio.fixtures.vision import PAGES, frame_nodes
from otto.portfolio.tests import test_vision_authoring as authoring_fixture
from otto.portfolio.tests.test_vision_pack_and_command import managed_vision_pack
from herzchen.content.vision_pack import load_vision_pack


class OwnerVisionInstallationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = authoring_fixture.VisionAuthoringTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        from herzchen.domains.work import register_work
        register_work(self.fixture.store)
        from herzchen.domains.assessment.module import contribution
        self.fixture.store.register_domain_handler((contribution(),))
        self.owner = PortfolioOwnerBootstrap(self.fixture.store,
            binding=HerzchenBindingConfig("vision-test", "fixture-credential"), owner_actor="owner")
        self.editor = DocumentEditorHost(owner=self.owner, directory=self.fixture.root / "editor", secret=b"v"*32)
        self.managed = managed_vision_pack()
        self.selection = load_vision_pack(managed_pack=self.managed).selection()
        self.installation = OwnerVision(owner=self.owner, editor=self.editor,
            managed_pack=self.managed, expected_selection=self.selection)

    def test_one_surface_editor_and_cli_real_authoring_connected_fixture(self):
        refs = {name: self.installation.authoring.creation_ref("connected:"+name) for name,*_ in PAGES}
        definition = {"pack_id":"vision", "source_revision":self.managed.source.source_revision,
            "resource_path":"schemas/vision-node.json", "resource_sha256":self.installation.pack.definition_pin.digest,
            "host_contract":"vision-inline.v1"}
        nodes = frame_nodes(definition, refs)
        for name,*_ in PAGES:
            result = self.editor.dispatch({"command":"vision", "operation":"create",
                "arguments":{"content":nodes[name]}, "request_key":"connected:"+name}, actor=self.owner.owner_actor)
            self.assertIsNotNone(result["revision_ref"])
        request = {"command":"vision", "operation":"query", "arguments":{"root_ref":refs["frame"].to_dict(), "preset":"outline"}}
        from otto.portfolio.cli import main
        self.assertIs(self.editor.vision_operations, self.installation.surface)
        self.assertEqual(len(self.editor.dispatch(request, actor=self.owner.owner_actor)["rows"]),14)
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["vision","--request-json",__import__("json").dumps(request)],
                                  vision_operations=self.installation.surface),0)
        with self.assertRaises(PermissionError):
            self.editor.dispatch(request, actor=self.owner.binding.authenticated_actor("agent"))
        wrong = deepcopy(self.selection); wrong["selection_digest"] = "0"*64
        with self.assertRaises(PermissionError):
            OwnerVision(owner=self.owner, editor=self.editor, managed_pack=self.managed, expected_selection=wrong)

    def test_agent_uses_own_identity_current_grant_visibility_and_revoked_membership(self):
        project = self.owner.graph.create_project(title="Shared fixture", logical_request_key="shared-project")
        project_ref = project.ref
        actor = self.owner.binding.authenticated_actor("agent")
        grant = ProjectReadGrant(actor,(project_ref.id,),"fixture-current","v1")
        ref = ResourceRef("vision-test","dat.content.document","shared-frame")
        node = deepcopy(self.fixture.nodes["frame"]); node["members"] = []
        node["definition"] = {"pack_id":"vision", "source_revision":self.managed.source.source_revision,
            "resource_path":"schemas/vision-node.json", "resource_sha256":self.installation.pack.definition_pin.digest,
            "host_contract":"vision-inline.v1"}
        document = ContentDocument(ref,"vision","shared","write","owner",authoring_scope=project_ref)
        draft={"document":document,"content":node}
        opened=self.editor.authoring.materialise(document,self.owner.owner_actor,request_id="shared-open",initial_content=draft,base_revision="initial")
        self.editor.authoring.finish(opened,request_id="shared-finish",draft=draft)
        active = {ref.id}
        membership=lambda p,d,a: p==project_ref and a==actor and d.id in active
        request={"command":"vision","operation":"read","arguments":{"document_ref":ref.to_dict(),"project_ref":project_ref.to_dict()}}
        result=self.installation.agent_read(request,actor=actor,project_ref=project_ref,grant=grant,membership_reader=membership)
        self.assertEqual(result["status"],"ok")
        # Exercise actual bound ingress and canonical document membership,
        # rather than substituting a handler or granting the owner identity.
        from types import SimpleNamespace
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
        manager=self.owner.assignments.assign(project_ref,role="manager",principal="agent",
            session="agent-session",logical_request_key="vision-manager")
        granted_owner=PortfolioOwnerBootstrap(self.fixture.store,
            binding=HerzchenBindingConfig("vision-test","fixture-credential"),owner_actor="owner",
            project_read_grant=ProjectReadGrant(self.owner.owner_actor,(project_ref.id,),"fixture-owner","v1"))
        self.installation.surface.dispatch({"command":"vision","operation":"attach",
            "arguments":{"project_ref":project_ref.to_dict(),"document_refs":[ref.to_dict()]},
            "request_key":"vision-shared-membership"})
        state={"project_ref":project_ref.to_dict(),"assignment_ref":manager.ref.to_dict(),
            "manager":"agent","manager_generation":manager.generation}
        server=SimpleNamespace(owner=granted_owner,portfolio=None,state=state,due_port=None,
            _execution=lambda **kw: None,vision=self.installation,document_editor=self.editor)
        ingress=OwnerAuthoringIngress(actor=granted_owner.owner_actor,
            owner_actor=granted_owner.owner_actor,directory=self.fixture.root/"vision-owner-ipc")
        service=ManagerJourneyService(server=server,host=None,run_path=self.fixture.root,
            workspace=self.fixture.root,authoring_authorizer=ingress.authorize)
        caller={"role":"manager","principal":"agent","assignment_ref":manager.ref.to_dict(),
                "generation":manager.generation}
        self.assertEqual(service.dispatch_bound(caller,request)["status"],"ok")
        with self.assertRaises(PermissionError):
            service.dispatch_bound({**caller,"principal":"foreign"},request)
        with self.assertRaises(PermissionError):
            service.dispatch_bound({**caller,"generation":manager.generation+1},request)
        with self.assertRaises(PermissionError):
            service.dispatch_bound(caller,{**request,"operation":"snapshot"})
        with self.assertRaises(PermissionError):
            service(request)
        owner_request={**request,"arguments":{"document_ref":ref.to_dict()}}
        published=ingress.publish({"schema":ingress.schema,"request":owner_request})
        self.assertEqual(service(owner_request)["status"],"ok")
        self.assertFalse(published["provider_called"])
        active.clear()
        with self.assertRaises(VisionAuthorizationError):
            self.installation.agent_read(request,actor=actor,project_ref=project_ref,grant=grant,membership_reader=membership)
        with self.assertRaises(PermissionError):
            self.installation.agent_read({**request,"operation":"snapshot"},actor=actor,project_ref=project_ref,grant=grant,membership_reader=membership)
        with self.assertRaises(PermissionError):
            self.installation.agent_read(request,actor=actor,project_ref=ResourceRef("vision-test","work.project","foreign","rev-1"),grant=grant,membership_reader=membership)

    def test_vision_project_document_read_uses_live_association_without_manifest(self):
        from otto.portfolio.shared_documents import _association, _document_ref, _link, _write, project_shared_documents
        portfolio = ResourceRef("vision-test", "wrk.portfolio", "vision-shared")
        project = self.owner.graph.create_project(title="Vision shared docs",
            logical_request_key="vision-shared-project",
            metadata={"otto_orchestrator": {"portfolio_ref": portfolio.to_dict()}})
        document = _document_ref(portfolio, "guide.md")
        _write(self.owner, self.owner.owner_actor, portfolio, document, "Vision can still read this document.")
        _link(self.owner, self.owner.owner_actor, _association(project.ref, "guide.md", document))
        result = project_shared_documents(self.owner, project.ref, operation="read", path="guide.md")
        self.assertEqual(result["outcome"], "read")
        self.assertEqual(result["content"], "Vision can still read this document.")

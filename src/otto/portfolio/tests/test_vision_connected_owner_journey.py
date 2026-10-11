"""D05 connected owner/editor/agent proof over the supported Vision ports."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from herzchen.authoring import domain_contribution as edt_domain
from herzchen.content import (
    VisionAttachment,
    VisionCommandSurface,
    VisionQueryService,
    VisionReorganizer,
    domain_contribution as content_domain,
    load_vision_pack,
)
from herzchen.content.packets import ContextPacketService, domain_contribution as packet_domain
from herzchen.content.vision import (
    ManagedVisionDefinitions,
    RESOURCE_PATH,
    VisionValidator,
)
from herzchen.content.vision_authoring import VisionAuthoring
from herzchen.contracts import AuthenticatedActor, ReferenceBinding, ResourceRef
from herzchen.content.model import DocumentAssociation
from herzchen.content.vision_queries import vision_attachment_key
from herzchen.domains.assessment.module import contribution as assessment_domain
from herzchen.domains.work import WorkModule, contributions
from herzchen.kernel.store import Store
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.tests.test_vision_pack_and_command import managed_vision_pack


class _ReadOnlyAuthoring:
    def create(self, *_args, **_kwargs):
        raise AssertionError("representative agent was given no authoring route")


class ConnectedVisionOwnerJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="vision-d05-owner-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store.create(root / "fixture.sqlite", authority="vision-d05-owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler((
            content_domain(),
            edt_domain(),
            packet_domain(),
            *contributions(include_assignment_resources=True),
            assessment_domain(),
        ))
        self.actor = AuthenticatedActor("vision-d05-owner", "person", "owner-credential")
        self.owner = PortfolioOwnerBootstrap(
            self.store,
            binding=HerzchenBindingConfig("vision-d05-owner", "owner-credential"),
            owner_actor="person",
        )
        project = WorkModule(self.store, actor=self.actor).create_project(
            title="Vision connected proof", logical_request_key="vision-d05-project",
        )
        self.project = replace(project.ref, revision=None)
        self.pack = load_vision_pack(managed_pack=managed_vision_pack())
        pin = self.pack.definition_pin
        self.validator = VisionValidator(
            ManagedVisionDefinitions((managed_vision_pack(),), (pin,)),
            target_reader=self._target_reader,
        )
        self.host = DocumentEditorHost(
            owner=self.owner,
            directory=root / "editor",
            secret=b"x" * 32,
            vision_validator=self.validator,
        )
        self.authoring = VisionAuthoring(self.host.authoring, self.actor)
        self.surface = VisionCommandSurface(
            authoring=self.authoring,
            queries=VisionQueryService(ContextPacketService(self.store), actor=self.actor),
            pack=self.pack,
            reorganizer=VisionReorganizer(self.host.authoring, self.actor),
            attachment=VisionAttachment(self.host.authoring.content, self.actor),
        )
        self.host.vision_operations = self.surface

    def _target_reader(self, binding, actor=None):
        try:
            return ContextPacketService(self.store).resolve_reference(
                binding, actor=actor or self.actor,
            )
        except Exception:
            return None

    def dispatch(self, operation, *, request_key=None, arguments=None):
        request = {"command": "vision", "operation": operation, "arguments": arguments or {}}
        if request_key is not None:
            request["request_key"] = request_key
        return self.host.dispatch(request, actor=self.actor)

    def test_person_to_agent_connected_journey(self):
        root_ref = self.authoring.creation_ref("journey:root")
        node_ref = self.authoring.creation_ref("journey:offline")
        definition = {
            "pack_id": "vision",
            "source_revision": self.pack.source_revision,
            "resource_path": RESOURCE_PATH,
            "resource_sha256": next(item.digest for item in self.pack.resources if item.path == RESOURCE_PATH),
            "host_contract": "vision-inline.v1",
        }
        root = {
            "schema": "vision.node.v1", "definition": definition, "kind": "product",
            "title": "Frame", "summary": "Recoverable collaborative work.",
            "maturity": "proposed", "as_of": "2026-10-11",
            "body_markdown": "Preserve user intent across a disconnect.",
            "navigation_parent": None, "applies_to": [], "relationships": [],
            "sources": [], "work_refs": [], "repository": None,
            "members": [ReferenceBinding(node_ref, "current").to_dict()],
        }
        node = {
            "schema": "vision.node.v1", "definition": definition, "kind": "concept",
            "title": "Offline work", "summary": "A recoverable disconnected edit.",
            "maturity": "proposed", "as_of": "2026-10-11",
            "body_markdown": "Reconcile alternatives without silent loss.",
            "navigation_parent": ReferenceBinding(root_ref, "current").to_dict(),
            "applies_to": [], "relationships": [], "sources": [], "work_refs": [],
            "repository": None, "members": None,
        }

        created_root = self.dispatch(
            "create", request_key="journey:root", arguments={
                "content": root, "project_ref": self.project.to_dict(),
            },
        )
        created_node = self.dispatch(
            "create", request_key="journey:offline", arguments={
                "content": node, "project_ref": self.project.to_dict(),
            },
        )
        self.assertEqual(created_root["outcome"], "created")
        self.assertEqual(created_node["outcome"], "created")
        self.assertEqual(created_root["resource_selection"]["host_contract"], "vision-inline.v1")

        attached = self.dispatch(
            "attach", request_key="journey:attach", arguments={
                "project_ref": self.project.to_dict(),
                "document_refs": [root_ref.to_dict(), node_ref.to_dict()],
            },
        )
        self.assertEqual(attached["outcome"], "attached")
        self.assertEqual(self.dispatch("query", arguments={
            "root_ref": root_ref.to_dict(), "preset": "outline",
        })["rows"][0]["ref"], root_ref.to_dict())

        reorganized = self.dispatch(
            "reorganize", request_key="journey:reorganize", arguments={
                "document_ref": node_ref.to_dict(),
                "changes": {"title": "Recoverable offline work", "navigation_parent": None},
            },
        )
        self.assertEqual(reorganized["outcome"], "updated")
        history = self.dispatch("history", arguments={"document_ref": node_ref.to_dict()})
        self.assertGreaterEqual(history["count"], 2)
        context = self.dispatch("context", arguments={
            "root_ref": root_ref.to_dict(), "focus_refs": [node_ref.to_dict()],
            "question": "How is disconnected work kept recoverable?",
            "implementation_context": {"status": "observed", "items": []},
            "direction_context": {"status": "adopted", "ref": {"id": "direction", "revision": "rev-1"}},
            "task_context": {"status": "authorized", "ref": {"id": "task", "revision": "rev-1"}},
        })
        self.assertFalse(context["provider_called"])
        self.assertEqual(context["effects_started"], False)

        snapshot = self.dispatch("snapshot", request_key="journey:snapshot", arguments={
            "scope": "collection", "root_ref": root_ref.to_dict(), "label": "Journey checkpoint",
        })
        replay = self.dispatch("snapshot", request_key="journey:snapshot", arguments={
            "scope": "collection", "root_ref": root_ref.to_dict(), "label": "Journey checkpoint",
        })
        self.assertEqual(snapshot["outcome"], "created")
        self.assertEqual(replay["outcome"], "replayed")

        agent = AuthenticatedActor("vision-d05-owner", "representative-agent", "agent-credential")
        grant = {"project_ids": [self.project.id], "principal": agent}
        resolver = ContextPacketService(self.store)

        def membership(project_ref, document_ref, actor):
            if project_ref.id != self.project.id:
                return False
            association = DocumentAssociation(
                self.project, "project.documents", vision_attachment_key(document_ref),
                ReferenceBinding(document_ref, "current"),
            )
            record = self.store.consumer().get_identity(ResourceRef(
                self.project.authority, "document-association", association.identity,
            ))
            return record is not None and record.payload.get("active") is not False

        agent_surface = VisionCommandSurface(
            authoring=_ReadOnlyAuthoring(),
            queries=VisionQueryService(
                resolver, actor=agent, grant=grant, membership_reader=membership,
            ),
            pack=self.pack,
        )
        received = agent_surface.dispatch({
            "command": "vision", "operation": "read", "arguments": {
                "document_ref": node_ref.to_dict(), "project_ref": self.project.to_dict(),
            },
        })
        self.assertEqual(received["status"], "ok")
        self.assertEqual(received["ref"], node_ref.to_dict())
        self.assertEqual(received["resource_selection"]["selection_digest"], self.pack.digest)
        self.assertEqual(received["revision_ref"]["authority"], node_ref.authority)


if __name__ == "__main__":
    unittest.main()

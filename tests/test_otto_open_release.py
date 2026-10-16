"""The ``otto`` entry, ``open`` over the project folder, the late-writer finish and ``release`` of a parked session.

The console script resolves to the portfolio CLI's ``main`` and runs a verb. A folder
edit made through ``open folder`` round-trips into the project. A late writer's finish
is refused with the base it lost to and never parks the session. ``otto release``
frees a session the lifecycle parked for recovery. Real owner Stores, real lanes.
"""
from contextlib import redirect_stdout
from hashlib import sha256
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tomllib
import unittest

from herzchen.content.authoring import DocumentAuthoringHandler
from herzchen.content.model import ContentDocument, ContentRevision
from herzchen.content.packets import domain_contribution as packets
from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.domains.assessment.module import contribution as assessment
from otto.portfolio import cli
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.fixtures import project_authoring
from otto.portfolio.fixtures.project_folder import ProjectFolderProof
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap

PROJECT_REF = {"authority": "owner", "kind": "work.project", "id": "p1", "revision": "r1"}


class _ShowPortfolio:
    """One project row, so the console verb runs without a Store."""

    def list_work(self, *, actor, view, project_ref, limit):
        return {"outcome": "listed", "projects": [{"project_ref": PROJECT_REF, "task_count": 0}], "items": []}


class ConsoleEntryTests(unittest.TestCase):
    def test_otto_script_resolves_to_the_portfolio_cli_and_runs_a_verb(self):
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as stream:
            scripts = tomllib.load(stream)["project"]["scripts"]
        self.assertEqual(scripts["otto"], "otto.portfolio.cli:main")
        module, _, attribute = scripts["otto"].partition(":")
        entry = getattr(import_module(module), attribute)
        self.assertIs(entry, cli.main)
        out = StringIO()
        with redirect_stdout(out):
            code = entry(["show", "project", "--project-ref", json.dumps(PROJECT_REF), "--actor", "owner"],
                         portfolio=_ShowPortfolio())
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["schema"], "otto.show.project.v1")


class FolderOpenTests(unittest.TestCase):
    """``open folder`` checks a project folder out to disk, takes an edit back in and releases it."""

    def setUp(self):
        self.f = ProjectFolderProof()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.ref = self.f.import_files(key="folder-import")["project_ref"]

    def run_open(self, *argv):
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["open", "folder", *argv], portfolio=self.f.portfolio)
        return code, json.loads(out.getvalue())

    def test_folder_edit_round_trips_through_open_folder_check_in_and_release(self):
        ref = json.dumps(self.ref)
        code, exported = self.run_open("export", "--project-ref", ref, "--actor", "owner",
                                       "--request-key", "folder-export")
        self.assertEqual(code, 0, exported)
        self.assertEqual(exported["files"]["README.md"], "[topic](docs/research/topic.md)")
        directory = self.f.root / "folder-work"
        code, opened = self.run_open("start", "--project-ref", ref, "--actor", "owner",
                                     "--request-key", "folder-open", "--directory", str(directory))
        self.assertEqual(code, 0, opened)
        self.assertEqual(opened["outcome"], "checked_out", opened)
        readme = directory / "README.md"
        self.assertEqual(readme.read_text(encoding="utf-8"), "[topic](docs/research/topic.md)")
        readme.write_text("# Edited from the folder\n", encoding="utf-8")
        code, finished = self.run_open("finish", "--project-ref", ref, "--actor", "owner",
                                       "--session-id", opened["session_id"], "--request-key", "folder-check-in",
                                       "--directory", str(directory))
        self.assertEqual(code, 0, finished)
        self.assertEqual(finished["outcome"], "finished", finished)
        verified = self.f.portfolio.export_folder(self.ref, actor="owner", request_id="folder-verify")
        self.assertEqual(verified["files"]["README.md"], "# Edited from the folder\n")
        code, released = self.run_open("release", "--project-ref", ref, "--actor", "owner",
                                       "--session-id", opened["session_id"], "--request-key", "folder-release")
        self.assertEqual(code, 0, released)
        self.assertEqual(released["outcome"], "released", released)


class LateWriterTests(unittest.TestCase):
    """The editor host's finish refuses a late writer before the session is claimed."""

    def setUp(self):
        self.f = project_authoring.ProjectAuthoringProof()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.store.register_domain_handler((packets(), assessment()))
        self.project = {k: v for k, v in self.f.create().items() if k != "revision"}
        binding = self.f.owner.binding
        self.owner = PortfolioOwnerBootstrap(self.f.store, binding=binding, owner_actor="owner",
            project_read_grant=ProjectReadGrant(binding.authenticated_actor("owner"),
                (self.project["id"],), "fixture-owner", "1"))
        created = self.f.portfolio.create_document(self.project, actor="owner", request_id="doc",
            content={"text": "Opening"}, access_mode="write", document_id="late-doc")
        self.doc = {k: v for k, v in created["document_ref"].items() if k != "revision"}
        self.f.portfolio.link_document(self.project, self.doc, actor="owner", request_id="link",
                                       access_mode="read")
        self.project = {k: v for k, v in self.project.items() if k != "revision"}
        self.editor = DocumentEditorHost(owner=self.owner, directory=self.f.root / "editor",
                                         secret=b"s" * 32, clock=lambda: 1000.0)

    def call(self, operation, key, **fields):
        request = {"command": "document-authoring", "operation": operation, "request_key": key,
                   "project_ref": self.project, "document_ref": self.doc, **fields}
        return dict(self.editor.dispatch(request, actor=self.editor.actor))

    def head(self):
        return self.owner.content.read(ResourceRef.from_dict(self.doc))["current_revision"]["revision"]

    def recovery(self, session_id):
        return self.editor.dispatch({"command": "document-authoring", "operation": "recover",
            "request_key": "recover-" + session_id, "session_id": session_id}, actor=self.editor.actor)

    def open_handle(self, key):
        opened = self.call("open", key)
        self.assertEqual(opened["outcome"], "opened", opened)
        return opened["handle"]

    def publish_second_writer(self):
        ref = ResourceRef.from_dict(self.doc)
        document = ContentDocument.from_dict(self.f.store.get_identity(ref).payload["document"])
        other = ContentRevision(ref, "rev-other", {"text": "Other writer"}, self.owner.owner_actor,
                                parent_revision=self.head())
        context = TransactionContext(self.owner.owner_actor, "other-writer",
                                     sha256(b"other-writer").hexdigest(), expected_revision=self.head())
        self.owner.content.execute(self.owner.content.build_append_revision(context, document, other))
        return self.head()

    def test_late_writer_finish_is_refused_naming_the_base_and_never_parked(self):
        handle = self.open_handle("open-late")
        self.call("save", "draft-late", handle=handle, editor_buffer={"content": {"text": "Stale draft"}})
        other_head = self.publish_second_writer()
        refused = self.call("finish", "late-finish", handle=handle,
                            expected_base_revision=handle["base_revision"])
        self.assertEqual(refused["outcome"], "conflict", refused)
        self.assertEqual(refused["error"]["code"], "stale_base", refused)
        self.assertIn("expected_base_revision", refused["error"]["message"])
        self.assertIn(other_head, refused["error"]["message"])
        self.assertEqual(refused["current_revision"], other_head)
        self.assertFalse(refused["dat_revision_advanced"], refused)
        self.assertEqual(self.head(), other_head)
        state = self.recovery(handle["session_id"])
        self.assertFalse(state["recovery_pending"], state)
        self.assertEqual(state["status"], "open", state)

    def test_finish_with_the_current_base_checks_in(self):
        handle = self.open_handle("open-current")
        self.call("save", "draft-current", handle=handle, editor_buffer={"content": {"text": "Current draft"}})
        head = self.head()
        finished = self.call("finish", "current-finish", handle=handle,
                             expected_base_revision=handle["base_revision"])
        self.assertEqual(finished["outcome"], "finished", finished)
        self.assertTrue(finished["dat_revision_advanced"], finished)
        self.assertNotEqual(self.head(), head)

    def test_parked_session_is_freed_by_otto_release(self):
        handle = self.open_handle("open-park")
        self.call("save", "draft-park", handle=handle, editor_buffer={"content": {"text": "Parked draft"}})
        original = DocumentAuthoringHandler.lifecycle_handler

        def failing_apply(authoring, material, *, request_id):
            handler = original(authoring, material, request_id=request_id)

            def apply(*args, **kwargs):
                raise RuntimeError("injected failure after the finish claim")
            return SimpleNamespace(validate=handler.validate, apply=apply)

        with patch.object(DocumentAuthoringHandler, "lifecycle_handler", failing_apply):
            parked = self.call("finish", "park-finish", handle=handle)
        self.assertEqual(parked["outcome"], "recovery_pending", parked)
        self.assertTrue(self.recovery(handle["session_id"])["recovery_pending"])
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["release", "--session-id", handle["session_id"], "--request-key", "release-park"],
                            editor_host=self.editor)
        released = json.loads(out.getvalue())
        self.assertEqual(code, 0, released)
        self.assertEqual(released["outcome"], "released", released)
        self.assertFalse(self.recovery(handle["session_id"])["recovery_pending"])
        reopened = self.call("open", "open-after-release")
        self.assertEqual(reopened["outcome"], "opened", reopened)


if __name__ == "__main__":
    unittest.main()

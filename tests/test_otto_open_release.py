"""The ``otto`` entry, ``open`` over the project folder, the late-writer finish and ``release`` of a parked session.

``otto`` is a thin client: outside the owner it parses its verb and forwards the argv
through the owner lane, and the owner runs the verb with its own portfolio, editor host
and status session. The lane tests run a real owner service over real lanes
(HostctlFixture) and open no Store in the client. The direct tests drive the owner-side
verbs in-process with an injected portfolio and editor host.
"""
from contextlib import redirect_stdout
from hashlib import sha256
from importlib import import_module
import io
from io import StringIO
import json
import os
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
from herzchen.kernel.store import Store
from otto.hostctl import config as host_config
from otto.hostctl.owner import HostSession
from otto.portfolio import cli
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.fixtures import project_authoring
from otto.portfolio.fixtures.project_folder import ProjectFolderProof
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from test_hostctl_cli import HostctlFixture

PORTFOLIO = "claude-code-portfolio"
OWNER = "otto-test-owner"


class ConsoleEntryTests(unittest.TestCase):
    def test_otto_script_resolves_to_the_thin_client(self):
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as stream:
            scripts = tomllib.load(stream)["project"]["scripts"]
        self.assertEqual(scripts["otto"], "otto.portfolio.cli:client_main")
        module, _, attribute = scripts["otto"].partition(":")
        entry = getattr(import_module(module), attribute)
        self.assertIs(entry, cli.client_main)

    def test_client_without_a_portfolio_refuses_and_opens_no_store(self):
        out = StringIO()
        with patch.object(Store, "open", wraps=Store.open) as opened, redirect_stdout(out):
            code = cli.client_main(["show", "project", "--project-ref", "{}", "--actor", OWNER])
        self.assertEqual(code, 2, out.getvalue())
        self.assertEqual(opened.call_count, 0)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "usage")


class OwnerRouteTests(HostctlFixture):
    """``otto`` through the owner lane: the verb runs in the owner, the client opens no Store."""

    def setUp(self):
        super().setUp()
        self._init()
        self._register()

    def otto(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.client_main(["--home", self.home, "--portfolio", PORTFOLIO, *argv])
        return code, json.loads(out.getvalue())

    def _owner_for(self, project_id, callback):
        # The owner's read grant is for the one project under test; None grants none.
        grant = (project_id,) if project_id else ()

        def run():
            config = host_config.load(Path(self.home))
            with HostSession(config, host=config["hosts"]["claude-code"], project_ids=grant) as session:
                return callback(session)
        return self.owner_service.call(run)

    def _project(self):
        save_file = Path(self.bundle).parent / "open-plan.json"
        save_file.write_text(json.dumps({"project": {"title": "Open plan", "outcome": "Edit from otto"},
                                         "tasks": [{"id": "t1", "title": "Plan t1", "instructions": "Do t1",
                                                    "acceptance": "Done t1"}]}))
        code, saved = self.otto("save", str(save_file), "--actor", OWNER)
        self.assertEqual(code, 0, saved)
        return {k: v for k, v in saved["project_ref"].items() if k != "revision"}

    def _document(self, project):
        def create(session):
            created = session.portfolio.create_document(project, actor=OWNER, request_id="open-doc",
                content={"text": "Opening"}, access_mode="write", document_id="open-doc")
            session.portfolio.link_document(project, {k: v for k, v in created["document_ref"].items() if k != "revision"},
                actor=OWNER, request_id="open-link", access_mode="read")
            return {k: v for k, v in created["document_ref"].items() if k != "revision"}
        return self._owner_for(project["id"], create)

    def _head(self, project, document):
        return self._owner_for(project["id"], lambda session: session.owner.content.read(
            ResourceRef.from_dict(document))["current_revision"]["revision"])

    def _open_args(self, project, document):
        return ["--project-ref", json.dumps(project), "--document-ref", json.dumps(document)]

    def test_save_resolves_relative_file_from_the_caller_directory(self):
        caller = Path(self.bundle).parent / "caller-a"
        owner = Path(self.bundle).parent / "owner-b"
        caller.mkdir()
        owner.mkdir()
        (caller / "project.json").write_text(json.dumps({
            "project": {"title": "Caller A", "outcome": "Caller data"},
            "tasks": [{"id": "caller-task", "title": "Caller task", "instructions": "Caller instructions",
                       "acceptance": "Caller acceptance"}],
        }), encoding="utf-8")
        (owner / "project.json").write_text(json.dumps({
            "project": {"title": "Owner B", "outcome": "Owner data"},
            "tasks": [{"id": "owner-task", "title": "Owner task", "instructions": "Owner instructions",
                       "acceptance": "Owner acceptance"}],
        }), encoding="utf-8")

        from otto.hostctl import cli as hostctl_cli
        await_owner_lane = hostctl_cli._await

        def await_from_owner_directory(*args, **kwargs):
            caller_directory = Path.cwd()
            os.chdir(owner)
            try:
                return await_owner_lane(*args, **kwargs)
            finally:
                os.chdir(caller_directory)

        with patch.object(hostctl_cli, "_await", await_from_owner_directory):
            original_directory = Path.cwd()
            os.chdir(caller)
            try:
                # Save options before the positional filename must still be reconstructed correctly.
                code, saved = self.otto("save", "--actor", OWNER, "--request-id", "caller-save", "project.json")
            finally:
                os.chdir(original_directory)

        self.assertEqual(code, 0, saved)
        self.assertEqual(saved["outcome"], "saved", saved)
        actual_title = self._owner_for(saved["project_ref"]["id"], lambda session:
            session.owner.graph.current(ResourceRef.from_dict(saved["project_ref"])).payload["title"])
        self.assertEqual(actual_title, "Caller A", saved)

    def test_otto_show_runs_through_the_owner_lane_and_opens_no_store(self):
        project = self._project()
        with patch.object(Store, "open", wraps=Store.open) as opened:
            code, shown = self.otto("show", "project", "--project-ref", json.dumps(project), "--actor", OWNER)
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["schema"], "otto.show.project.v1")
        self.assertIn("Plan t1", json.dumps(shown))
        self.assertEqual(opened.call_count, 0)

    def test_otto_status_runs_through_the_owner_lane(self):
        self._project()
        code, status = self.otto("status")
        self.assertEqual(code, 0, status)
        self.assertNotIn("error", status)

    def test_folder_edit_round_trips_through_otto_open_folder(self):
        imported = self._owner_for(None, lambda session: session.portfolio.import_folder(
            project_json={"title": "Folder plan", "outcome": "Edit in a folder"},
            files={"README.md": "# Before\n"}, actor=OWNER, request_id="folder-import"))
        ref = imported["project_ref"]
        ref_json = json.dumps(ref)
        directory = Path(self.bundle).parent / "folder-work"
        code, opened = self.otto("open", "folder", "start", "--project-ref", ref_json, "--actor", OWNER,
                                 "--request-key", "folder-open", "--directory", str(directory))
        self.assertEqual(code, 0, opened)
        self.assertEqual(opened["outcome"], "checked_out", opened)
        (directory / "README.md").write_text("# Edited through otto\n", encoding="utf-8")
        code, finished = self.otto("open", "folder", "finish", "--project-ref", ref_json, "--actor", OWNER,
                                   "--session-id", opened["session_id"], "--request-key", "folder-check-in",
                                   "--directory", str(directory))
        self.assertEqual(code, 0, finished)
        self.assertEqual(finished["outcome"], "finished", finished)
        exported = self._owner_for(None, lambda session: session.portfolio.export_folder(
            ref, actor=OWNER, request_id="folder-verify"))
        self.assertEqual(exported["files"]["README.md"], "# Edited through otto\n")

    def test_two_writers_racing_through_otto_open_refuse_the_late_one_and_never_park_it(self):
        project = self._project()
        document = self._document(project)
        args = self._open_args(project, document)
        code, opened = self.otto("open", "start", *args, "--request-key", "race-open")
        self.assertEqual(code, 0, opened)
        handle = opened["handle"]
        code, saved = self.otto("open", "autosave", *args, "--request-key", "race-save", "--handle-json",
                                json.dumps(handle), "--buffer-json", json.dumps({"content": {"text": "Stale draft"}}))
        self.assertEqual(code, 0, saved)

        def second_writer(session):
            ref = ResourceRef.from_dict(document)
            stored = ContentDocument.from_dict(session.store.get_identity(ref).payload["document"])
            head = session.owner.content.read(ref)["current_revision"]["revision"]
            other = ContentRevision(ref, "rev-other", {"text": "Other writer"}, session.owner.owner_actor,
                                    parent_revision=head)
            context = TransactionContext(session.owner.owner_actor, "other-writer",
                                         sha256(b"other-writer").hexdigest(), expected_revision=head)
            session.owner.content.execute(session.owner.content.build_append_revision(context, stored, other))
            return session.owner.content.read(ref)["current_revision"]["revision"]
        other_head = self._owner_for(project["id"], second_writer)
        code, refused = self.otto("open", "finish", *args, "--request-key", "race-finish", "--handle-json",
                                  json.dumps(handle))
        self.assertEqual(code, 4, refused)
        self.assertEqual(refused["outcome"], "conflict", refused)
        self.assertEqual(refused["error"]["code"], "stale_base", refused)
        self.assertEqual(refused["current_revision"], other_head)
        self.assertFalse(refused["dat_revision_advanced"], refused)
        code, released = self.otto("open", "release", *args, "--request-key", "race-release", "--handle-json",
                                   json.dumps(handle))
        self.assertEqual(code, 0, released)
        self.assertTrue(released["nonpublishing"], released)

    def test_parked_session_is_released_through_otto_release(self):
        project = self._project()
        document = self._document(project)
        args = self._open_args(project, document)
        code, opened = self.otto("open", "start", *args, "--request-key", "park-open")
        self.assertEqual(code, 0, opened)
        handle = opened["handle"]
        code, saved = self.otto("open", "autosave", *args, "--request-key", "park-save", "--handle-json",
                                json.dumps(handle), "--buffer-json", json.dumps({"content": {"text": "Parked draft"}}))
        self.assertEqual(code, 0, saved)
        original = DocumentAuthoringHandler.lifecycle_handler

        def failing_apply(authoring, material, *, request_id):
            handler = original(authoring, material, request_id=request_id)

            def apply(*apply_args, **kwargs):
                raise RuntimeError("injected failure after the finish claim")
            return SimpleNamespace(validate=handler.validate, apply=apply)

        with patch.object(DocumentAuthoringHandler, "lifecycle_handler", failing_apply):
            code, parked = self.otto("open", "finish", *args, "--request-key", "park-finish", "--handle-json",
                                     json.dumps(handle))
        self.assertEqual(parked["outcome"], "recovery_pending", parked)
        code, released = self.otto("release", "--session-id", handle["session_id"], "--request-key", "park-release")
        self.assertEqual(code, 0, released)
        self.assertEqual(released["outcome"], "released", released)
        code, reopened = self.otto("open", "start", *args, "--request-key", "park-reopen")
        self.assertEqual(code, 0, reopened)
        self.assertEqual(reopened["outcome"], "opened", reopened)


class FolderOpenTests(unittest.TestCase):
    """``open folder`` in-process: the owner verb with an injected portfolio."""

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
        # A checkout abandoned unchecked is released; this runs first because a check-in moves the project revision.
        code, abandoned = self.run_open("start", "--project-ref", ref, "--actor", "owner",
                                        "--request-key", "folder-open-abandoned", "--directory",
                                        str(self.f.root / "folder-abandoned"))
        self.assertEqual(code, 0, abandoned)
        code, released = self.run_open("release", "--project-ref", ref, "--actor", "owner",
                                       "--session-id", abandoned["session_id"], "--request-key", "folder-release")
        self.assertEqual(code, 0, released)
        self.assertEqual(released["outcome"], "released", released)
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
        # A successful check-in already closes the session, so a later release is refused as not open.
        code, again = self.run_open("release", "--project-ref", ref, "--actor", "owner",
                                    "--session-id", opened["session_id"], "--request-key", "folder-release-done")
        self.assertEqual(code, 4, again)
        self.assertEqual(again["error"]["code"], "InvalidSessionError", again)


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

    def test_parked_session_is_freed_by_release_parked(self):
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
        released = self.editor.dispatch({"command": "document-authoring", "operation": "release-parked",
            "request_key": "release-park", "session_id": handle["session_id"]}, actor=self.editor.actor)
        self.assertEqual(released["outcome"], "released", released)
        self.assertFalse(self.recovery(handle["session_id"])["recovery_pending"])
        reopened = self.call("open", "open-after-release")
        self.assertEqual(reopened["outcome"], "opened", reopened)


if __name__ == "__main__":
    unittest.main()

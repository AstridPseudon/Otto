"""``show``, ``open`` and ``status`` on the one manager entry.

``show`` reads one project or task identically for the Claude and Codex lanes.
``open`` drives Herzchen's authoring session (open, autosave, finish, release)
on a real DocumentEditorHost over real DAT and EDT. A stale check-in is refused
and changes nothing. ``status`` adds the lab count and the responsibility slot
kinds to the portfolio status. Real owner Stores, real lanes.
"""

from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.content.model import ContentDocument, ContentRevision
from herzchen.content.packets import domain_contribution as packets
from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.domains.assessment.module import contribution as assessment
from herzchen.domains.work import contributions
from herzchen.fleet.labs import LabFleet
from herzchen.kernel import Store
from otto.agents.host_profiles import SLOTS, resolve_profile_name
from otto.hostctl.owner import host_domains
from otto.portfolio import cli
from otto.portfolio.document_editor_host import DocumentEditorHost
from otto.portfolio.fixtures import project_authoring
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


def _task(local_id, **extra):
    return {"id": local_id, "title": "Plan " + local_id, "instructions": "Do " + local_id,
            "acceptance": "Done " + local_id, **extra}


def _file(*tasks, title="Show plan", **extra):
    return {"project": {"title": title, "outcome": "One read per project"}, "tasks": list(tasks), **extra}


class ShowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="a3-show-test-")
        self.addCleanup(self.temporary.cleanup)
        domains = tuple((*contributions(include_assignment_resources=True),
                         authoring_contribution(), content_contribution()))
        self.store = Store.create(Path(self.temporary.name) / "fixture.sqlite", authority="a3-show-test")
        self.store.register_domain_handler(domains)
        self.addCleanup(self.store.close)
        binding = HerzchenBindingConfig("a3-show-test", "fixture-credential")
        seed = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner")
        saved = OttoPortfolio(seed.consumer_operations()).save_project(
            _file(_task("A"), _task("B", dependencies=["A"])), actor="owner", request_id="show-seed")
        self.assertEqual(saved["outcome"], "saved", saved)
        self.project_ref = saved["project_ref"]
        self.task_ref = saved["task_refs"]["B"]
        # The read is scoped: the owner reads this one project through a grant for it.
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner",
            project_read_grant=ProjectReadGrant(binding.authenticated_actor("owner"),
                (self.project_ref["id"],), "fixture-owner", "1"))
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    def _show(self, *argv, kind):
        out = StringIO()
        with patch.dict(os.environ, {"OTTO_HOST_KIND": kind}), redirect_stdout(out):
            code = cli.main(list(argv), portfolio=self.portfolio)
        return code, out.getvalue()

    def test_show_project_and_task_are_identical_for_claude_and_codex_lanes(self):
        # The two lanes really select different model profiles; their show output must not differ.
        self.assertEqual(resolve_profile_name(environ={"OTTO_HOST_KIND": "claude-code"}), "claude")
        self.assertEqual(resolve_profile_name(environ={"OTTO_HOST_KIND": "codex"}), "codex")
        for argv in (("show", "project", "--project-ref", json.dumps(self.project_ref), "--actor", "owner"),
                     ("show", "task", "--project-ref", json.dumps(self.project_ref),
                      "--task-ref", json.dumps(self.task_ref), "--actor", "owner")):
            with self.subTest(argv=argv[1]):
                claude_code, claude_out = self._show(*argv, kind="claude-code")
                codex_code, codex_out = self._show(*argv, kind="codex")
                self.assertEqual(claude_code, 0, claude_out)
                self.assertEqual(codex_code, 0, codex_out)
                self.assertEqual(claude_out, codex_out)
                self.assertEqual(json.loads(claude_out)["outcome"], "read")

    def test_show_project_reads_its_title_and_both_tasks(self):
        code, out = self._show("show", "project", "--project-ref", json.dumps(self.project_ref),
                               "--actor", "owner", kind="codex")
        self.assertEqual(code, 0, out)
        shown = json.loads(out)
        self.assertEqual(shown["schema"], "otto.show.project.v1")
        self.assertEqual(shown["project"]["title"], "Show plan")
        self.assertEqual(shown["project"]["task_count"], 2)
        self.assertTrue(shown["read_only"])
        self.assertFalse(shown["dispatch"])


class OpenTests(unittest.TestCase):
    """``open`` drives the authoring session through the injected owner editor host."""

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
            content={"text": "Opening"}, access_mode="write", document_id="editor-doc")
        self.doc = {k: v for k, v in created["document_ref"].items() if k != "revision"}
        self.f.portfolio.link_document(self.project, self.doc, actor="owner", request_id="link",
                                       access_mode="read")
        self.project = {k: v for k, v in self.project.items() if k != "revision"}
        self.editor = DocumentEditorHost(owner=self.owner, directory=self.f.root / "editor",
                                         secret=b"s" * 32, clock=lambda: 1000.0)

    def run_open(self, step, *argv):
        refs = () if step == "release" else ("--project-ref", json.dumps(self.project),
                                             "--document-ref", json.dumps(self.doc))
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["open", step, *refs, *argv], editor_host=self.editor)
        return code, json.loads(out.getvalue())

    def head(self):
        return self.owner.content.read(ResourceRef.from_dict(self.doc))["current_revision"]["revision"]

    def start(self, key="open"):
        code, opened = self.run_open("start", "--request-key", key)
        self.assertEqual(code, 0, opened)
        self.assertEqual(opened["outcome"], "opened", opened)
        return json.dumps(opened["handle"])

    def test_open_autosave_then_finish_publishes_one_revision(self):
        handle = self.start()
        head = self.head()
        code, saved = self.run_open("autosave", "--request-key", "save", "--handle-json", handle,
                                    "--buffer-json", json.dumps({"content": {"text": "Edited"}}))
        self.assertEqual(code, 0, saved)
        self.assertTrue(saved["buffer_captured"])
        self.assertEqual(self.head(), head)
        code, finished = self.run_open("finish", "--request-key", "finish", "--handle-json", handle)
        self.assertEqual(code, 0, finished)
        self.assertTrue(finished["dat_revision_advanced"], finished)
        self.assertNotEqual(self.head(), head)

    def test_stale_check_in_is_refused_and_release_changes_nothing(self):
        handle = self.start()
        # A second writer publishes a newer revision after this session opened.
        ref = ResourceRef.from_dict(self.doc)
        document = ContentDocument.from_dict(self.f.store.get_identity(ref).payload["document"])
        other = ContentRevision(ref, "rev-other", {"text": "Other writer"}, self.owner.owner_actor,
                                parent_revision=self.head())
        context = TransactionContext(self.owner.owner_actor, "other-writer",
                                     sha256(b"other-writer").hexdigest(), expected_revision=self.head())
        self.owner.content.execute(self.owner.content.build_append_revision(context, document, other))
        other_head = self.head()
        self.run_open("autosave", "--request-key", "save", "--handle-json", handle,
                      "--buffer-json", json.dumps({"content": {"text": "Stale draft"}}))
        code, refused = self.run_open("finish", "--request-key", "stale-finish", "--handle-json", handle)
        self.assertEqual(code, 4, refused)
        self.assertEqual(refused["outcome"], "conflict", refused)
        self.assertEqual(refused["error"]["code"], "stale_base", refused)
        self.assertEqual(refused["current_revision"], other_head)
        self.assertFalse(refused["dat_revision_advanced"], refused)
        self.assertEqual(self.head(), other_head)
        code, released = self.run_open("release", "--request-key", "release", "--handle-json", handle)
        self.assertEqual(code, 0, released)
        self.assertTrue(released["nonpublishing"], released)
        self.assertEqual(self.head(), other_head)
        # The correction path: reopen on the new head, then check in.
        corrected = self.start("reopen")
        self.run_open("autosave", "--request-key", "correct", "--handle-json", corrected,
                      "--buffer-json", json.dumps({"content": {"text": "Corrected"}}))
        code, finished = self.run_open("finish", "--request-key", "correct-finish", "--handle-json", corrected)
        self.assertEqual(code, 0, finished)
        self.assertTrue(finished["dat_revision_advanced"], finished)
        self.assertNotEqual(self.head(), other_head)


class StatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="a3-status-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store.create(self.root / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(host_domains())
        binding = HerzchenBindingConfig("owner", "credential")
        owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner")
        self.portfolio = ResourceRef("owner", "wrk.portfolio", "portfolio")
        root = owner.assignments.assign(self.portfolio, role="orchestrator", principal="orchestrator",
                                        logical_request_key="root")
        self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner",
                                             portfolio_ref=self.portfolio, main_assignment_ref=root.ref)
        self.session = SimpleNamespace(store=self.store, owner=self.owner, binding=binding,
            config={"home": temporary.name},
            host={"portfolio_ref": self.portfolio.to_dict(), "principal": "orchestrator"})
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    def run_status(self, *extra):
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["status", *extra], status_session=self.session, labs=self.labs)
        return code, json.loads(out.getvalue())

    def test_status_lists_the_lab_count_and_the_slot_kinds(self):
        self.labs = LabFleet(repo=self.root / "line", labs_root=self.root / "labs",
                             checkpoint=lambda *args, **kwargs: None)
        for name in ("A2", "A3"):
            (self.root / "labs" / name).mkdir(parents=True)
        code, status = self.run_status("--format", "json")
        self.assertEqual(code, 0, status)
        self.assertEqual(status["labs"], {"count": 2})
        self.assertEqual(status["slot_kinds"], list(SLOTS))
        self.assertEqual(status["outcome"], "read")

    def test_status_without_a_lab_root_reports_no_count(self):
        self.labs = None
        code, status = self.run_status()
        self.assertEqual(code, 0, status)
        self.assertEqual(status["labs"], {"count": None})
        self.assertEqual(status["slot_kinds"], list(SLOTS))


if __name__ == "__main__":
    unittest.main()

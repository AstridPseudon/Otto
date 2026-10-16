"""Focused D01 proof for the maintained title-plus-brief onboarding route."""

from pathlib import Path
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution as content_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.kernel.store import Store
from otto.portfolio.cli import build_parser, main as cli_main
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from otto.portfolio.intake import OttoPortfolio
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap


class ProjectOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="d01-onboarding-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "fixture.sqlite"
        self.domains = tuple((*contributions(include_assignment_resources=True),
                              authoring_contribution(), content_contribution()))
        self.store = Store.create(self.path, authority="d01-onboarding-test")
        self.store.register_domain_handler(self.domains)
        self.addCleanup(self.store.close)
        self.owner = self._owner()
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    def _materialize(self, checkout, initial_bytes, **values):
        path = self.root / checkout.session_id
        path.mkdir()
        (path / "project.json").write_bytes(initial_bytes)
        return {"path": str(path), "registered_files": ["project.json"]}

    def _owner(self, project_ids=()):
        binding = HerzchenBindingConfig("d01-onboarding-test", "fixture-credential")
        grant = None
        if project_ids:
            grant = ProjectReadGrant(binding.authenticated_actor("owner"), tuple(project_ids), "d01-test", "v1")
        return PortfolioOwnerBootstrap(
            self.store,
            binding=binding,
            owner_actor="owner",
            materializer=self._materialize,
            project_read_grant=grant,
        )

    def test_create_release_find_reopen_preserves_identity_and_inert_state(self):
        created = self.portfolio.create_draft(
            actor="owner", request_id="draft-create", title="A title", brief="A short brief",
            supporting_files={"notes.md": "Notes"},
        )
        self.assertEqual(created["outcome"], "created", created)
        self.assertEqual(created["schema"], "otto.portfolio.onboarding.v1")
        self.assertEqual([item["path"] for item in created["documents"]], ["brief.md", "notes.md"])
        self.assertFalse(created["document_errors"])

        project_ref = created["project_ref"]
        self.assertEqual(created["workspace"]["locator"],
                         "otto://d01-onboarding-test/work.project/" + project_ref["id"])
        self.assertEqual(self.portfolio.release_project(
            project_ref, session_id=created["workspace"]["session_id"], actor="owner", request_id="draft-release"
        )["outcome"], "released")

        # The normal read route is the existing finite project-read grant; no
        # second reader or local manifest is introduced for onboarding.
        granted_owner = self._owner((project_ref["id"],))
        granted_portfolio = OttoPortfolio(granted_owner.consumer_operations())
        found = granted_portfolio.find_draft(actor="owner", project_ref=project_ref)
        self.assertEqual(found["outcome"], "read", found)
        reopened = granted_portfolio.reopen_draft(actor="owner", request_id="draft-reopen", project_ref=project_ref)
        self.assertEqual(reopened["outcome"], "opened", reopened)
        self.assertEqual(reopened["project_ref"]["id"], project_ref["id"])
        self.assertEqual(reopened["workspace"]["locator"], created["workspace"]["locator"])

        record = granted_owner.graph.current(ResourceRef.from_dict(project_ref))
        self.assertEqual(record.lifecycle.value, "pending")
        self.assertEqual(record.payload["tasks"], [])
        for field in ("manager", "worker", "budget", "execution"):
            self.assertIsNone(record.payload[field])

    def test_missing_owner_binding_is_actionable_and_inert(self):
        result = OttoPortfolio().create_draft(
            actor="owner", request_id="unbound-create", title="A title", brief="A short brief"
        )
        self.assertEqual(result["outcome"], "unavailable")
        self.assertEqual(result["binding"]["state"], "missing")
        self.assertIn("authenticated owner", result["binding"]["required"])
        self.assertIn("do not create a filesystem project", result["next_action"])
        self.assertEqual(result["effects"]["tasks"], [])
        self.assertEqual(result["effects"]["provider_calls"], 0)

    def test_create_reply_and_exact_replay_never_inventory_unrelated_events(self):
        operations = self.portfolio.operations
        reader = operations._owner_reader
        calls = []

        class ScopedReader:
            def __getattr__(self, name):
                return getattr(reader, name)

            def list_events(self, **query):
                # An unrelated native result may be arbitrarily large. The
                # create reply must never ask to decode the global inventory.
                self_subjects = query.get("subjects")
                if not self_subjects:
                    raise AssertionError("global event hydration in authoring reply")
                calls.append(self_subjects)
                return reader.list_events(**query)

        operations._owner_reader = ScopedReader()
        request = dict(actor="owner", request_id="bounded-create", title="Title", brief="Brief")
        created = self.portfolio.create_draft(**request)
        self.assertEqual(created["outcome"], "created", created)
        replayed = self.portfolio.create_draft(**request)
        self.assertEqual(replayed["project_ref"]["id"], created["project_ref"]["id"])
        self.assertEqual(replayed["receipt"]["event_ids"], created["receipt"]["event_ids"])
        self.assertTrue(calls)
        self.assertTrue(all(len(subjects) == 1 for subjects in calls))

    def test_receipt_scope_rejects_foreign_authority_before_reading_events(self):
        operations = self.portfolio.operations
        receipt = {"event_ids": ["foreign-event"], "operation": "work.create",
                   "target": {"authority": "foreign", "kind": "work.project", "id": "foreign"}}
        with self.assertRaisesRegex(ValueError, "owner authority"):
            operations._events_for(receipt)

    def test_empty_receipt_lineage_needs_no_event_inventory(self):
        self.assertEqual(self.portfolio.operations._events_for({"event_ids": []}), [])

    def test_help_and_cli_parser_expose_cold_onboarding_route(self):
        parser = build_parser()
        args = parser.parse_args(["onboarding", "create", "--actor", "owner", "--request-id", "r",
                                  "--title", "Title", "--brief", "Brief"])
        self.assertEqual(args.command, "onboarding")
        self.assertEqual(args.onboarding_command, "create")
        help_surface = OttoPortfolio.help()
        self.assertIn("onboarding", help_surface["operations"])
        self.assertIn("title plus brief", help_surface["operations"]["onboarding"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["help", "--format", "json"]), 0)
        cli_help = json.loads(output.getvalue())
        self.assertIn("project_onboarding", cli_help["canonical_public_paths"])


if __name__ == "__main__":
    unittest.main()

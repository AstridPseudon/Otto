"""Focused guard that maintained command guides follow the current parsers."""
import unittest
from pathlib import Path

from otto.hostctl.cli import build_parser as host_parser
from otto.hostctl.manager_client import build_parser as manager_parser
from otto.hostctl.portfolio import parser as portfolio_parser


ROOT = Path(__file__).resolve().parents[1]
MAINTAINED_GUIDES = (
    "docs/megado-from-any-host.md",
    "docs/portfolio.md",
    "docs/host-onboarding.md",
    "docs/portfolio-spec.md",
    "policy-staging/megado/skill/SKILL.md",
    "policy-staging/megado/skill/references/project-lifecycle.md",
)


class SupportedDocumentationRoutes(unittest.TestCase):
    def test_retired_project_sync_and_root_read_routes_are_rejected(self):
        parser = host_parser()
        for argv in (
            ["project", "sync-docs", "--project", "demo-run"],
            ["overview"],
            ["task"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                parser.parse_args(argv)

        with self.assertRaises(SystemExit):
            portfolio_parser().parse_args(["sync-docs", "--dir", "./portfolio-docs"])

    def test_documented_replacement_routes_exist_in_current_parsers(self):
        parser = host_parser()
        parser.parse_args(["project", "register", "--bundle", "./run"])
        parser.parse_args(["project", "activate", "--project", "demo-run"])

        portfolio = portfolio_parser()
        portfolio.parse_args(["apply", "--root", "./portfolio"])
        portfolio.parse_args(["documents", "--operation", "list"])
        portfolio.parse_args(["documents", "--operation", "read", "--path", "portfolio.md"])

        manager = manager_parser()
        manager.parse_args(["--project", "demo-run", "project-documents", "--operation", "read", "--path", "brief.md"])
        manager.parse_args(["--project", "demo-run", "project-authoring", "--operation", "read"])

    def test_maintained_guides_do_not_recommend_retired_routes(self):
        for relative in MAINTAINED_GUIDES:
            contents = (ROOT / relative).read_text()
            with self.subTest(path=relative):
                self.assertNotIn("ottoctl project sync-docs", contents)
                self.assertNotIn("ottoctl portfolio sync-docs", contents)
                self.assertNotIn("ottoctl overview", contents)
                self.assertNotIn("ottoctl task ", contents)

    def test_portfolio_apply_docs_do_not_promise_document_sync(self):
        for relative in MAINTAINED_GUIDES:
            contents = (ROOT / relative).read_text()
            with self.subTest(path=relative):
                self.assertNotIn("apply --root DIR` reconciles a file-mode portfolio and its shared root documents", contents)
                self.assertNotIn("Apply reconciles all root files outside `projects/` as shared documents", contents)
                self.assertNotIn("shared-document associations through portfolio apply", contents)
                self.assertNotIn("accepts the root's shared documents", contents)

        portfolio_docs = (ROOT / "docs/portfolio.md").read_text()
        self.assertIn("portfolio-setup.json", portfolio_docs)
        self.assertIn("It does not import changed", portfolio_docs)
        self.assertIn("The `portfolio documents` and manager `project-documents` routes are read-only", portfolio_docs)
        self.assertIn("timeline-platform-r4-portfolio", portfolio_docs)


if __name__ == "__main__":
    unittest.main()

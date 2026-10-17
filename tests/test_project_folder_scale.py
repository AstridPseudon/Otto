"""A project folder has no product size limit; one operation is bounded.

200 documents of ~25 KiB each (about 5 MiB) import, check out, check in a
change to three of them, export and read back. Before, the whole folder was
capped at 50 files and 1 MiB in total at checkout, check-in, import and
transfer, so this project could not even be checked out.
"""
import unittest

from otto.portfolio.document_navigation import (MAX_BUNDLE_DOCUMENTS, MAX_SEARCH_DOCUMENTS,
                                                ProjectDocumentOperations, export_bundle_pages)
from otto.portfolio.fixtures.project_folder import ProjectFolderProof
from otto.portfolio.project_folder import MAX_OPERATION_FILES, validate_files


def _files(count=200, size=25 * 1024):
    files = {}
    for index in range(count):
        head = "# Document %03d\n\n" % index
        files["docs/%02d/doc-%03d.md" % (index % 10, index)] = head + ("x" * (size - len(head) - 1)) + "\n"
    return files


class ProjectFolderScaleTests(ProjectFolderProof):
    # This subclass raises the request bound on purpose; these live-bound proofs still run through ProjectFolderProof itself.
    test_large_folder_uses_bounded_child_requests_and_preserves_exact_bytes = None
    test_single_document_over_live_request_bound_is_rejected_before_creation = None

    def bind(self):
        # The installed host lane is an atomic private file transport. Its
        # trusted composition qualifies operation-sized requests; old bounded
        # stdin consumers retain the default 16KiB guard. No JSON caller flag
        # can raise this bound.
        from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
        from otto.portfolio.herzchen_binding import HerzchenBindingConfig
        from otto.portfolio.intake import OttoPortfolio
        self.owner = PortfolioOwnerBootstrap(self.store,
            binding=HerzchenBindingConfig("d01-fixture", "fixture-credential"),
            owner_actor="owner", materializer=self.materialize,
            folder_transport_request_bytes=256 * 1024 * 1024)
        self.portfolio = OttoPortfolio(self.owner.consumer_operations())

    def test_two_hundred_documents_roundtrip_through_checkout_check_in_and_export(self):
        files = _files()
        self.assertGreater(sum(len(text) for text in files.values()), 5 * 1000 * 1000)
        imported = self.import_files(key="large", files=files)
        ref = imported["project_ref"]
        opened = self.open(ref)
        self.assertEqual(len(opened["document_files"]), 200)
        changes = [{"operation": "edit", "path": path, "content": "# Changed " + path + "\n"}
                   for path in sorted(files)[:3]]
        finished = self.checkin(opened, changes, key="large-check-in")
        self.assertEqual(finished["outcome"], "finished", finished)
        exported = self.portfolio.export_folder(ref, actor="owner", request_id="large-export")
        expected = dict(files, **{change["path"]: change["content"] for change in changes})
        self.assertEqual(exported["files"], expected)
        rows = self.reader().list_documents(ref, actor=self.owner.owner_actor)["documents"]
        self.assertEqual(len(rows), 200)
        changed = self.doc(ref, changes[0]["path"])
        read = self.reader().read_document(ref, changed["document_ref"], actor=self.owner.owner_actor)
        self.assertEqual(read["content"], changes[0]["content"])

    def test_search_and_bundle_page_instead_of_failing_on_large_projects(self):
        from herzchen.content import domain_contribution as content_contribution
        from herzchen.content.packets import ContextPacketService
        files = _files(count=MAX_BUNDLE_DOCUMENTS + 30, size=512)
        ref = self.import_files(key="paged", files=files)["project_ref"]
        nav = ProjectDocumentOperations(document_reader=self.reader(), authoring=object(),
            context_reader=ContextPacketService(self.store.domain_handler((content_contribution(),))))
        rows = self.reader().list_documents(ref, actor=self.owner.owner_actor)["documents"]
        bundle = export_bundle_pages(nav, ref, [row["document_ref"] for row in rows], actor=self.owner.owner_actor)
        self.assertEqual((bundle["outcome"], bundle["pages"], len(bundle["files"])), ("exported", 2, len(files)))
        search = nav.search_documents(ref, "document 07", actor=self.owner.owner_actor, cursor=0)
        self.assertEqual(search["outcome"], "listed")
        self.assertIsNone(search["next_cursor"])  # 80 documents fit one window of MAX_SEARCH_DOCUMENTS
        self.assertLess(len(files), MAX_SEARCH_DOCUMENTS)

    def test_one_operation_is_bounded_not_the_project(self):
        validate_files(_files(count=MAX_OPERATION_FILES + 1, size=64))  # a whole tree: fine
        result = self.portfolio.import_folder(actor="owner", request_id="too-much-at-once",
            project_json={"title": "Files"}, files=_files(count=MAX_OPERATION_FILES + 1, size=64))
        self.assertEqual(result["outcome"], "rejected", result)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ProjectFolderScaleTests(name) for name in ProjectFolderScaleTests.__dict__
                              if name.startswith("test_") and callable(getattr(ProjectFolderScaleTests, name)))


if __name__ == "__main__":
    unittest.main()

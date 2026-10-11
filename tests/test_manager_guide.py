"""Focused tests for trusted current-manager guide resolution."""
import hashlib
import unittest
from types import SimpleNamespace

from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from otto.portfolio.manager_guide import resolve_required_instruction_adoption


class ManagerGuideTests(unittest.TestCase):
    def test_exact_manager_guide_ignores_labels_and_rejects_ambiguous_or_stale_rows(self):
        ref = ResourceRef('owner', 'document', 'guide', 'rev-1').to_dict()
        name = 'shared-database-read-index-adoption-20261011-v1-onboarding-BASE@rev-1'
        content = {'schema': 'herzchen.instructions.v1', 'name': name,
                   'entrypoint': 'MANAGER.md', 'instructions': 'guide',
                   'bundle_digest': hashlib.sha256(b'guide').hexdigest(),
                   'export_manifest_digest': 'fixture', 'required': True,
                   'supporting_refs': []}
        digest = validate_instruction_content(content)
        row = {'resource_ref': ref, 'resource_name': name,
               'content_digest': digest, 'required': True}
        decoy = {'resource_ref': ResourceRef('owner', 'document', 'decoy', 'rev-1').to_dict(),
                 'resource_name': 'BASE', 'content_digest': 'decoy', 'required': True}
        reader = SimpleNamespace(read=lambda pin: {'current_revision': ref, 'content': content})
        selected, _, _ = resolve_required_instruction_adoption([decoy, row], ref, reader)
        self.assertEqual(selected, row)

        invalid = ([], [{**row, 'required': False}], [row, dict(row)],
                   [{**row, 'resource_name': 'BASE'}],
                   [{**row, 'content_digest': 'wrong'}])
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises((KeyError, TypeError, ValueError)):
                resolve_required_instruction_adoption(rows, ref, reader)
        with self.assertRaises(ValueError):
            resolve_required_instruction_adoption([row], {**ref, 'revision': None}, reader)
        stale = SimpleNamespace(read=lambda pin: {
            'current_revision': {**ref, 'revision': 'rev-2'}, 'content': content})
        with self.assertRaises(ValueError):
            resolve_required_instruction_adoption([row], ref, stale)


if __name__ == '__main__':
    unittest.main()

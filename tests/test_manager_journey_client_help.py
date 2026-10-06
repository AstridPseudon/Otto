"""Ordinary close instructions expose a usable command without opening a Store."""
import argparse
import contextlib
import io
import shlex
import unittest
from otto.portfolio.manager_journey_client import add_manager_journey_parsers


class ProjectCloseHelpTests(unittest.TestCase):
    def test_help_example_parses_and_explains_retained_terminal_semantics(self):
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest='command', required=True))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            parser.parse_args(['finish-project', '--help'])
        self.assertEqual(result.exception.code, 0)
        text = output.getvalue()
        example = next(line for line in text.splitlines() if line.startswith('ottoctl finish-project '))
        args = parser.parse_args(shlex.split(example)[1:])
        self.assertEqual(args.command, 'finish-project')
        self.assertEqual(set(args.dispositions), {'acceptance', 'publication', 'remote', 'runtime'})
        for value in args.dispositions.values():
            self.assertIn(value['status'], {'passed', 'verified', 'qualified'})
            self.assertTrue(value['rationale'].strip())
        for meaning in ['command-status --request-id HANDLE', 'project_completion_recorded=true',
                        'settlement_pending=false', 'reconciliation.status=reconciled',
                        'return so the owner can settle', 'do not repeat the finish effect']:
            self.assertIn(meaning, text)


if __name__ == '__main__':
    unittest.main()

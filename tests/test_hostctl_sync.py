"""The project document sync command has been removed."""
import unittest
from test_hostctl_cli import HostctlFixture as _Fixture


class SyncDocsRemovalTests(_Fixture):
    def test_project_sync_docs_is_not_a_command(self):
        from otto.hostctl.cli import build_parser
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["project", "sync-docs", "--project", "demo-run"])


del _Fixture

if __name__ == "__main__":
    unittest.main()

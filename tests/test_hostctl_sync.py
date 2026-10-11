"""ottoctl project sync-docs: the run directory stays authoritative until activation."""
import os
import unittest

from test_hostctl_cli import HostctlFixture as _Fixture


class SyncDocsTests(_Fixture):
    def test_changed_and_added_files_are_recorded_as_revisions_by_digest(self):
        self._ready()
        code, clean = self._ottoctl("project", "sync-docs", "--project", "demo-run", "--check")
        self.assertEqual((code, clean["outcome"]), (0, "in_sync"))
        with open(os.path.join(self.bundle, "agent_goal.md"), "a") as stream:
            stream.write("\n## Authority\nThe run directory is authoritative until activation.\n")
        with open(os.path.join(self.bundle, "notes.md"), "w") as stream:
            stream.write("# Notes\n")
        code, drift = self._ottoctl("project", "sync-docs", "--project", "demo-run", "--check")
        states = {row["path"]: row["state"] for row in drift["documents"]}
        self.assertEqual((drift["outcome"], states["agent_goal.md"], states["notes.md"]), ("drift", "changed", "added"))
        self.assertEqual(drift["tasks"]["added"], [])
        _, before = self._ottoctl("project", "status", "--project", "demo-run")
        code, synced = self._ottoctl("project", "sync-docs", "--project", "demo-run")
        self.assertEqual((code, synced["outcome"]), (0, "synced"), synced)
        self.assertEqual(sorted(synced["recorded"]), ["agent_goal.md", "notes.md"])
        code, again = self._ottoctl("project", "sync-docs", "--project", "demo-run")
        self.assertEqual(again["outcome"], "in_sync")
        _, after = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(after["lifecycle"], "pending")
        self.assertTrue(all(row["matches_registered_bytes"] for row in after["documents"]
                            if row["registered_raw_sha256"] is not None), after["documents"])
        revisions = {row["path"]: row["revision_ref"]["revision"] for row in after["documents"]}
        self.assertEqual(revisions["agent_goal.md"], "rev-2")
        self.assertEqual(len(after["documents"]), len(before["documents"]) + 1)
        self.assertEqual(after["tasks"], before["tasks"])

    def test_task_drift_is_reported_not_applied(self):
        self._ready()
        path = os.path.join(self.bundle, "tasklist.md")
        with open(path) as stream:
            text = stream.read()
        with open(path, "w") as stream:
            stream.write(text.replace("| T2 |", "| T3 |"))
        code, drift = self._ottoctl("project", "sync-docs", "--project", "demo-run")
        self.assertEqual(drift["tasks"]["added"], ["T3"])
        self.assertEqual(drift["tasks"]["removed"], ["T2"])
        self.assertFalse(drift["tasks"]["applied"])
        _, status = self._ottoctl("project", "status", "--project", "demo-run")
        self.assertEqual(sorted(task["id"] for task in status["tasks"]), ["T1", "T2"])


del _Fixture

if __name__ == "__main__":
    unittest.main()

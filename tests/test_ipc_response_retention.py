"""Answered manager-ipc responses leave the lane; unanswered ones never do."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from otto.portfolio.execution_host import ExecutionHost
from otto.portfolio.ipc_retention import ANSWERED_RESPONSE_GRACE_SECONDS, prune_answered_responses

TOKEN = "a" * 32
OTHER = "b" * 32


class IpcResponseRetentionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lane = Path(self._tmp.name)
        self.old = time.time() - 2 * ANSWERED_RESPONSE_GRACE_SECONDS

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, value=None, *, age=None, raw=None):
        path = self.lane / name
        path.write_text(raw if raw is not None else json.dumps(value or {"outcome": "ok", "terminal": True}))
        if age is not None:
            os.utime(path, (age, age))
        return path

    def _answered(self, token=TOKEN, age=None):
        return self._write("response-" + token + ".json", age=self.old if age is None else age)

    def test_answered_ipc_response_removed(self):
        response = self._answered()
        status = self._write("status-response-" + TOKEN + ".json", age=self.old)
        removed = prune_answered_responses(self.lane)
        self.assertEqual(removed, 1)
        self.assertFalse(response.exists())
        self.assertFalse(status.exists())

    def test_request_is_consumed_before_response_is_pruned(self):
        # A request still beside its response means the owner has not finished it.
        response = self._answered()
        request = self._write("request-" + TOKEN + ".json", {"command": "status"}, age=self.old)
        self.assertEqual(prune_answered_responses(self.lane), 0)
        self.assertTrue(response.exists())
        self.assertTrue(request.exists())

    def test_unanswered_ipc_response_kept(self):
        kept = {}
        kept["pending_receipt"] = (self._answered(TOKEN), self._write("pending-" + TOKEN + ".json", age=self.old))
        kept["socket_custody"] = (self._answered(OTHER), self._write("socket-intent-" + OTHER + ".json", age=self.old))
        kept["non_terminal"] = (self._write("response-" + "c" * 32 + ".json",
                                            {"outcome": "pending"}, age=self.old),)
        kept["unknown_effects"] = (self._write("response-" + "d" * 32 + ".json",
                                               {"outcome": "unknown", "terminal": False}, age=self.old),)
        kept["within_grace"] = (self._write("response-" + "e" * 32 + ".json",
                                            {"outcome": "ok"}, age=time.time()),)
        kept["unparseable"] = (self._write("response-" + "f" * 32 + ".json", raw="{not json", age=self.old),)
        self.assertEqual(prune_answered_responses(self.lane), 0)
        for label, paths in kept.items():
            for path in paths:
                self.assertTrue(path.exists(), label)

    def test_limit_bounds_one_pass(self):
        for index in range(5):
            self._write("response-" + format(index, "032x") + ".json", age=self.old)
        self.assertEqual(prune_answered_responses(self.lane, limit=2), 2)
        self.assertEqual(len(list(self.lane.glob("response-*.json"))), 3)

    def test_request_scan_ignores_responses(self):
        self._answered()
        self._write("request-" + TOKEN + ".json", {"command": "status"})
        self._write("status-response-" + TOKEN + ".json")
        host = SimpleNamespace(directory=self.lane)
        paths = ExecutionHost._request_paths(host)
        self.assertEqual([path.name for path in paths], ["request-" + TOKEN + ".json"])


if __name__ == "__main__":
    unittest.main()

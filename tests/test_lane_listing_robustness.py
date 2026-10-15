"""Owner listings survive a file vanishing mid-poll, and retire answered pairs after the window."""
import contextlib
import json
import os
import pathlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from otto.hostctl import lanes
from otto.portfolio import client_lanes
from otto.portfolio import ipc_retention
from otto.portfolio.ipc_retention import ANSWERED_RESPONSE_GRACE_SECONDS, prune_answered_responses

OLD = time.time() - 2 * ANSWERED_RESPONSE_GRACE_SECONDS


def token(index):
    return format(index, "032x")


@contextlib.contextmanager
def vanishing_request(name):
    """Remove ``name`` the moment it is stat'ed, as a request answered mid-poll does."""
    real_stat = pathlib.Path.stat

    def stat(self, *args, **kwargs):
        if self.name == name:
            self.unlink(missing_ok=True)
        return real_stat(self, *args, **kwargs)

    with mock.patch.object(pathlib.Path, "stat", stat):
        yield


class _VanishingEntry:
    def __init__(self, entry, name):
        self._entry = entry
        self._name = name
        self.name = entry.name

    def is_file(self, **kwargs):
        return self._entry.is_file(**kwargs)

    def stat(self, **kwargs):
        if self.name == self._name:
            os.unlink(self._entry.path)
        return self._entry.stat(**kwargs)


@contextlib.contextmanager
def vanishing_entry(name):
    """Remove ``name`` between the directory scan and its stat, as an answered response does."""
    real_scandir = os.scandir

    @contextlib.contextmanager
    def scandir(path):
        with real_scandir(path) as entries:
            yield [_VanishingEntry(entry, name) for entry in entries]

    with mock.patch.object(ipc_retention.os, "scandir", scandir):
        yield


def _age(*paths):
    for path in paths:
        if path.exists():
            os.utime(path, (OLD, OLD))


class LaneListingTests(unittest.TestCase):
    """lanes.requests: the owner's own lane, polled about 20 times a second."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lane = lanes.private_dir(Path(self._tmp.name) / "lane")

    def test_vanished_request_never_stops_owner(self):
        gone, kept = token(1), token(2)
        lanes.submit(self.lane, {"command": "a", "args": {}}, token=gone)
        lanes.submit(self.lane, {"command": "b", "args": {}}, token=kept)
        with vanishing_request("request-" + gone + ".json"):
            listed = list(lanes.requests(self.lane))
        self.assertEqual([listed_token for listed_token, _ in listed], [kept])

    def test_answered_pairs_pruned_after_window(self):
        stale, fresh, open_ = token(3), token(4), token(5)
        for request_token in (stale, fresh):
            lanes.submit(self.lane, {"command": "a", "args": {}}, token=request_token)
            lanes.respond(self.lane, request_token, {"outcome": "ok", "terminal": True})
        lanes.submit(self.lane, {"command": "c", "args": {}}, token=open_)
        _age(self.lane / ("request-" + stale + ".json"), self.lane / ("response-" + stale + ".json"),
             self.lane / ("request-" + open_ + ".json"))
        listed = [listed_token for listed_token, _ in lanes.requests(self.lane)]
        self.assertEqual(listed, [open_])
        self.assertFalse((self.lane / ("request-" + stale + ".json")).exists())
        self.assertFalse((self.lane / ("response-" + stale + ".json")).exists())
        self.assertTrue((self.lane / ("request-" + fresh + ".json")).exists())
        self.assertTrue((self.lane / ("response-" + fresh + ".json")).exists())

    def test_pending_relays_kept(self):
        relayed, unanswered = token(6), token(7)
        lanes.submit(self.lane, {"command": "a", "args": {}}, token=relayed)
        lanes.respond(self.lane, relayed, {"outcome": "ok", "terminal": True})
        lanes.mark_pending(self.lane, relayed, "relayed")
        lanes.submit(self.lane, {"command": "b", "args": {}}, token=unanswered)
        lanes.mark_pending(self.lane, unanswered, "queued")
        _age(self.lane / ("request-" + relayed + ".json"), self.lane / ("response-" + relayed + ".json"),
             self.lane / ("pending-" + relayed + ".json"), self.lane / ("request-" + unanswered + ".json"),
             self.lane / ("pending-" + unanswered + ".json"))
        listed = [listed_token for listed_token, _ in lanes.requests(self.lane)]
        self.assertEqual(listed, [unanswered])
        for name in ("request-", "response-", "pending-"):
            self.assertTrue((self.lane / (name + relayed + ".json")).exists(), name)
        self.assertTrue((self.lane / ("request-" + unanswered + ".json")).exists())


class ClientLaneListingTests(unittest.TestCase):
    """client_lanes.requests: the lane a client writes and the orchestrator answers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lane = client_lanes.private_dir(Path(self._tmp.name) / "lane")

    def test_vanished_request_never_stops_owner(self):
        gone, kept = token(1), token(2)
        client_lanes.submit(self.lane, {"command": "a", "args": {}}, token=gone)
        client_lanes.submit(self.lane, {"command": "b", "args": {}}, token=kept)
        with vanishing_request("request-" + gone + ".json"):
            listed = list(client_lanes.requests(self.lane))
        self.assertEqual([listed_token for listed_token, _ in listed], [kept])

    def test_answered_pairs_pruned_after_window(self):
        stale, fresh, open_ = token(3), token(4), token(5)
        for request_token in (stale, fresh):
            client_lanes.submit(self.lane, {"command": "a", "args": {}}, token=request_token)
            client_lanes.respond(self.lane, request_token, {"outcome": "ok", "terminal": True})
        client_lanes.submit(self.lane, {"command": "c", "args": {}}, token=open_)
        _age(self.lane / ("request-" + stale + ".json"), self.lane / ("response-" + stale + ".json"),
             self.lane / ("request-" + open_ + ".json"))
        listed = [listed_token for listed_token, _ in client_lanes.requests(self.lane)]
        self.assertEqual(listed, [open_])
        self.assertFalse((self.lane / ("request-" + stale + ".json")).exists())
        self.assertFalse((self.lane / ("response-" + stale + ".json")).exists())
        self.assertTrue((self.lane / ("request-" + fresh + ".json")).exists())
        self.assertTrue((self.lane / ("response-" + fresh + ".json")).exists())

    def test_pending_relays_kept(self):
        relayed, unanswered = token(6), token(7)
        client_lanes.submit(self.lane, {"command": "a", "args": {}}, token=relayed)
        client_lanes.respond(self.lane, relayed, {"outcome": "ok", "terminal": True})
        client_lanes.mark_pending(self.lane, relayed, "relayed")
        client_lanes.submit(self.lane, {"command": "b", "args": {}}, token=unanswered)
        client_lanes.mark_pending(self.lane, unanswered, "queued")
        _age(self.lane / ("request-" + relayed + ".json"), self.lane / ("response-" + relayed + ".json"),
             self.lane / ("pending-" + relayed + ".json"), self.lane / ("request-" + unanswered + ".json"),
             self.lane / ("pending-" + unanswered + ".json"))
        listed = [listed_token for listed_token, _ in client_lanes.requests(self.lane)]
        self.assertEqual(listed, [unanswered])
        for name in ("request-", "response-", "pending-"):
            self.assertTrue((self.lane / (name + relayed + ".json")).exists(), name)
        self.assertTrue((self.lane / ("request-" + unanswered + ".json")).exists())


class ManagerIpcListingTests(unittest.TestCase):
    """ipc_retention: manager-ipc responses, pruned by the owner's timer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lane = Path(self._tmp.name)

    def _write(self, name, value=None, *, age=None):
        path = self.lane / name
        path.write_text(json.dumps(value or {"outcome": "ok", "terminal": True}))
        if age is not None:
            os.utime(path, (age, age))
        return path

    def test_vanished_request_never_stops_owner(self):
        gone, kept = token(1), token(2)
        self._write("response-" + gone + ".json", age=OLD)
        kept_response = self._write("response-" + kept + ".json", age=OLD)
        with vanishing_entry("response-" + gone + ".json"):
            self.assertEqual(prune_answered_responses(self.lane), 1)
        self.assertFalse(kept_response.exists())
        self.assertFalse((self.lane / ("response-" + gone + ".json")).exists())

    def test_answered_pairs_pruned_after_window(self):
        stale, fresh, open_ = token(3), token(4), token(5)
        stale_response = self._write("response-" + stale + ".json", age=OLD)
        stale_status = self._write("status-response-" + stale + ".json", age=OLD)
        fresh_response = self._write("response-" + fresh + ".json", age=time.time())
        open_response = self._write("response-" + open_ + ".json", age=OLD)
        self._write("request-" + open_ + ".json", {"command": "status"})
        self.assertEqual(prune_answered_responses(self.lane), 1)
        self.assertFalse(stale_response.exists())
        self.assertFalse(stale_status.exists())
        self.assertTrue(fresh_response.exists())
        self.assertTrue(open_response.exists())

    def test_pending_relays_kept(self):
        relayed, custody = token(6), token(7)
        relayed_response = self._write("response-" + relayed + ".json", age=OLD)
        relayed_pending = self._write("pending-" + relayed + ".json", age=OLD)
        custody_response = self._write("response-" + custody + ".json", age=OLD)
        custody_intent = self._write("socket-intent-" + custody + ".json", age=OLD)
        self.assertEqual(prune_answered_responses(self.lane), 0)
        for path in (relayed_response, relayed_pending, custody_response, custody_intent):
            self.assertTrue(path.exists(), path.name)


if __name__ == "__main__":
    unittest.main()

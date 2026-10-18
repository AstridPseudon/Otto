import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from otto.agents import codex_host_reader as reader_module
from herzchen.fleet import custody as custody_module


class CodexHostReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.native_path = self.root / "metadata-only.jsonl"
        self.native_path.write_text("trace content must never be read")
        self.requests = self.root / "requests.jsonl"
        self.launcher = self.root / "codex"
        self.custody = self.root / "reader-custody"

    def fixture_reader(self, *, initialize=None, response=None):
        initialize = initialize if initialize is not None else {"id": 1, "result": {"userAgent": "fixture"}}
        response = response if response is not None else {
            "id": 2, "result": {"thread": {"id": "issued-session", "path": str(self.native_path), "turns": []}}}
        self.launcher.write_text(
            "#!" + sys.executable + "\n"
            "import json, sys, time\n"
            "responses = " + repr([initialize, response]) + "\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    with open(" + repr(str(self.requests)) + ", 'a') as capture: capture.write(line)\n"
            "    if 'id' in request:\n"
            "        print(json.dumps(responses.pop(0)), flush=True)\n"
            "time.sleep(30)\n")
        self.launcher.chmod(0o700)
        qualified = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.allowed = patch.object(reader_module, "SUPPORTED_CLI_SHA256", frozenset({qualified}))
        self.allowed.start()
        self.addCleanup(self.allowed.stop)
        real_popen = reader_module.subprocess.Popen
        spawned = []
        self.spawned = spawned
        observed_children = {}
        def capture_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process
        real_kernel_proc = custody_module._kernel_proc
        def fixture_census():
            # The sandbox blocks the production ps enumeration. Preserve exact
            # kernel birth evidence for the owner and launched reader directly.
            parent = real_kernel_proc(os.getpid())
            self.assertIsNotNone(parent)
            snapshot = {parent.pid: parent}
            if spawned:
                child_pid = spawned[-1].pid
                child = real_kernel_proc(child_pid)
                if child is not None:
                    observed_children[child_pid] = child
                    snapshot[child.pid] = child
                elif spawned[-1].poll() is None:
                    child = observed_children.get(child_pid)
                    if child is None:
                        self.fail("live app-server fixture must have a kernel birth identity")
                    snapshot[child.pid] = child
            return snapshot
        census = patch.object(custody_module, "census", fixture_census)
        census.start()
        self.addCleanup(census.stop)
        popen = patch.object(reader_module.subprocess, "Popen", capture_popen)
        popen.start()
        self.addCleanup(popen.stop)
        return reader_module.CodexAppServerThreadReader(
            launcher=str(self.launcher), sessions_root=str(self.root), timeout_seconds=3,
            custody_directory=str(self.custody))

    def test_qualified_binary_reads_only_the_exact_session_metadata(self):
        reader = self.fixture_reader()
        self.assertEqual(reader("issued-session"), {
            "thread": {"id": "issued-session", "path": str(self.native_path)}})
        requests = [json.loads(line) for line in self.requests.read_text().splitlines()]
        self.assertEqual([request["method"] for request in requests], ["initialize", "initialized", "thread/read"])
        self.assertEqual(requests[-1]["params"], {"threadId": "issued-session", "includeTurns": False})
        self.assertEqual(self.native_path.read_text(), "trace content must never be read")

    def test_changed_binary_digest_is_rejected_before_process_creation(self):
        reader = self.fixture_reader()
        self.launcher.write_text(self.launcher.read_text() + "# altered binary\n")
        with patch.object(reader_module.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^unsupported_cli_identity$"):
                reader("issued-session")
            spawn.assert_not_called()
        self.assertFalse(self.requests.exists())

    def test_protocol_and_exact_session_fences_survive_qualified_binary(self):
        cases = [
            ({"jsonrpc": "1.0", "id": 2, "result": {}}, "app_server_malformed_message"),
            ({"id": "2", "result": {}}, "app_server_response_id_mismatch"),
            ({"id": 9, "result": {}}, "app_server_response_id_mismatch"),
            ({"id": 2, "error": {"message": "untrusted detail"}}, "app_server_rpc_error"),
            ({"id": 2, "result": {"thread": {"id": "other-session", "path": str(self.native_path)}}},
             "thread_missing_or_session_mismatch"),
            ({"id": 2, "result": {"thread": {"id": "issued-session", "path": str(self.native_path), "turns": [{}]}}},
             "unexpected_turns_in_metadata_response"),
        ]
        for response, error in cases:
            with self.subTest(error=error, response=response):
                reader = self.fixture_reader(response=response)
                with self.assertRaisesRegex(reader_module.HostThreadReadError, "^" + error + "$"):
                    reader("issued-session")

    def test_initialize_response_identity_is_fenced(self):
        reader = self.fixture_reader(initialize={"id": 2, "result": {}})
        with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_response_id_mismatch$"):
            reader("issued-session")
        requests = [json.loads(line) for line in self.requests.read_text().splitlines()]
        self.assertEqual([request["method"] for request in requests], ["initialize"])


    def test_exhausted_rpc_deadline_still_gets_bounded_term_and_kill_reap(self):
        process = MagicMock(pid=1234)
        process.wait.side_effect = [reader_module.subprocess.TimeoutExpired("reader", 1), 0]
        with patch.object(reader_module.os, "killpg") as kill, patch.object(
                reader_module.time, "monotonic", return_value=100000):
            reader_module._reap_app_server(process)
        self.assertEqual([call.kwargs["timeout"] for call in process.wait.call_args_list], [1.0, 1.0])
        self.assertEqual([call.args[1] for call in kill.call_args_list],
                         [reader_module.signal.SIGTERM, reader_module.signal.SIGKILL])

    def test_term_exit_needs_no_kill(self):
        process = MagicMock(pid=1234)
        with patch.object(reader_module.os, "killpg") as kill:
            reader_module._reap_app_server(process)
        process.wait.assert_called_once_with(timeout=1.0)
        kill.assert_called_once_with(1234, reader_module.signal.SIGTERM)

    def test_cleanup_failure_preserves_original_rpc_timeout(self):
        reader = self.fixture_reader()
        reap = reader_module._reap_app_server
        def failed_reap(process):
            reap(process)
            raise OSError("fixture secondary failure")
        with patch.object(reader_module._StdioRPC, "response", side_effect=
                reader_module.HostThreadReadError("app_server_timeout")), patch.object(
                reader_module, "_reap_app_server", side_effect=failed_reap):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_timeout$"):
                reader("issued-session")

    def test_valid_metadata_does_not_bypass_failed_cleanup(self):
        reader = self.fixture_reader()
        reap = reader_module._reap_app_server
        def failed_reap(process):
            reap(process)
            raise OSError("fixture secondary failure")
        with patch.object(reader_module, "_reap_app_server", side_effect=failed_reap):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_cleanup_failed$"):
                reader("issued-session")

    def test_production_reader_launch_persists_latch_before_rpc_and_retires_it_when_gone(self):
        reader = self.fixture_reader()
        send = reader_module._StdioRPC.send
        observed = []
        def inspect_before_send(rpc, value):
            latches = list(self.custody.glob("app-server-*.latch"))
            self.assertEqual(len(latches), 1)
            observed.append(latches[0])
            return send(rpc, value)
        with patch.object(reader_module._StdioRPC, "send", inspect_before_send):
            self.assertEqual(reader("issued-session")["thread"]["id"], "issued-session")
        self.assertTrue(observed)
        self.assertFalse(observed[0].exists(), "a proven-gone app server retires its durable latch")

    def test_uncertain_cleanup_survives_owner_loss_for_startup_recovery(self):
        reader = self.fixture_reader()
        from herzchen.fleet.custody import Disposition, UNCERTAIN
        with patch.object(reader_module.Custody, "release", return_value=Disposition(UNCERTAIN, "fixture doubt")):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_cleanup_failed$"):
                reader("issued-session")
        latches = list(self.custody.glob("app-server-*.latch"))
        self.assertEqual(len(latches), 1, "uncertain cleanup retains a discoverable latch after the call ends")
        outcomes = reader_module.recover_app_server_custody(str(self.custody))
        self.assertEqual(outcomes[str(latches[0])].state, "gone")
        self.assertFalse(latches[0].exists(), "the new owner resolves the retained latch after the process exited")

    def test_new_owner_terminates_surviving_reader_from_uncertain_latch(self):
        reader = self.fixture_reader()
        from herzchen.fleet.custody import Disposition, UNCERTAIN
        with patch.object(reader_module, "_reap_app_server"), patch.object(
                reader_module.Custody, "release", return_value=Disposition(UNCERTAIN, "fixture doubt")):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_cleanup_failed$"):
                reader("issued-session")
        process = self.spawned[-1]
        self.assertIsNone(process.poll(), "the simulated crashed owner leaves a reader alive")
        latches = list(self.custody.glob("app-server-*.latch"))
        self.assertEqual(len(latches), 1)
        outcomes = reader_module.recover_app_server_custody(str(self.custody))
        self.assertEqual(outcomes[str(latches[0])].state, "gone")
        self.assertLess(process.wait(timeout=2), 0, "startup recovery terminates the exact recorded reader")
        self.assertFalse(latches[0].exists())

    def test_recovery_keeps_latch_when_census_is_uncertain(self):
        reader = self.fixture_reader()
        from herzchen.fleet.custody import Disposition, UNCERTAIN
        with patch.object(reader_module, "_reap_app_server"), patch.object(
                reader_module.Custody, "release", return_value=Disposition(UNCERTAIN, "fixture doubt")):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_cleanup_failed$"):
                reader("issued-session")
        process = self.spawned[-1]
        def cleanup_process():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            reader_module.recover_app_server_custody(str(self.custody))
        self.addCleanup(cleanup_process)
        latches = list(self.custody.glob("app-server-*.latch"))
        with patch.object(custody_module, "census", return_value=None):
            outcomes = reader_module.recover_app_server_custody(str(self.custody))
        self.assertEqual(outcomes[str(latches[0])].state, UNCERTAIN)
        self.assertTrue(latches[0].exists(), "unprovable custody remains available for a later retry")


if __name__ == "__main__":
    unittest.main()

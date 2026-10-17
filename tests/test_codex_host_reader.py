import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from otto.agents import codex_host_reader as reader_module
from otto.agents.orchestrator_route import compose_owner_resource_herzchen_adapter


class CodexHostReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.native_path = self.root / "metadata-only.jsonl"
        self.native_path.write_text("trace content must never be read")
        self.requests = self.root / "requests.jsonl"
        self.launcher = self.root / "codex"

    def fixture_reader(self, *, initialize=None, response=None):
        initialize = initialize if initialize is not None else {"id": 1, "result": {"userAgent": "fixture"}}
        response = response if response is not None else {
            "id": 2, "result": {"thread": {"id": "issued-session", "path": str(self.native_path), "turns": []}}}
        self.launcher.write_text(
            "#!" + sys.executable + "\n"
            "import json, sys\n"
            "responses = " + repr([initialize, response]) + "\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    with open(" + repr(str(self.requests)) + ", 'a') as capture: capture.write(line)\n"
            "    if 'id' in request:\n"
            "        print(json.dumps(responses.pop(0)), flush=True)\n")
        self.launcher.chmod(0o700)
        qualified = hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.allowed = patch.object(reader_module, "SUPPORTED_CLI_SHA256", frozenset({qualified}))
        self.allowed.start()
        self.addCleanup(self.allowed.stop)
        return reader_module.CodexAppServerThreadReader(
            launcher=str(self.launcher), sessions_root=str(self.root), timeout_seconds=3,
            scope_latch_path=str(self.root / 'reader-scope.json'))

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


    def test_rpc_failure_uses_birth_fenced_custody_cleanup(self):
        from herzchen.fleet.custody import Disposition
        reader = self.fixture_reader()
        process = MagicMock(pid=1234)
        custody = MagicMock(process=process)
        custody.release.return_value = Disposition('gone')
        with patch.object(reader_module.Custody, 'launch', return_value=custody), patch.object(
                reader_module, '_StdioRPC', side_effect=reader_module.HostThreadReadError('app_server_timeout')), patch.object(
                reader_module.os, 'killpg') as raw_signal:
            with self.assertRaisesRegex(reader_module.HostThreadReadError, '^app_server_timeout$'):
                reader('issued-session')
        custody.release.assert_called_once_with()
        raw_signal.assert_not_called()

    def test_cleanup_failure_preserves_original_rpc_timeout(self):
        from herzchen.fleet.custody import Custody
        reader = self.fixture_reader()
        release = Custody.release
        def failed_release(custody):
            release(custody)
            raise OSError("fixture secondary failure")
        with patch.object(reader_module._StdioRPC, "response", side_effect=
                reader_module.HostThreadReadError("app_server_timeout")), patch.object(
                Custody, "release", autospec=True, side_effect=failed_release):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_timeout$"):
                reader("issued-session")

    def test_valid_metadata_does_not_bypass_failed_cleanup(self):
        from herzchen.fleet.custody import Custody
        reader = self.fixture_reader()
        release = Custody.release
        def failed_release(custody):
            release(custody)
            raise OSError("fixture secondary failure")
        with patch.object(Custody, "release", autospec=True, side_effect=failed_release):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, "^app_server_cleanup_failed$"):
                reader("issued-session")

    def test_valid_metadata_requires_settled_scope_cleanup(self):
        from herzchen.fleet.custody import Custody, Disposition
        reader = self.fixture_reader()
        with patch.object(Custody, 'release', return_value=Disposition('uncertain', 'census unavailable')):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, '^app_server_cleanup_failed$'):
                reader('issued-session')

    def test_valid_metadata_requires_cleanup_without_exception(self):
        from herzchen.fleet.custody import Custody
        reader = self.fixture_reader()
        with patch.object(Custody, 'release', side_effect=OSError('fixture cleanup failure')):
            with self.assertRaisesRegex(reader_module.HostThreadReadError, '^app_server_cleanup_failed$'):
                reader('issued-session')

    def test_production_reader_recovers_crashed_scope_before_another_spawn(self):
        from herzchen.fleet.custody import Disposition
        self.fixture_reader()  # Qualify the fake CLI digest for the production composition.
        latch = self.root / 'metadata-reader-scope.json'

        def production_reader(evidence_id):
            adapter = compose_owner_resource_herzchen_adapter(
                owner='test-owner', source='test-source', worktree=str(self.root),
                launcher=str(self.launcher),
                host_context_path=str(self.root / (evidence_id + '-owner-context.json')),
                reader_scope_latch_path=str(latch), trusted_sessions_root=str(self.root))
            return adapter.trusted_thread_reader

        first = production_reader('startup')
        def died_after_intent(_argv, **kwargs):
            self.assertEqual(kwargs['latch_path'], str(latch))
            latch.write_text(json.dumps({'pgid': None, 'leader_birth': None,
                                         'state': 'launching', 'members': {}}))
            raise SystemExit('owner died after durable launch intent')
        with patch.object(reader_module.Custody, 'launch', side_effect=died_after_intent):
            with self.assertRaises(SystemExit):
                first('issued-session')
        self.assertTrue(latch.exists())

        restarted = production_reader('delivery')
        with patch.object(reader_module.Custody, 'launch') as launch, patch.object(
                reader_module, 'resume_cleanup', return_value=Disposition('uncertain', 'identity missing')) as resume:
            with self.assertRaisesRegex(reader_module.HostThreadReadError, '^app_server_cleanup_unresolved$'):
                restarted('issued-session')
            resume.assert_called_once_with(str(latch))
            launch.assert_not_called()
        self.assertTrue(latch.exists())

        def settled(path):
            self.assertEqual(path, str(latch))
            latch.unlink()
            return Disposition('gone')
        with patch.object(reader_module, 'resume_cleanup', side_effect=settled) as resume, patch.object(
                reader_module.Custody, 'launch', side_effect=OSError('fixture stops before spawn')) as launch:
            with self.assertRaisesRegex(reader_module.HostThreadReadError, '^host_metadata_lookup_failed$'):
                restarted('issued-session')
            resume.assert_called_once_with(str(latch))
            launch.assert_called_once()

    def test_installed_owner_factories_share_one_reader_scope_across_evidence_ids(self):
        controller = self.root / 'controller'
        expected = str(controller / 'manager-ipc' / 'metadata-reader-scope.json')
        sources = ('operating_service.py', 'shared_operating_service.py', 'w0_codex_view_join.py')
        for source in sources:
            path = Path(__file__).resolve().parents[1] / 'install' / 'controller' / source
            tree = ast.parse(path.read_text(), filename=str(path))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'CodexAppServerThreadReader']
            self.assertEqual(len(calls), 1, source)
            option = next((kw.value for kw in calls[0].keywords if kw.arg == 'scope_latch_path'), None)
            self.assertIsNotNone(option, source)
            for evidence_id in ('startup-one', 'preflight-two', 'delivery-three'):
                scope = eval(compile(ast.Expression(option), str(path), 'eval'),
                             {'__builtins__': {'str': str}},
                             {'HERE': controller, 'C': controller,
                              'CONTROLLER': controller, 'evidence_id': evidence_id})
                self.assertEqual(scope, expected, (source, evidence_id))


if __name__ == "__main__":
    unittest.main()

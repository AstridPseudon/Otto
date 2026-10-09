"""Host-only scope probe selection; no Claude process or provider call."""
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from otto.agents.claude_cli import ClaudeBindingError, MacWriteScope, _preflight_interpreter, file_digest


class ScopeInterpreterTests(unittest.TestCase):
    def test_framework_wrapper_selects_only_direct_same_framework_binary(self):
        with tempfile.TemporaryDirectory() as root:
            version = Path(root) / 'Python3.framework/Versions/3.9'
            wrapper = version / 'bin/python3.9'
            direct = version / 'Resources/Python.app/Contents/MacOS/Python'
            for path in (wrapper, direct):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'host-test-executable')
                path.chmod(0o700)
            with patch.object(sys, 'executable', str(wrapper)):
                pin = _preflight_interpreter()
            self.assertEqual(pin, {'realpath': str(direct.resolve()), 'sha256': file_digest(direct)})
            direct.unlink()
            with patch.object(sys, 'executable', str(wrapper)), self.assertRaises(FileNotFoundError):
                _preflight_interpreter()

    def test_direct_executable_pin_and_policy_reject_drift_before_probe(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as state:
            direct = Path(state) / 'direct-python'
            direct.write_bytes(b'host-test-executable')
            direct.chmod(0o700)
            with patch.object(sys, 'executable', str(direct)):
                scope = MacWriteScope(root, state)
            with patch.object(sys, 'platform', 'darwin'), patch('otto.agents.claude_cli.subprocess.run') as run:
                run.return_value = subprocess.CompletedProcess([], 0, '', '')
                proof = scope.preflight()
                command = run.call_args.args[0]
                self.assertEqual(command[3], str(direct.resolve()))
                self.assertIn('(deny process-fork)(deny process-exec)', command[2])
                self.assertEqual(command[2].count('(allow process-exec'), 1)
                self.assertEqual(proof['preflight_interpreter']['sha256'], file_digest(direct))
                direct.write_bytes(b'changed')
                run.reset_mock()
                with self.assertRaises(ClaudeBindingError):
                    scope.preflight()
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

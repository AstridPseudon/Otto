"""herzchen-command-* owner directories are removed when the owning process exits."""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_CHILD = textwrap.dedent("""
    import os, sys
    from herzchen import command_ports as cp

    class Facade:
        endpoints = ("status",)
        domain_id = "test.domain"
        def status(self):
            return {}

    transport = cp._start_service(Facade(), "test.domain", "test.Facade", ("status",), None, sys.argv[1])
    mode = sys.argv[2]
    if mode == "raise":
        raise RuntimeError("command failed after the owner directory was created")
    if mode == "exit":
        sys.exit(0)
""")


def _run_child(scratch: str, mode: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": SRC, "HERZCHEN_IN_PROCESS_COMMAND_FALLBACK": "1"}
    return subprocess.run([sys.executable, "-c", _CHILD, scratch, mode],
                          capture_output=True, text=True, env=env, timeout=60)


class CommandDirCleanupTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="sl12-scratch-")

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def _leftover(self):
        return sorted(glob.glob(os.path.join(self.scratch, "herzchen-command-*")))

    def test_command_dir_removed_on_exit(self):
        result = _run_child(self.scratch, "exit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._leftover(), [])

    def test_command_dir_removed_on_error_exit(self):
        result = _run_child(self.scratch, "raise")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RuntimeError", result.stderr)
        self.assertEqual(self._leftover(), [])

    def test_socket_mode_dir_removed_on_exit(self):
        # AF_UNIX paths are limited to ~104 bytes on macOS, so use a short root.
        short = tempfile.mkdtemp(prefix=".sl12-", dir=os.path.expanduser("~"))
        try:
            env = {**os.environ, "PYTHONPATH": SRC}
            env.pop("HERZCHEN_IN_PROCESS_COMMAND_FALLBACK", None)
            result = subprocess.run([sys.executable, "-c", _CHILD, short, "exit"],
                                    capture_output=True, text=True, env=env, timeout=60)
            if "PermissionError" in result.stderr or "Operation not permitted" in result.stderr:
                self.skipTest("AF_UNIX bind denied in this sandbox")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(glob.glob(os.path.join(short, "herzchen-command-*")), [])
        finally:
            shutil.rmtree(short, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

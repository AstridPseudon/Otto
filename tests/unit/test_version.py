import subprocess
import sys

import otto


def test_version_is_set():
    assert otto.__version__


def test_cli_version():
    out = subprocess.run([sys.executable, "-m", "otto", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"otto {otto.__version__}"

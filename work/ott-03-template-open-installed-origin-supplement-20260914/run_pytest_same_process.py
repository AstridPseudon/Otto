from __future__ import annotations
import json
import os
import pathlib
import sys
import time
import importlib.metadata

import herzchen
import otto
import pytest

mode = sys.argv[1]
root = pathlib.Path(sys.argv[2])
if mode == "full":
    paths = [str(root / "tests/otto")]
elif mode == "focused":
    paths = [
        str(root / "tests/otto/test_selected_template_create_open.py"),
        str(root / "tests/otto/test_selected_template.py"),
        str(root / "tests/otto/test_owner_bootstrap.py"),
    ]
else:
    raise SystemExit(f"unknown mode: {mode}")
origin = {
    "mode": mode,
    "pid": os.getpid(),
    "python": sys.executable,
    "otto": otto.__file__,
    "herzchen": herzchen.__file__,
    "owner_bootstrap": __import__("otto.portfolio.owner_bootstrap", fromlist=["*"]).__file__,
    "otto_version": importlib.metadata.version("otto-local-candidate"),
    "herzchen_version": importlib.metadata.version("herzchen-contracts"),
    "sys_path": list(sys.path),
    "pythonpath": os.environ.get("PYTHONPATH"),
    "pythonhome": os.environ.get("PYTHONHOME"),
}
print("ORIGINS_BEGIN")
print(json.dumps(origin, indent=2, sort_keys=True))
print("ORIGINS_END")
started = time.time()
return_code = pytest.main(["-q", "-p", "no:cacheprovider", "-c", "/dev/null", *paths])
elapsed = time.time() - started
print(json.dumps({"mode": mode, "return_code": return_code, "elapsed_seconds": elapsed, "pid": os.getpid()}, sort_keys=True))
raise SystemExit(return_code)

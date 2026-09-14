from __future__ import annotations
import json
import os
import pathlib
import runpy
import sys

script = pathlib.Path(sys.argv[1])
print("WRAPPER_ORIGINS_BEGIN")
import herzchen
import otto
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
print(json.dumps({
    "pid": os.getpid(),
    "python": sys.executable,
    "otto": otto.__file__,
    "herzchen": herzchen.__file__,
    "owner_bootstrap": PortfolioOwnerBootstrap.__module__,
    "pythonpath": os.environ.get("PYTHONPATH"),
    "pythonhome": os.environ.get("PYTHONHOME"),
}, indent=2, sort_keys=True))
print("WRAPPER_ORIGINS_END")
runpy.run_path(str(script), run_name="__main__")

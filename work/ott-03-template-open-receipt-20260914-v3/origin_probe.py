"""Print installed import and distribution origins as JSON."""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import sys

import herzchen
import otto
from otto.portfolio import PortfolioOwnerBootstrap


print(json.dumps({
    "executable": sys.executable,
    "python": sys.version,
    "herzchen_import_origin": herzchen.__file__,
    "herzchen_version": importlib.metadata.version("herzchen-contracts"),
    "otto_import_origin": otto.__file__,
    "owner_bootstrap_origin": inspect.getfile(PortfolioOwnerBootstrap),
    "otto_version": importlib.metadata.version("otto-local-candidate"),
    "pytest_version": importlib.metadata.version("pytest"),
    "sys_path": sys.path,
}, indent=2, sort_keys=True))

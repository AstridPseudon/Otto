"""Run the runner daemon: ``python -m herzchen.fleet.runner --socket PATH --state-dir DIR``."""
from __future__ import annotations

import sys

from herzchen.fleet.runner import server

if __name__ == "__main__":
    sys.exit(server.main())

"""Launch only a fake PERCH staging owner with approving local presence."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import json
import re


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = os.environ.get("OTTO_STAGING_ROOT")
    if (os.environ.get("OTTO_STAGING_FAKE_PRESENCE") != "1" or not root
            or len(argv) != 4 or argv[0] != "--home" or argv[2:] != ["service", "run"]
            or Path(argv[1]).resolve() != (Path(root) / "home").resolve()):
        raise SystemExit("fake presence launcher requires the staging owner's service run")

    from otto.hostctl import presence

    class ApprovingPresence:
        def prove(self, *, reason, timeout_seconds):
            marker = Path(root) / "home" / "run" / "perch-fake-presence-deny.json"
            if marker.is_file():
                try:
                    request = json.loads(marker.read_text(encoding="utf-8"))
                except Exception:
                    request = {}
                task = request.get("task")
                match = re.search(r"Admit Otto task ([^ ]+) at revision ", reason)
                if isinstance(task, str) and match and match.group(1) == task:
                    marker.unlink()
                    return presence.PresenceResult("declined")
            return presence.PresenceResult("approved")

    presence.LocalAuthenticationProver = ApprovingPresence
    from otto.hostctl.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())

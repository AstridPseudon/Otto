"""The otto CLI.

Owned by the state project (docs/plan/projects/state/). Other projects supply
command handlers through the L0 contract (docs/plan/projects/contract.md).
"""

import argparse

from otto import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="otto", description="Run an organisation of AI agents on one machine.")
    parser.add_argument("--version", action="version", version=f"otto {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0

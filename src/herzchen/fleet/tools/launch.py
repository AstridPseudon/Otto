"""Safe command arguments for launching the fleet stdio tool server."""

from __future__ import annotations


_STDIO_SERVER_MODULE = "herzchen.fleet.tools.stdio_server"


def isolated_stdio_server_args(*server_args: str) -> tuple[str, ...]:
    """Build arguments that keep lab paths and ``PYTHONPATH`` out of server imports."""
    return ("-I", "-m", _STDIO_SERVER_MODULE, *server_args)

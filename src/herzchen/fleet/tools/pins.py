"""The one MCP server a worker sees, as a product-neutral grant.

The caller names the server, its tools, its command and its token; nothing here is product-specific.
A worker's tool surface admits exactly one server, and the OS fence lets the worker's process tree
execute exactly that server's binary, with the matching executable Python.app target added for a real
framework Python launcher (``exec_allow_for``), and nothing else.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from ..hosts.contract import HostContractError, McpGrant, McpServer


_PYTHON_FRAMEWORK_BINARY = re.compile(r"^python(?:[0-9]+(?:\.[0-9]+)*)?$")


def framework_python_app_exec(command: str) -> str | None:
    """Return the matching executable Python.app binary for a framework launcher, if present."""
    real = Path(os.path.realpath(command))
    if (not real.is_file() or not os.access(real, os.X_OK) or real.parent.name != 'bin'
            or not _PYTHON_FRAMEWORK_BINARY.fullmatch(real.name)):
        return None
    version = real.parent.parent
    framework = version.parent.parent
    if (version.parent.name != 'Versions' or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version.name)
            or framework.name not in {'Python.framework', 'Python3.framework'}):
        return None
    target = version / 'Resources' / 'Python.app' / 'Contents' / 'MacOS' / 'Python'
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if (not resolved.is_file() or not os.access(resolved, os.X_OK)
            or not resolved.is_relative_to(version)):
        return None
    return str(resolved)


def exec_allow_for_commands(commands) -> tuple[str, ...]:
    """Normalize executable pins, adding only matching framework Python.app binaries."""
    result = []
    for command in commands:
        resolved = os.path.realpath(command)
        result.append(resolved)
        python_app = framework_python_app_exec(resolved)
        if python_app is not None:
            result.append(python_app)
    return tuple(result)


def sole_server_grant(*, server, tools, command, args=(), token, token_env, token_env_prefix) -> McpGrant:
    """The grant for a worker: one MCP server with an explicit tool allowlist and one token."""
    tools = tuple(tools)
    if not tools:
        raise HostContractError("the sole MCP server needs an explicit tool allowlist")
    return McpGrant(servers=(McpServer(name=server, command=command, args=tuple(args), tools=tools),),
                    token_env=token_env, token=token, token_env_prefix=token_env_prefix)


def require_sole_server(grant, server) -> None:
    """Refuse any grant that is not exactly one server, named ``server``."""
    if not isinstance(grant, McpGrant) or len(grant.servers) != 1 or grant.servers[0].name != server:
        raise HostContractError("a worker must see exactly one MCP server, named %r" % (server,))


def exec_allow_for(grant) -> tuple:
    """Resolved server binaries, plus an existing same-version Python.app target when needed."""
    return exec_allow_for_commands(server.command for server in grant.servers)

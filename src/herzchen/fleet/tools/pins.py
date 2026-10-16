"""The one MCP server a worker sees, as a product-neutral grant.

The caller names the server, its tools, its command and its token; nothing here is product-specific.
A worker's tool surface admits exactly one server, and the OS fence lets the worker's process tree
execute exactly that server's binary (``exec_allow_for``) and nothing else.
"""
from __future__ import annotations

import os

from ..hosts.contract import HostContractError, McpGrant, McpServer


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
    """The resolved binary of every server in the grant: the only executables the fence admits."""
    return tuple(os.path.realpath(server.command) for server in grant.servers)

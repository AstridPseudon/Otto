## Design

The cited gap is real on `canon/main`: the manager role has no MCP calls, its transport receives no grant, and the facade admits only workers.

1. `src/otto/agents/claude_cli.py:63` and `src/otto/agents/claude_adapter.py:34` → Keep the three worker specs and grant separate. Add manager specs and role calls for exactly `whoami`, `status`, `show`, `save`, `answer`, `route`, `report`. Expose no project, principal, assignment, generation, session, token, or request-key argument. Use the existing CLI argument shapes for the four mutations.
2. `src/herzchen/fleet/hosts/claude.py:41` → A granted **manager work turn** must omit `--safe-mode`: current code says it drops MCP servers. Give that turn `dontAsk` and explicit `mcp__otto__…` allowed tools; keep the initializer MCP-empty. Update `src/otto/agents/claude_adapter.py:316` so its permission pin reports the launched mode.
3. `src/otto/agents/claude_adapter.py:268` and `:429` → Obtain a distinct manager grant **after** exact owner delivery authorization and before the useful work process starts. Apply it only to that manager turn’s transport, never to the worker transport. Require one `otto` server and the seven manager tool names.
4. `src/otto/hostctl/product_service.py:427` and `src/herzchen/fleet/tools/server.py:63` → Extend the existing facade and `TokenBook` with a manager role. On **both** listing and calling, authenticate the MCP child’s Unix-socket peer through the existing live native-process ingress; compare its owner-resolved project, assignment, generation, occurrence, and session with the manager token and current manager head. Revoke the prior turn’s token when issuing a replacement. Worker tokens must list and call only worker tools.
5. `src/otto/hostctl/product_service.py:221`, `:1241`, `:1343` and `src/otto/hostctl/serve.py:448` → Wire the shared owner router and ingress into that facade, then supply its manager grant to the default adapter. Run calls on the existing owner command pump. Translate tool arguments into the existing authenticated command requests: owner-resolved `whoami` context at `src/otto/portfolio/execution_host.py:1254`; `status/show/save/answer/route` at `src/otto/portfolio/manager_journey_service.py:880`; `report` at `src/otto/hostctl/serve.py:621`. Reuse `ProjectServices.dispatch_bound` at `src/otto/portfolio/project_services.py:154`. Mint mutation keys server-side using the existing `manager-tool:` convention at `src/otto/hostctl/manager_client.py:72`.
6. `src/otto/portfolio/manager_journey_service.py:725` → Make the manager caller check explicitly compare the project and current manager head/session as well as assignment and generation. This closes the interval in which an old, still-live process could retain a valid assignment after its session was replaced.

Add a real manager-launch integration test using the scripted provider in `tests/test_hostctl_serve.py:31`: discover and call all seven through MCP, verify effects in the bound project, and refuse worker credentials, a foreign project, an advanced generation, and a replaced session. The script stands in for the model; the facade and owner handlers remain real.

## First failing test

Add to `tests/test_tools.py` after `test_confined_worker_launch_flags`:

```python
def test_granted_manager_work_turn_enables_its_otto_mcp_tools(tmp_path):
    ws, state = _dirs(tmp_path)
    names = ("whoami", "status", "show", "save", "answer", "route", "report")
    grant = sole_server_grant(
        server=TOOL_SERVER,
        tools=names,
        command=sys.executable,
        token="manager-secret",
        token_env="OTTO_MANAGER_TOKEN",
        token_env_prefix="OTTO_MANAGER_",
    )
    host = get_host("claude-code")
    work = _confined_spec(
        ws, state, mcp=grant, tools=MANAGER_TOOLS,
        allow_subprocesses=True,
    )
    argv = list(host.launch(work).argv)

    assert "--safe-mode" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert [name for name in
            ("mcp__otto__" + tool for tool in names)
            if name in argv[argv.index("--allowedTools") + 1:]] == [
                "mcp__otto__" + tool for tool in names
            ]
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    assert list(config["mcpServers"]) == ["otto"]
    assert "manager-secret" not in json.dumps(argv)

    initial = _confined_spec(
        ws, state, mcp=grant, initializer=True,
        allow_subprocesses=True,
    )
    initial_argv = list(host.launch(initial).argv)
    assert json.loads(initial_argv[initial_argv.index("--mcp-config") + 1]) == {
        "mcpServers": {}
    }
```

It fails now at `--safe-mode`. The later integration test must prove actual discovery, calls, and effects; launch flags alone do not establish that.

## Delete

Remove the manager’s empty-call entry at `src/otto/agents/claude_adapter.py:37` and the granted-manager `--safe-mode` branch. Keep the existing CLI handlers and worker grant. Do not add a second implementation of save, answer, route, or report.

## Plausible mistake

A worker token reused for manager tools, or authorization performed only during `tools/list`, would expose foreign or stale mutations. The integration test must list with each credential **and then call a mutation after** changing the manager generation/session; it must verify no report, note, answer, or route effect was committed. The first test separately catches the launch-mode mistake that would hide every granted MCP tool.

## D19 and row corrections

**D19 decision needed:** change `tests/test_tools.py:749`’s expectation that manager calls are `()` and its manager-empty-list assertions at `:762`. The new expectation is exactly the seven manager tools; the worker’s three-tool expectation stays. Record that reason in the required D19 review before changing those existing assertions. The ungranted-manager safe-mode assertion at `tests/test_tools.py:865` remains valid.

The row omits the `--safe-mode` blocker at `src/herzchen/fleet/hosts/claude.py:402`. Its `serve.py:479` evidence is specifically the **worker** Due branch, not a manager grant. `whoami` is an ExecutionHost identity read, while `report` delegates to HostOwnerService; treating all seven as one new mutation handler would duplicate existing authority. No files were changed and no tests were run.
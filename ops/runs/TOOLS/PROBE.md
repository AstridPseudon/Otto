# TOOLS live probe: the Claude CLI as a worker (16 Oct 2026)

Script: `probe_claude.py` (one real `claude` turn per run, a paid call, through the same `TurnSpec`, `MacWriteScope`
and host launch plan the worker transport uses). CLI under test: `2.1.301 (Claude Code)`, model `claude-haiku-5-5`,
effort low. The host's qualified version is 2.1.293, so the script qualifies the observed version for its own run only.

Each run writes `probe-claude-<variant>-<stamp>.jsonl` (raw stream-json) and `.verdict.json` (tool results paired with
their calls, the init frame, the argv, the exec allowance). Fixtures: a workspace with `inside.txt`, a sibling
`outside/secret.txt` holding a canary, a facade server on a unix socket, one token for one assignment.

| run | launcher shape | outside Read/Grep/Glob | `otto` server | inside Write/Edit |
|---|---|---|---|---|
| `probe-claude-2026...134943Z` | as shipped in 6e5725b: `--safe-mode`, `--dangerously-skip-permissions` | **all three returned the canary** | not registered (`mcp_servers: []`, "No such tool") | not asked |
| `A-nosafe` | `--safe-mode` and `CLAUDE_CODE_SAFE_MODE` removed | all three returned the canary | connected, `task` answered, `check` refused by the allowlist | not asked |
| `B-dontask` | A plus `--permission-mode dontAsk` (single-slash `Tool(/abs/**)` rules) | all three refused | connected | not asked |
| `C-launcher` | the launcher code, single-slash rules | all three refused | connected | **Write and Edit inside refused** |
| `D-abs-rules` | the launcher code with `Tool(//abs/**)` rules (as committed) | **all three refused** | **connected; `task` answered** | **Write and Edit inside allowed, Write outside refused** |

What this establishes:

1. `--dangerously-skip-permissions` makes the `--allowedTools` path scopes inert. The OS fence (`sandbox-exec`) confines
   writes only (`(allow default)`), so Read, Grep and Glob read any file the user can. The goldens' scoped `Read(<ws>/**)`
   never did anything. This was already true of the Read-only worker, and Grep and Glob widen it.
2. `--safe-mode` (flag and `CLAUDE_CODE_SAFE_MODE=1`) drops every MCP server, so a worker that is granted its one server
   cannot run in safe mode. Settings, slash commands and other MCP configs stay off through `--setting-sources ''`,
   `--disable-slash-commands` and `--strict-mcp-config` (init showed `skills: []`, `slash_commands: []`, one MCP server).
3. In a rule, `/path` is project-relative and only `//path` is absolute. Under `dontAsk` a single-slash rule matched
   nothing, so Write and Edit were refused even inside the workspace; Read inside only worked because reads in the working
   directory are allowed by default.
4. The `otto` stdio server starts from inside the sandbox when the fence allows fork and exec of exactly its binary. On a
   macOS framework Python the interpreter re-execs `Python.app/Contents/MacOS/Python`, so both paths must be allowed
   (the script does; an earlier `sandbox-exec`-only probe showed the same). The unix-socket connect is not denied.
5. The strict stream parser rejects this CLI's init frame (`ClaudeBindingError: ...ingress mismatch`) because 2.1.301 lists
   two builtin plugins (`plugins != []`). That is true of the baseline shape too and is a launcher-qualification matter
   for 2.1.301, not a change made here.

Not probed: a Codex MCP call under workspace-write. `codex exec` reads credentials from and writes sessions into
`~/.codex`, which this row may not touch, and an isolated `CODEX_HOME` has no credentials. The Codex path is covered
by the launch-plan harness test only.

Not probed: an MCP-less worker under the new shape. Only a worker that is granted its server takes the `dontAsk` launch;
an MCP-less worker still runs under `--dangerously-skip-permissions` and can read outside its workspace (unchanged).

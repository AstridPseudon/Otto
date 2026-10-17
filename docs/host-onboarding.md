# Onboarding a host (any agent CLI) onto the one Otto

A *host* is one agent CLI on one machine account, for example Codex or
Claude Code. A machine has ONE Otto:
- one Store;
- one running owner service that holds it (`ottoctl service run`);
- one owner principal.

Every host is a **client** of that service, acting as its **own** orchestrator
principal in its own portfolio. A host never opens the Store, never starts a
second owner and never borrows another host's principal or session. See
[OTTO-ONE.md](../OTTO-ONE.md) for the design and its decisions.

## Operator: install, run, admit

```sh
python3.11 -m venv ~/.otto/venv
~/.otto/venv/bin/pip install --no-index --no-build-isolation /path/to/otto   # stdlib only
ottoctl --home <service home> install --store <owner.sqlite> --authority <authority> \
    --owner <owner principal> --credential-ref <this installation's credential label>
ottoctl --home <service home> service run          # foreground; or a launchd agent
ottoctl --home <service home> service admit-host --host claude-code --client-home ~/.otto
```

- **`install`** attaches an existing Store: it opens it once with the exact
  persisted domain set and pins its identity. `--create` makes a new Store
  (fresh machines and tests only).
- **`service run`** holds the Store for its whole life. It starts no Due and
  calls no provider. `service stop` drains it, then closes it.
- **`service admit-host`** is the owner action that admits a host. It:
  - assigns the host's orchestrator principal (default `<host>-orchestrator`)
    in `wrk.portfolio/<host>-portfolio`;
  - creates the host's lane in its client home;
  - writes `client.json` there. That file names a principal and a lane, never
    a Store.

## Host: work through your lane

`OTTO_HOME` is your client home; the default is `~/.otto`. With more than one
admitted host in one home, pass `--host` (or set `OTTO_HOST_KIND`).

| Command | Effect |
|---|---|
| `ottoctl service status` | is the owner busy? Holder, generation, heartbeat, attached project, manager turn, in-flight requests |
| `ottoctl whoami` / `effective-context` | your principal, role, portfolio and adopted direction |
| `ottoctl projects` / `project status --project R` | records; documents checked against the digests of the last sync |
| `ottoctl project register --bundle DIR` | an inert draft through the onboarding route; the WHOLE run dir becomes documents |
| `ottoctl project sync-docs --project R` | records run-dir work in Otto, before and after activation |
| `ottoctl project activate --project R` | materializes tasks, roles, pools and paused checks from Otto's documents; adopts the operating setup; nothing starts |
| `ottoctl project import-history --bundle DIR --note ...` | keeps a closed run as withdrawn history |
| `ottoctl admission dry-run --project R` | would the manager be admitted now? Writes nothing |
| `ottoctl manager --project R <command>` | owner-custody manager commands (start-manager, status, ...), relayed to the project's manager lane |
| `ottoctl help read\|respond --project R` | escalations: read them, and answer as the project's supervisor |
| `ottoctl request-status --request-id T` | the response to a retained request (when a wait timed out) |

If no service answers, commands exit 3 with `owner_service_not_running`. A
request already written stays retained; read it later with `request-status`.

## Add a new agent CLI

The hooks already exist. A new CLI plugs in at the same points as Codex and
Claude Code.

### Contributor map: third-host extension

Use this route when adding a host kind to the codebase. The fleet contract is
the extension point; Otto's host control and admission code is the integration
path around it.

| Work | Start here | Then update |
|---|---|---|
| Implement the host kind | `src/herzchen/fleet/hosts/contract.py` (`HostKind`) and the sibling implementations `claude.py` / `codex.py` | Add `src/herzchen/fleet/hosts/<kind>.py`; export and register it in `src/herzchen/fleet/hosts/__init__.py` (`REGISTRY`) |
| Make Otto admit and launch it | `src/otto/hostctl/config.py`, `service.py`, and `adapters.py` | Add the host model profile in `src/otto/agents/host_profiles.py`, its native adapter/result verifier beside `claude_adapter.py`, and `policy-staging/megado/skill/templates/run.<kind>.json` |
| Check the contract and integration | `tests/test_host_contract.py` | Also run `tests/test_hostctl_cli.py`, `tests/test_host_neutral_defaults.py`, `tests/test_megado_templates.py`, and `tests/test_hostctl_serve.py` for Otto wiring; copy the Claude binding/admission focused tests for host-specific coverage |

The fleet registry and Otto admission are separate steps: registering a
`HostKind` makes `get_host(<kind>)` resolve it, but does not admit an agent CLI
to a running Otto. The operator admission route is `ottoctl service
admit-host --host <kind>`; its host configuration must resolve to a pinned,
owner-bound adapter and declared capabilities. Follow the numbered steps below
for adapter, fence, profile, and conformance details.

**Gate boundary.** Focused fixtures establish mechanics; they do not establish
that a native CLI is safe or live-ready. A native launcher/write-fence probe,
actual owner or staging journey, or check that requires `sandbox-exec`, `ps`,
or a staging owner needs the project gate. In a sandbox where those facilities
are unavailable, record the check as `needs the gate` and continue with the
focused offline tests. Keep live behavior `unverified` until a real journey
runs.

1. **Adapter module.** Write it next to `otto/agents/claude_cli.py` and
   `claude_adapter.py`:
   - `LauncherPin`: an absolute launcher, its realpath, sha256 and exact
     `--version`. Qualified versions are listed explicitly, never matched by
     prefix.
   - A bounded transport with an inert initializer.
   - An adapter with:
     - `owner_bound` and `require_host_context`;
     - a stable `adapter_identity`;
     - `bind_owner_authorization(..., role, profile)` and
       `validate_owner_host_composition(role, profile)`;
     - the thread and turn callbacks;
     - `invoke` (and `resume` for a manager).
   - A native result verifier.
2. **Declare capabilities.** Never imply them:
   - roles (worker leaf and/or manager);
   - `leaf_only`;
   - per-role tool profiles;
   - a `capabilities()` map in which each item is supported, unsupported,
     degraded or unverified, with its reason.
3. **Fence.** If a role runs commands, prove in the preflight that children
   inherit the write fence. `MacWriteScope(allow_subprocesses=True,
   extra_write_roots=...)` is the macOS example. A manager is given exactly
   one extra write root: its own manager lane.
4. **Admit and register on the host.** `service admit-host --host <kind>`
   records the adapter (launcher, qualified versions, roles, profiles,
   efforts, models). `otto.hostctl.adapters` turns that into a
   `TrustedAdapterSelection`.
5. **Model profile.** Add a profile to `otto/agents/host_profiles.py`, binding
   the seven Megado slots. Add the skill template
   `policy-staging/megado/skill/templates/run.<host>.json`.
   `tests/test_megado_templates.py` keeps the two equal.
6. **Conformance.** Copy these tests:
   - `src/otto/agents/tests/test_claude_binding.py`;
   - `tests/test_claude_manager_admission.py`;
   - `tests/test_hostctl_serve.py`. Its synthetic stream-json launcher runs
     under the real fence; a native launcher is needed for the worker leaf.

   No paid call is needed to qualify the mechanics. Live behaviour stays
   `unverified` until a real journey runs.

### Managers whose CLI creates its session at first launch

Codex creates its manager thread before activation. A CLI that creates its
session on first launch uses the `fresh_manager` occurrence:

1. The inert initializer reports the session.
2. The owner authorizes it before any useful input.
3. Later turns `--resume` that exact session.

Readiness and the help loop bind the conversation from the owner's own
authorized delivery.

## From a Megado run directory to an Otto project

1. **Register.**
   - `project register --bundle DIR` creates the draft and its documents (the
     whole directory, nested paths kept).
   - It enrolls the draft in your portfolio, so your orchestrator is the
     accountable supervisor and help routes to you.
2. **Edit and sync.** While pending, the run directory is the authority;
   `sync-docs` mirrors it.
3. **Activate.** From activation on, Otto is the authority. `sync-docs` keeps
   recording run work and never overwrites an Otto-side edit; it reports
   `otto_newer` or `conflict`.
4. **Start.** `manager --project R start-manager --schedule-id <setup.roles.manager>`
   launches the manager. Its commands then reach the owner over its own
   lanes.
5. **Bind the checks.** Bind and resume the orchestrator checks with your
   conversation and host scheduler. On Claude Code that is `/loop` or
   CronCreate.

A walkthrough: [Start and run a project with Megado, from any host](megado-from-any-host.md).

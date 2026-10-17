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
| `ottoctl projects` / `project status --project R` | records and project documents |
| `ottoctl project register --bundle DIR` | an inert draft through the onboarding route; the WHOLE run dir becomes documents |
| `ottoctl manager --project R project-authoring --operation open\|check-in\|read` | the bound manager's owner-backed project.json authoring |
| `ottoctl portfolio apply --root DIR` | registers and reconciles a file-mode portfolio tree, including root shared documents |
| `ottoctl portfolio documents --operation list\|read` | reads shared portfolio documents |
| `ottoctl manager --project R project-documents --operation list\|read` | reads project documents and associated shared portfolio documents |
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
2. **Edit.** A bound manager uses its owner-backed `manager project-authoring`
   open/check-in operation for project.json. For file-mode portfolio bundles
   and shared root documents, preview and apply with `portfolio apply --root DIR`; resolve
   reported conflicts before reconciling again. There is no `project sync-docs`
   route.
3. **Activate.** `project activate --project R` materializes the project from
   Otto's canonical documents; activation remains an explicit step.
4. **Start.** `manager --project R start-manager --schedule-id <setup.roles.manager>`
   launches the manager. Its commands then reach the owner over its own
   lanes.
5. **Bind the checks.** Bind and resume the orchestrator checks with your
   conversation and host scheduler. On Claude Code that is `/loop` or
   CronCreate.

A walkthrough: [Start and run a project with Megado, from any host](megado-from-any-host.md).

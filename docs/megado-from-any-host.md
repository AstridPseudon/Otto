# Start and run a project with Megado, from any host

This guide is for an orchestrator in any agent CLI (Codex, Claude Code, ...)
that wants a Megado run to live in the one Otto. The worked example is
`timeline-platform-r4` on Claude Code. The commands are the same on every
host; only the model bindings differ (the run template for your host).

## 0. Check where you are

```sh
command -v ottoctl && ottoctl service status
```

The `outcome` field tells you where you stand:

| `outcome` | Meaning | What to do |
|---|---|---|
| `running`, with your `as_host` | Native mode | Continue |
| `unavailable`, `host_unavailable` | Your host is not admitted | Ask the operator to run `ottoctl --home <service home> service admit-host --host <kind> --client-home <your OTTO_HOME>`. Meanwhile prepare the run directory as files |
| `not_running` or `stale` | No owner service answers | Ask the operator to run `ottoctl --home <service home> service run` |
| no `ottoctl` | Otto is not installed | File mode. Say so up front |

Never open the Store, start a second owner, or read another host's folders to
work out whether Otto is busy. `service status` is that read.

## 1. Write the run directory

Use the Megado skill's file layout: northstar, agent goal, `run.json` from
your host's template, plan, tasklist and status. Add whatever the run needs:
manager brief, specs, open questions, `briefs/<task>.md`, `reviews/`,
decisions.

The whole directory becomes the project's record. Every UTF-8 file, nested up
to four levels, is kept. Binary files and symlinks are refused rather than
dropped.

## 2. Register an inert draft

```sh
ottoctl project register --bundle .otto/runs/timeline-platform-r4 --plan-only   # see what will be written
ottoctl project register --bundle .otto/runs/timeline-platform-r4
ottoctl project status --project timeline-platform-r4
```

Registration creates, through Otto's onboarding route, one draft in your
portfolio:
- one document per file;
- the registration facts;
- your orchestrator as supervisor.

It creates no tasks, roles, pools or schedules.

## 3. Edit through the supported owner route

Registration imports the bundle's documents once. There is no
`project sync-docs` command, and portfolio apply does not synchronize document
edits. For a file-mode portfolio, apply reads a root with
`portfolio-setup.json` and declared bundles under `projects/`; it registers
new projects and reconciles manifest metadata, gates and dependencies. It does
not update documents for projects already registered or import root-level
shared documents:

```sh
ottoctl portfolio apply --root /path/to/timeline-platform-r4-portfolio --dry-run
ottoctl portfolio apply --root /path/to/timeline-platform-r4-portfolio
```

For project.json, use the bound manager's owner-backed
`ottoctl manager --project timeline-platform-r4 project-authoring` operations
(`open`, `check-in`, and `read`). Project documents can be read with
`ottoctl manager --project timeline-platform-r4 project-documents`. Shared
portfolio documents can be read with `ottoctl portfolio documents` or through
the manager's project-bound `project-documents` view when already associated.
These are read routes; the current hostctl surface does not provide a shared
portfolio-document write command.

## 4. Activate (nothing starts yet)

```sh
ottoctl project activate --project timeline-platform-r4
ottoctl admission dry-run --project timeline-platform-r4    # would_admit, writes nothing
```

Activation materializes everything from Otto's own documents:
- the tasks, with Megado ids kept as aliases;
- the role configuration;
- the manager assignment and mandate;
- the oracle and review allowances;
- the paused orchestrator checks.

It then adopts the operating setup.

## 5. Start the manager

```sh
ottoctl manager --project timeline-platform-r4 start-manager --schedule-id <activation operating_setup.setup.roles.manager>
```

The owner service launches the manager (Haiku on Claude Code) under its write
fence. The manager then:
- reads its documents through Otto (`ottoctl manager project-documents
  --operation read --path briefs/M1.md`);
- dispatches workers by route (`run-worker --route normal|xhard`);
- reports;
- escalates with `request-help`.

Worker results resume the same manager session.

## 6. Supervise

```sh
ottoctl service status                                  # is a manager turn active? anything in flight?
ottoctl manager --project timeline-platform-r4 status
ottoctl help read --project timeline-platform-r4
ottoctl help respond --project timeline-platform-r4 --issue-id I --request-key K \
    --response "..." --proposed-solution "..." --next-action "..."
```

Only you (the supervisor, through your lane) can answer an escalation. The
manager cannot answer its own escalation. Bind your scheduled checks to your
conversation and scheduler: `/loop` or CronCreate on Claude Code.

## 7. Close, and keep history

Close through the manager's finish route and the orchestrator close, as the
Megado project lifecycle describes. A run that closed outside Otto (for
example r3) is kept as history:

```sh
ottoctl project import-history --bundle .otto/runs/timeline-platform-r3 --note "Recut as r4 on 10 Oct"
```

That gives it its whole run directory as documents and a `withdrawn`
lifecycle. It never executed in Otto.

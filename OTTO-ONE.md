# One Otto: Claude Code joins the shared Otto as its own principal

Branch `claude-host/one-otto`, based on Codex's head `a0392d3`. It lives in the
Claude host's clone (`~/Developer/otto-claude-host/otto`). Nothing has been
pushed to Codex's repository, and nothing has been written to Codex's live Store.
Whether and when Codex adopts this branch is the user's decision; Codex would
adopt it by fetching from that clone into its own tree.

## The model

- **One Store, one owner service.** `ottoctl service run` is the only process
  that opens the Store. It holds the Store under its exclusive writer lock for
  its whole life and performs every write. All writes in the process go
  through one command lock. During a manager's native turn, finite operations
  run on the owner's pump.
- **Every host is a client, as its own principal.** A host's `ottoctl` writes
  each request into its own *lane*: a 0700 directory in the host's client home.
  The service answers there. The lane binds the principal; a request cannot
  name one. A client home holds only `client.json` and its lanes. It names no
  Store, so a client can never open it.
- **Admitting a host is an owner action:**
  `ottoctl --home <service home> service admit-host --host claude-code --client-home <claude home>`.
  It assigns the host's own orchestrator principal in its own portfolio
  (`wrk.portfolio/claude-code-portfolio`) through
  `ResponsibilityAssignments.assign`, and creates the host's lane.
- **"Is the owner busy?" is a supported read:** `ottoctl service status`. It
  reports the holder pid, generation, heartbeat, attached project, whether a
  manager turn is active, and in-flight lane requests and relays, as published
  by the service. Nothing reads another host's folders.
- **One owner principal (ruling, 11 Oct).** The Store keeps ONE owner service
  principal (`otto-operating-setup-owner`). Claude's installation uses its own
  credential label. Every Claude action runs under Claude's own principals and
  portfolio. Reason: Codex's ProjectServices requires one owner actor across
  all project views. A second owner principal in the same authority would
  recreate two authorities in one Store.
- **Same-account caveat.** Codex, Claude and the service all run as one macOS
  account. A lane binds intent and prevents one host being mistaken for
  another. It is not a defence against a hostile process in the same account,
  and no lane in one account can be. The kernel-level checks that do exist
  remain: caller-socket peer ancestry for launched processes, and write fences
  for launched roles.

### What a host does through its lane

| Command | Effect |
|---|---|
| `ottoctl whoami`, `effective-context`, `projects` | the host principal's own context and portfolio (reads) |
| `ottoctl project register --bundle DIR` | an inert draft through the canonical onboarding route, with the WHOLE run dir as documents, enrolled in the host's portfolio |
| `ottoctl project sync-docs --project R` | records run-dir work as new revisions or documents, before and after activation; never overwrites an Otto-side edit |
| `ottoctl project activate --project R` | materializes tasks, roles, pools and paused checks from Otto's own documents and adopts the operating setup. Nothing starts |
| `ottoctl project import-history --bundle DIR --note ...` | a closed run kept as withdrawn history |
| `ottoctl admission dry-run --project R` | would the manager be admitted now? Writes nothing |
| `ottoctl manager --project R start-manager --schedule-id S` | relayed to the project's manager lane: launches the prepared manager |
| `ottoctl help read\|respond --project R` | the orchestrator's side of escalations |

The launched manager uses its own lanes:
- its file lane, which its write fence admits, for `report`, `request-help` and
  `resolve-help`;
- the caller socket, authenticated by kernel peer ancestry, for `whoami`,
  `run-worker` and `project-documents`.

The manager reads its project's documents through Otto:
`ottoctl manager project-documents --operation list|read --path briefs/M1.md`.

## What changed in Codex-owned code, and why

In merge order (each commit message has the details):

1. `0aa435c` **Caller ancestry stops at the owner.** A terminal-launched owner
   previously failed to authenticate its own children.
2. `d336c73` **Host-neutral defaults.** Model defaults, adapter efforts and the
   manager port name no single host.
3. `b8c271d` **Claude Code may be a declared manager.**
   - The `fresh_manager` execution mode covers a CLI that creates its session
     at first launch: inert initializer, then owner authorization, then the
     work turn.
   - A no-cost dry-run admission proves it.
4. `d288e7b` **Megado setup frictions.**
   - A run.json loader.
   - Host role guidance.
   - The Claude run template.
5. `f2de8a0` **Claude usage in Codex's Usage model,** with Anthropic semantics:
   - additive cache read and creation tokens;
   - `total_cost_usd` / `modelUsage.costUSD`;
   - a `by_model` view.
6. `7e45ba7` and `5f5f8ad` **Receipt events are filtered by subject** before
   the shared Store's whole history is decoded. Draft creation on a 7.6 GB
   clone of the live Store had hung; it now takes 4 s.
7. `6775375` **Role guidance names the host's own command,** not one Codex
   run's controller path.
8. `eae211e` **A fresh-session manager is carried through resume, readiness
   and help:**
   - `--resume` of the exact owner-bound session;
   - the conversation is bound by the owner's authorized delivery. Before
     this, every orchestrator reply to such a manager failed with "role
     conversation current assignment/project differs";
   - manager lanes;
   - `project-documents` is admitted as a finite socket read. This is one
     entry in ExecutionHost.
9. `8b1166b` **The arbitrary whole-project cap is replaced by per-operation
   batching.**
   - Before: `project_folder.py` capped a WHOLE project at 50 files and
     1 MiB in total, and checked that at checkout, check-in, import and
     transfer.
   - Now:
     - one file holds up to 10 MiB;
     - one operation carries up to 1,000 files and 256 MiB;
     - a whole tree is refused only when pathological (100,000 files or
       2 GiB, because a checkout materializes every file).
   - Search and bundle export page instead of failing.
   - The cap also hid quadratic reads: every document read re-listed the
     whole project. A 200-document, 5 MiB round trip went from 702 s to 14 s.
   - Reason: a project must hold its whole record. r4 alone is 74 documents
     and about 0.9 MB.
10. `52cf6a5`, `d7905d2`, `b9c4c3d`, `673c433`, `0625c5c` and `d09620d`
    **`otto.hostctl`** (the service, lanes, register, sync, activate and
    history) and the packaging that installs `ottoctl`. These are new files
    only.

## How this coexists with Codex's current controllers

Today Codex launches per-project owner services from run directories
(`controller/operating_service.py`, supervised by a waiter, with receipts
under `~/.codex/owner-services`). Each one opens the Store under the same
exclusive writer lock that `ottoctl service run` uses.

**(a) Clients, or alternating under the lock?**

*Alternating* works mechanically, because the lock decides. The clone proof
ran exactly that way. What breaks:
- While a Codex owner holds the Store (about 18-minute sessions, often back to
  back), Claude's requests and its running manager stall. The manager cannot
  report, escalate or receive worker results.
- A running manager's lanes belong to the service that launched it. The other
  owner cannot serve that manager.
- Scheduled checks are served only by whichever owner is up.
- Every switch is an operator action: a drain, then a start.

*Clients* means:
- Codex's orchestrator is admitted as host `codex`, and its portfolio reads
  and writes go through its lane.
- Codex's projects run as project views inside the one service.
- What breaks is Codex's out-of-git controller layer:
  - `operating_service.py`, the waiter and the owner-services receipts must be
    ported into, or replaced by, the one service's composition;
  - live occurrences must be drained at a boundary before they move.
- Alternating is acceptable only as a bounded transition. The steady state is
  clients.

**(b) Migrating Codex's live projects** (Usage, Onboarding, Vision, the
validation project, the port's Luna manager), one project at a time. For each:
1. Wait for a boundary: no native turn in flight, and the current Due settled
   or explicitly held.
2. Drain that project's Codex owner (its stop marker).
3. The one service attaches the project's view from its retained state and
   records.
4. Verify:
   - the readiness read matches;
   - a no-op status read through the new lane succeeds;
   - the schedules are unchanged.

Projects without a running manager go first: the validation project, then
drafts. A project in a correction loop (Onboarding D01) goes after its current
turn settles. The port's manager goes last, or at its completion.

**(c) Who runs it.** This is the user's decision:
- The operator is either the user or Codex's controller acting as operator.
  The operator needs only `ottoctl --home <service home> service run`.
- Start and restart can be a launchd LaunchAgent (user domain) with
  KeepAlive, preferably wrapped in Codex's existing
  `ExecutionHost.supervise_owner_service`. That wrapper reconciles retained
  effects before every relaunch and bounds restarts.
- Stop is `ottoctl service stop`, which drains first.

**(d) One convergence with ProjectServices.**
- Codex's in-progress "multi-project host" (ProjectServices) composes fixed
  project views over one owner, one Store, one Due port and one ExecutionHost
  with bounded transports. Optional `owner_route` grants authenticate owner
  requests.
- `ottoctl service run` is the process around that:
  - it holds the Store;
  - it admits hosts;
  - it publishes status;
  - it routes each host lane as an authenticated owner route.
- Today it attaches one project's view at a time
  (`serve.HostOwnerService`, which is exactly the `server` object a
  ManagerJourneyService view expects).
- Convergence: the service installs ProjectServices with one
  HostOwnerService view per attached project. Host lanes and their grants
  become ProjectServices' `owner_route`. There is no second multi-project
  mechanism.

**Decision points for the user:**
1. Admit Claude Code to the shared Store, and who performs the admission.
2. Who operates `service run`, and whether launchd supervises it.
3. Land ProjectServices inside `service run`, then migrate Codex's projects one
   at a time; or alternate for a bounded period first.
4. Document visibility (see Findings): keep registered documents private to
   the authoring principal, or make project documents shared within their
   project.

## Joining the live Store: the facts

Nothing below has been done on the live Store.

**Commands.** On the service home:
```sh
ottoctl install --store <live owner.sqlite> --authority otto-project-operating-setup-20261005-owner-v1 \
  --owner otto-operating-setup-owner --credential-ref otto-shared-owner-credential-claude-host-v1
ottoctl service run
ottoctl service admit-host --host claude-code --client-home ~/.otto
```
Then, as the Claude client:
```sh
ottoctl project register --bundle <run dir>
```

**What they write.**
- `install` writes `installation.json` in the service home. It opens the
  Store once with the exact domain set (digest `e86780ac…`) and records that
  digest and the Store's inode.
- `admit-host` writes one orchestrator assignment in `claude-code-portfolio`.
- `register` writes:
  - the draft project;
  - one document and link per run file, plus Otto's `brief.md`;
  - the registration facts;
  - the portfolio enrollment.
- No Due, task, role or pool is created before activation.

**Guards used** (scripted for the clone proof):
- Before each step:
  - `lsof` shows nobody holding the db or the lock;
  - no owner process is running;
  - the db's mtime and size are unchanged since the last step.
- An APFS `clonefile` backup is taken under the owner flock. The flock was
  held for 0.0025 s.
- `integrity_check` runs on a post-write clone, never on the live file.
- Both clones are deleted afterwards, and everything is logged in
  `production/ledger/housekeeping.log`.

**Clone proof (11 Oct)** on a clone of the live Store (7.6 GB):
- The clone tool waited 121 s for idle, took the clone, and `integrity_check`
  returned ok in 21 s.
- install, join, register, activate, dry-run (`would_admit`) and a serve smoke
  test all succeeded.
- All 16 Codex projects were byte-identical before and after.
- The proof added 49 receipts/events and 69 identities.
- The clone was deleted.

The proof used the pre-service command set; the owner operations are the same.

**The service split proven on disposable NEW Stores.** An in-process suite,
plus one process-level run with real macOS write fences, covered:
- admission;
- client register (with nested briefs) and activate;
- the dry-run;
- relayed start-manager;
- the manager authenticating, listing and reading its briefs through Otto;
- Haiku and Sonnet workers reporting back to one resumed manager session;
- escalation and reply;
- stop.

**Two permission denials** stopped the live sequence. Exact wording:
1. When reading Codex's owner-services launch receipts to learn the owner
   process names:
   "Permission for this action was denied by the Claude Code auto mode
   classifier. Reason: [Credential Exploration]."
2. When writing the guarded driver whose steps would attach, admit and register
   on the live Store:
   "Permission for this action was denied by the Claude Code auto mode
   classifier. Reason: [Modify Shared Resources]."

Both were reported, not worked around. They led directly to the service/client
split above: no Claude process opens Codex's Store or inspects `~/.codex`.

## Expectations of the one-Otto setup

- **Everything is saved in Otto.**
  - A run is registered with its WHOLE run directory as documents: plan,
    briefs, specs, reviews, decisions, archive, status.
  - Later work is recorded with `sync-docs`, before and after activation.
  - Closed runs are imported as history (`import-history`; withdrawn, never
    executed in Otto).
- **Run work keeps flowing in after activation.** Otto is the authority then.
  A three-way digest check never overwrites an Otto-side edit; conflicts are
  reported.
- **No document cap per project.** Only per-file and per-operation bounds
  apply.

## Findings for Codex

- **Document visibility.** `create_draft` creates every document `private` to
  its authoring principal.
  - A host principal's registered documents are therefore invisible to the
    owner and to the project's manager.
  - The service now discloses exactly a project's `project.files` to that
    project's bound manager, reading as the accountable supervisor.
  - The open question: should project documents be `shared` within the
    project (authoring scope) at onboarding?
- **The manager surface had no document read.** It is now `project-documents`.
  Codex's own managers could use the same command.
- **Event history at scale.** Any whole-history read
  (`list_events()` without a subject) is O(Store). df32538 removed the one on
  the onboarding path; others may remain.
- **Socket reply size.** `caller_client` caps a socket reply at 4 MiB. A
  manager reading a document larger than that needs paging.

## Tests

### Suite comparison

The full suite was run per module, at most 3 in parallel, on Python 3.9,
against Codex's `a0392d3` and this branch at `0625c5c` (code-identical to the
head; later commits change only the skill text and docs).

| | Tests | Failing |
|---|---|---|
| `a0392d3` (Codex head) | 943 | 15, plus `test_initial_manager_transport`, which hangs past 900 s |
| this branch | 1050 | 14, plus the same hang |

- **Fixed on the branch (2):**
  - `test_native_caller_ingress …same_uid_spoof`;
  - `test_worker_occurrences …capacity_one_real_parent…`.
  Both are fixed by the ancestry correction (`0aa435c`).
- **New on the branch (1):**
  `test_manager_assessment_ipc …test_unknown_is_not_accepted…` failed once.
  The test's `wait_file` helper read a child receipt while it was being
  written (JSONDecodeError). The module passed that test in two reruns; the
  same race exists at `a0392d3`.
- **The other 13 failures are identical on both sides:**
  - `test_advisor_lifecycle`;
  - the two `installed_journey` tests;
  - `test_help_completion_regression` (2);
  - `test_manager_advisor_followup_command`;
  - `test_manager_assessment_ipc` (2);
  - `test_manager_reentrant_ipc`;
  - three kernel modules that fail to import;
  - `test_manager_consumption`.
- **Additionally:**
  - Codex's out-of-suite folder and authoring proofs
    (`src/otto/portfolio/fixtures/project_folder.py`, `project_authoring.py`)
    pass;
  - the host modules pass on Python 3.11;
  - the process-level service proof passed with real fences.

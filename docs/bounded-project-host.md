# Bounded project execution

`ExecutionHost(bounded_transports=True)` admits multiple native transports while
all canonical reads, claims, budget operations, callbacks, capture and settlement
run on one owner command thread. A completed A can settle and deliver its result
while B is still waiting. The default host remains synchronous for existing
single-project installations.

The initial shared limits are conjunctive: at most two manager transports, two
worker transports and three transports total. Workers cannot occupy the third
coordination slot. Existing retained requests enter in age order; eligible project
views rotate, with manager continuations before fresh workers within a project.
An unstarted request has no native claim or allowance debit. Same-assignment,
same-session and overlapping worker checkout writes stay serialized. A native
initializer returning another live session is rejected before useful delivery.

Compose one fixed `ManagerJourneyService` per eligible project before starting
the single host. Each view needs its own state object and saver, exact current
manager assignment/generation, task map, run directory, workspace and adapter
factory. Share the same Store object, Due port and owner capabilities. Do not
swap globals such as `WORK`, `MANAGER`, state or the adapter while a turn runs.
`ProjectServices` checks these bindings and rejects mismatched execution ports,
principal, workspace or source. An assignment generation/project replacement
requires recomposition at a closed owner boundary; ordinary current revisions
continue through the canonical authorization checks.

The composition order is:

1. Open the existing owner once, create the closed bounded host and the finite
   service views over that owner's existing handles. Construct each adapter
   freshly for its requested principal, with its view's run path and workspace.
2. Construct `ProjectServices(views, owner_route=authenticate_owner_target)`.
   The injected owner route must verify the existing protected owner grant and
   exact target. It must be repeatable for the same retained request; a JSON
   project ID or caller-selected view name is not authentication.
3. Attach one `NativeProcessCallerIngress` using
   `router.managed_caller_binding`, and pass its `observe` callback and the same
   protected native socket to each view's fresh adapter. Set the host's
   `caller_binding_reader` to that ingress. Keep owner file compatibility only
   for the existing protected owner command directory.
4. Call `router.install()`, then `host.start()` inside the existing cleanup
   guard. `install` reconciles exact current and pending occurrence handles,
   restores uncertain capacity holds, and wires the handler, canonical caller
   resolver and authorizer. It reads no global Due/history inventory and opens
   no extra Store. Startup accepts at most 128 known/pending handles across the
   finite views; reconcile a larger retained set before enabling new admission.

Native callers use the ordinary finite delegate command and return its original
retained handle. They cannot dispatch another long manager turn and wait on it
from inside their own native turn. Internal child starts and result notices route
by the original Due's project and assignment. Child results continue through the
existing exact parent destination and consumption report, including restart.

Only the isolated adapter transport executes off owner. Native admission,
authorization, usage, process-custody observation and result publication marshal
back to the owner. In-memory `OwnerCompletion` values only connect an already
retained command to its eventual owner result; they never cross IPC or introduce
another durable queue. The existing request, Due and atomic response remain the
recovery identities. Use maintained service starts through `ExecutionApplication`;
legacy direct gateway/scheduled-advisor delivery is not a bounded host entrance.

UNKNOWN and stop/cancel retain their slot/session hold; neither is native-exit
evidence. Exact successful settlement, or the existing verified owner worker
custody-release disposition, releases the hold. Recovery does not resend a
provider or reset allowance. Draining stops new transports, captures admitted
ones, and retains their deterministic parent/manager notices for restart. Close
the host and Store before maintenance; never run a second owner against this
composition.

`tests.test_bounded_project_host` uses five disposable projects, one tiny Store,
real owner/gateway/parser/adapter paths and fake native bindings. It proves the
shared caps, A settlement with B live, fair progress, isolated authenticated
views, queued/restart/UNKNOWN behavior, pending-child consumption, session and
checkout fences, and retained drain notices. These are source fixtures, not
installed concurrency or resource-headroom evidence. Adoption still belongs to
the current sole owner, followed by the next real two-project opportunity using
the original handles. Do not manufacture native work to replay the fixture.
